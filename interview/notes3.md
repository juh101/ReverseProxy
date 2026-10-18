# Mini Security Gateway --- Notes (Part 2)

> These notes continue from the previous notes. They cover only the
> newer material: WAF, header filtering, multiple backends, round-robin
> selection, and the proposed health-check update. They do not repeat
> the earlier JWT/admin/RBAC/token-bucket explanation.

## 1. Web Application Firewall (WAF)

The WAF code is in `app/gateway/waf.py` and is called by the gateway
before a request is forwarded.

### Path filtering

`is_bad_path(path)` decodes the path and rejects it if it contains: - A
null byte (`\x00`) - A backslash (`\`) - A path segment equal to `..`

The gateway returns `400 Bad Request` for a rejected path.

### Request body size

``` python
MAX_BODY_SIZE = 1 * 1024 * 1024
```

The maximum body size is 1 MiB.

The gateway first checks `Content-Length` if the header is present. It
then reads the body and checks its actual length too. If the body is too
large, it returns `413 Payload Too Large`.

Important limitation: checking the actual length after reading the full
body does not, by itself, prevent all memory-exhaustion problems. A
production implementation would need stronger streaming and server-level
limits.

### Basic SQL injection and XSS pattern checks

The WAF checks the query string and decoded request body for simple
patterns.

Examples include: - SQL injection-like patterns: `UNION SELECT`,
`OR 1=1`, `DROP TABLE`, `SELECT ... FROM` - XSS-like patterns:
`<script`, `javascript:`, `onerror=`, `onload=`

If a pattern matches, the gateway returns `403 Forbidden`.

These are basic pattern checks, not a complete WAF. They can block some
suspicious input, but they can also miss attacks or reject legitimate
input.

## 2. Header filtering

Before forwarding the request, the gateway removes selected headers.

Examples: - `Host` - `Connection` - `Keep-Alive` -
`Proxy-Authenticate` - `Proxy-Authorization` - `TE` - `Trailer` -
`Transfer-Encoding` - `Upgrade` - `Content-Length` - `Authorization`

Many of these are hop-by-hop headers, meaning they relate to one
particular HTTP connection and should not simply be forwarded to the
next connection. The gateway also removes the incoming `Authorization`
header because it validates the JWT itself.

The response filters hop-by-hop headers and `Content-Length` too.

## 3. Multiple backend instances

The same FastAPI backend source file is run several times, using
different environment values and ports.

  Instance      Port `BACKEND_NAME`
  ----------- ------ ----------------
  Backend 1     8001 `backend-1`
  Backend 2     8003 `backend-2`
  Backend 3     8004 `backend-3`
  Backend 4     8005 `backend-4`
  Gateway       8002 ---

The backend includes endpoints such as: - `/health`: returns a health
status and backend name - `/whoami`: identifies which backend handled
the request - `/api/data`: returns sample data - `/slow`: waits about
two seconds - `/admin`: returns a sample admin response

Each backend runs in its own terminal. Example for backend 1:

``` powershell
.\.venv\Scripts\Activate.ps1
$env:BACKEND_NAME = "backend-1"
python -m uvicorn app.backend.main:app --port 8001
```

For the other instances, use the corresponding name and port.

## 4. Round-robin load balancing

The gateway has a `BackendPool` class that stores backend URLs and an
index.

Basic idea: 1. Select the backend at the current index. 2. Move the
index forward for the next request. 3. Wrap around to the beginning
after the last backend.

For four healthy backends, the expected sequence after a fresh start is
backend 1, backend 2, backend 3, backend 4, then back to backend
1---assuming no other requests consume selections.

An `asyncio.Lock` protects the backend selection and index update from
overlapping coroutines.

The user confirmed the four-backend round-robin behavior was working as
expected.

## 5. Proposed health checks

The next proposed improvement is to check backend health before
selecting a backend.

The suggested design: - Call each backend's `/health` endpoint. - Keep a
set of healthy backend URLs. - Run an initial health check during
application startup. - Run a periodic health-check loop approximately
every five seconds. - Select only backends currently marked healthy. -
Return `503 Service Unavailable` if no healthy backends are available.

A backend that comes back online should be able to rejoin the healthy
set after a later successful health check.

**Status:** The health-check code was discussed and provided as an
update, but its application and test results have not been confirmed. Do
not claim this feature is complete until it is verified in `main.py` and
tested.

## 6. Failover limitation

Health-aware selection cannot prevent every backend error. A backend may
go down after the last health check but before the gateway sends a
request. That request may still fail.

Retry-based failover---trying another healthy backend after an upstream
failure---is a separate improvement and was not confirmed as
implemented.

The existing upstream error handling is: - `httpx.TimeoutException` →
`504 Gateway Timeout` - Other `httpx.RequestError` → `502 Bad Gateway`

## 7. Manual checks discussed

### WAF checks confirmed

-   A suspicious XSS-style query returned `403`.
-   A request body larger than 1 MiB returned `413`.

### Round-robin check confirmed

The user reported that the four-backend round-robin sequence was working
as expected.

### Health-check test still needed

After applying the health-check change: 1. Keep all four backend
instances running. 2. Restart the gateway and confirm health checks
start. 3. Stop only backend 2. 4. Wait at least five seconds. 5. Send
authenticated requests through the gateway. 6. Confirm backend 2 is
skipped. 7. Restart backend 2 and check whether it rejoins after a
successful health check.

The gateway's rate limiter can affect repeated testing, so avoid sending
unnecessary requests during this test.

## 8. Interview questions and answers

### Q1. What does your WAF check?

It checks for invalid paths, request bodies over 1 MiB, and simple SQL
injection/XSS patterns in query strings and request bodies.

### Q2. What status codes does the WAF return?

`400` for invalid paths or invalid `Content-Length`, `413` for oversized
bodies, and `403` when suspicious patterns match.

### Q3. Is this a production-grade WAF?

No. It is a basic learning implementation based on pattern matching. It
can miss attacks and can block legitimate requests.

### Q4. Why filter HTTP headers?

Some headers are specific to one connection and should not be blindly
forwarded. The gateway also validates the client's token itself, so the
incoming `Authorization` header is removed before forwarding.

### Q5. What is round-robin load balancing?

It sends requests to backends in sequence, moving to the next backend
each time and wrapping back to the first.

### Q6. Why use multiple backend instances?

To demonstrate how requests can be distributed across several servers
and to create a base for availability improvements.

### Q7. What is a health check?

A request to an endpoint such as `/health` to determine whether a
backend is responding as expected.

### Q8. Does round-robin alone skip a failed backend?

No. Basic round-robin only follows the configured list. Health-aware
selection must be added to skip backends marked unhealthy.

### Q9. What is the difference between health checks and failover?

Health checks periodically measure whether backends appear healthy.
Failover attempts to use another backend when the selected backend fails
during an actual request.

### Q10. What happens if all backends are unhealthy?

The proposed health-aware version returns `503 Service Unavailable`, but
this behavior must be tested after the change is applied.
