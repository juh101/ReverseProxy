# Rev Proxy --- Latest Implementation Notes

These notes cover the features implemented after the earlier Rev Proxy
and Bearer Token notes: a separate backend admin endpoint routed through
the gateway, plus an in-memory Token Bucket rate limiter.

## 1. Current architecture

-   **Gateway:** FastAPI, running locally on port `8002`.
-   **Backend:** FastAPI, running locally on port `8001`.
-   **Gateway responsibilities:** JWT validation, role checks for the
    admin endpoint, rate limiting, request forwarding, and handling
    upstream timeout/connection errors.
-   **Backend responsibilities:** Respond to backend routes, including
    `/admin`.

Typical request flow for an authorized admin request:

1.  Postman sends `GET /admin` to the gateway with a Bearer JWT.
2.  Gateway checks that the token exists and is valid.
3.  Gateway checks that the JWT contains `role: "admin"`.
4.  Gateway's rate limiter checks the client-IP bucket.
5.  If allowed, the gateway sends `GET /admin` to the backend.
6.  The gateway returns the backend response to Postman.

A request rejected by authentication, authorization, or rate limiting
does not get forwarded to the backend.

## 2. Separate backend `/admin` endpoint

In `app/backend/main.py`:

``` python
@app.get("/admin")
async def admin_dashboard():
    return {"message": "Welcome, admin", "source": "backend"}
```

This endpoint is implemented in the backend, so an authorized admin
request can travel through the gateway and receive a response from the
backend.

The `source` field is a useful manual-testing signal that the response
came from the backend endpoint, not a hardcoded gateway response.

## 3. Gateway admin authorization

In `app/gateway/main.py`, the separate `GET /admin` handler:

1.  Reads the `Authorization` header.
2.  Expects the `Bearer <token>` format.
3.  Decodes and validates the JWT using the configured secret and
    algorithm.
4.  Returns `401 Unauthorized` when the token is missing, invalid, or
    expired.
5.  Returns `403 Forbidden` when the token is valid but its role is not
    `admin`.
6.  For an authorized admin, calls the existing HTTP client to request
    `/admin` from the backend.
7.  Returns the backend response to the client.

### Why a separate route?

The specific `GET /admin` route is declared before the catch-all
`/{path:path}` route. This lets FastAPI match `/admin` to the dedicated
handler instead of the general proxy handler.

The catch-all route continues to handle other protected paths such as
`/whoami` and `/api/data`.

### Error handling

-   `401`: missing or invalid/expired Bearer token.
-   `403`: valid token without the required admin role.
-   `502`: gateway cannot communicate with the backend.
-   `504`: backend request times out.
-   `200`: successful request, assuming the backend responds
    successfully.

## 4. Token Bucket rate limiter

Implemented in `app/gateway/rate_limiter.py`.

Configuration:

-   **Capacity:** 10 tokens per client bucket.
-   **Initial tokens:** 10 for a new client.
-   **Refill:** 1 token every 10 seconds.
-   **Cost per allowed request:** 1 token.
-   **Empty bucket:** reject with HTTP `429 Too Many Requests`.

The limiter is instantiated in `app/gateway/main.py` and used by the
protected admin handler and catch-all proxy handler.

## 5. How the Token Bucket code works

The `TokenBucketRateLimiter` class maintains a dictionary of buckets.
Each bucket records the token count and the timestamp used for refill
calculations.

### `__init__`

Stores the bucket capacity and refill interval, initializes the bucket
dictionary, and creates an `asyncio.Lock`.

### `allow_request(client_id)`

1.  Acquires the lock so simultaneous requests cannot update a bucket at
    the same time.
2.  Reads the monotonic clock using `time.monotonic()`.
3.  Creates a full bucket if this client ID has not been seen before.
4.  Calculates elapsed time since the last refill.
5.  Adds one token for each complete 10-second interval, without
    exceeding capacity.
6.  Returns `False` if no token is available.
7.  Otherwise consumes one token and returns `True`.

`time.monotonic()` is useful for measuring elapsed time because it is
not affected by wall-clock changes.

The lock makes updates safe between concurrent coroutines inside this
Python process. It does not share state between separate worker
processes or machines.

## 6. Client identification and limits

The current gateway code uses `request.client.host` as `client_id`.

Consequences:

-   Requests from the same IP address share a bucket.
-   During local Postman testing, requests usually come from
    `127.0.0.1`, so they share the same bucket.
-   Multiple real users behind the same NAT/proxy may share an IP
    bucket.
-   This is an initial implementation, not a robust identity-based or
    distributed rate limiter.

## 7. Rate-limit response

When the bucket is empty, the gateway returns:

``` json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

HTTP status: `429 Too Many Requests`

The response includes `Retry-After: 10`. This is a fixed hint; it does
not calculate the exact time until the next token. Depending on how much
of the refill interval has already elapsed, the next token may arrive
sooner than 10 seconds.

Authentication is checked before rate limiting in the protected
handlers. The current implementation does **not** rate-limit
`/auth/login`.

## 8. Example token sequence

For a new client:

  Request               Tokens before request Result
  ------------------- ----------------------- ---------------------
  1                                        10 Allowed; 9 remain
  2                                         9 Allowed; 8 remain
  ...                                     ... ...
  10                                        1 Allowed; 0 remain
  11, before refill                         0 Rejected with `429`

After the bucket is empty, one token becomes available for each
completed 10-second refill interval, up to a maximum of 10.

## 9. Manual testing in Postman

### Test A --- Admin reaches the backend

1.  Send `POST http://localhost:8002/auth/login` with the configured
    admin credentials.
2.  Copy the returned `access_token`.
3.  Send `GET http://localhost:8002/admin`.
4.  Choose **Authorization → Bearer Token** and paste the token.
5.  Expected: `200 OK`, with a response containing
    `"source": "backend"`.

### Test B --- Normal user cannot access `/admin`

1.  Log in with the normal-user credentials.
2.  Use that user's token for `GET http://localhost:8002/admin`.
3.  Expected: `403 Forbidden`.

### Test C --- Missing token

Send `GET http://localhost:8002/admin` without a Bearer token.

Expected: `401 Unauthorized`.

### Test D --- Rate limit

1.  Use a valid token.
2.  Send repeated requests from the same client IP to a protected route.
3.  Ten requests can consume the initial ten tokens if no refill
    interval elapses between them.
4.  An additional request while the bucket is empty should return `429`.
5.  Wait for a refill interval and retry.

### Test E --- Backend unavailable

1.  Keep the gateway running.
2.  Stop the backend.
3.  Send a valid, authorized request before the rate limit is exhausted.
4.  Expected: `502 Bad Gateway` if the connection fails, or
    `504 Gateway Timeout` if the backend times out.

## 10. Current limitations and not-yet-implemented features

-   Rate-limit buckets are stored in process memory; restarting the
    gateway resets them.
-   Multiple Uvicorn worker processes do not share the bucket counters.
-   The current key is client IP, not a user ID or API key.
-   `/auth/login` is not currently rate-limited.
-   `Retry-After` is fixed at 10 seconds rather than calculated
    precisely.
-   The admin demo endpoint returns static demo data.
-   A database-backed multi-user account system has **not** been
    implemented; the configured demo credentials are still used.
-   WAF rules, load balancing across multiple backend instances, health
    checks/failover, structured logging, metrics, automated test
    coverage, and Docker Compose are still planned, not completed.

## Interview summary

"I implemented a FastAPI reverse-proxy gateway with JWT authentication,
role-based access control for an admin route, upstream error handling,
and an in-memory Token Bucket rate limiter. The admin request is
authorized at the gateway and then forwarded to a separate backend
endpoint. The limiter gives each client IP a bucket of 10 tokens and
replenishes one token every 10 seconds; when the bucket is empty, the
gateway returns HTTP 429 before forwarding the request."
