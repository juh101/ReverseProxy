from pathlib import Path

notes = r"""# Rev Proxy — Notes

## What we're making
Rev Proxy is a gateway that sits between the client and backend. The client talks to the gateway; the gateway forwards the request to the backend and returns the backend's response.

## Current setup
- Project folder: `D:\Projs26\revProxy`
- Python 3.12.8; virtual environment: `.venv`
- Backend runs on port `8001`
- Gateway runs on port `8002` (`8000` gave Windows `WinError 10013`)
- Stack: FastAPI, Uvicorn, HTTPX, Pytest
- Run commands from the project root with `.venv` activated.

## How to run
Terminal 1 — backend:
```powershell
python -m uvicorn app.backend.main:app --reload --port 8001
```

Terminal 2 — gateway:
```powershell
python -m uvicorn app.gateway.main:app --reload --port 8002
```

## Current flow
Example: browser opens `http://localhost:8002/api/data`

1. Browser sends request to gateway on port `8002`.
2. `@app.api_route("/{path:path}", ...)` catches the path. For `/api/data`, `path` is `api/data`.
3. `Request` gives us method, headers, query parameters and body.
4. `await request.body()` reads the request body.
5. `httpx.AsyncClient` sends a new request to `http://127.0.0.1:8001/api/data`.
6. Backend's `/api/data` function runs and returns JSON.
7. HTTPX receives that backend response as `upstream_response`.
8. Gateway filters response headers and uses `Response(...)` to return the body and status code to the browser.

Flow:
`Client → Gateway :8002 → HTTPX → Backend :8001 → Gateway → Client`

## What the backend endpoints do
File: `app/backend/main.py`
- `GET /health`: says the backend is healthy.
- `GET /whoami`: returns the backend name.
- `GET /api/data`: returns sample JSON.
- `GET /slow`: waits 2 seconds, then returns JSON.
- `BACKEND_NAME` defaults to `backend-1`; this is a label, not another server.

## Gateway code — what each important part does
File: `app/gateway/main.py`

- `BACKEND_URL = "http://127.0.0.1:8001"`: tells the gateway where the backend is. It doesn't start the backend.
- `lifespan(...)`: runs setup at gateway startup and cleanup at shutdown.
- `httpx.AsyncClient(...)`: creates one reusable HTTP client. Reusing it avoids making a new client for every request.
- `app.state.client`: stores that client so request handlers can use it.
- `@app.api_route("/{path:path}", methods=[...])`: one route catches many paths and the listed HTTP methods.
- `path`: the path part, e.g. `api/data`; query parameters are separate.
- `request.method`: keeps the incoming method, e.g. GET or POST.
- `url="/" + path`: turns `api/data` into `/api/data`; HTTPX combines it with the base URL.
- `params=request.query_params`: forwards query parameters, e.g. `?page=2`.
- `content=body`: forwards the request body, e.g. JSON sent with POST.
- `headers={...}`: forwards most incoming headers.

## Why do we exclude headers?
We don't blindly copy every header from one HTTP connection to another. Some headers describe the original connection and should be recalculated or not forwarded.

The current request-header exclusion list contains:
`host`, `connection`, `keep-alive`, `proxy-authenticate`, `proxy-authorization`, `te`, `trailer`, `transfer-encoding`, `upgrade`, `content-length`.

- `Host`: the destination is different; the outgoing request should identify the upstream host correctly.
- `Connection`, `Keep-Alive`, `TE`, `Trailer`, `Transfer-Encoding`, `Upgrade`: connection-specific/hop-by-hop headers; copying them blindly between connections can cause issues.
- `Proxy-Authenticate`, `Proxy-Authorization`: proxy-specific authentication headers.
- `Content-Length`: HTTPX should handle the outgoing body's length rather than blindly reuse the incoming value.
- `key.lower()`: header names are case-insensitive, so `Host` and `host` must be treated the same.
- The dictionary comprehension copies only headers whose names are not in the exclusion set.

The response has a similar exclusion list. Then:
`Response(content=upstream_response.content, status_code=upstream_response.status_code, headers=response_headers)`
returns the backend body and status code to the client.

Note: this is a learning-stage proxy. A production proxy should also handle headers nominated by `Connection`, streaming, and more HTTP edge cases.

## Error handling we added
- `httpx.TimeoutException` → returns JSON with HTTP `504` (Gateway Timeout).
- `httpx.RequestError` → returns JSON with HTTP `502` (Bad Gateway).
- Timeout is caught first because it's a specific kind of request error.
- Manually tested: normal forwarding works; stopping the backend gives a `502`; timeout handling was reported to work.

## What is implemented vs. planned
Implemented now:
- Basic request forwarding and response returning
- Reusable HTTPX client
- Header filtering
- 502/504 error handling

Planned next:
- Pytest automated tests
- JWT authentication + roles
- Token-bucket rate limiting
- Rule-based request filtering
- Multiple backends, round-robin load balancing, health checks and failover
- Logging and metrics
- Docker Compose

Do not say planned features are already implemented.
"""

from pathlib import Path

content = """# Bearer Token — Brief Notes

## What is a Bearer Token?
A bearer token is a credential sent with a request. Whoever possesses a valid token can present it to request access.

Think of it like an event pass:
- JWT = the pass
- Gateway = the security guard
- Backend = the protected area

## How it works in Rev Proxy
1. Client sends username and password to `POST /auth/login`.
2. Gateway checks the demo credentials.
3. If correct, gateway creates a signed JWT and returns it as `access_token`.
4. Client sends the token with later requests in this header:

   ```http
   Authorization: Bearer <token>
   ```

5. Gateway reads the `Authorization` header and separates the scheme (`Bearer`) from the token.
6. Gateway verifies the JWT signature and expiry using the configured secret and `HS256`.
7. Valid token → request is forwarded to the backend.
8. Missing, invalid, or expired token → gateway returns `401 Unauthorized`.

## Important code
```python
authorization = request.headers.get(\"Authorization\", \"\")
scheme, _, token = authorization.partition(\" \")
```
- `authorization`: reads the header.
- `scheme`: should be `Bearer`.
- `token`: the actual JWT string.

```python
payload = jwt.decode(
    token,
    JWT_SECRET,
    algorithms=[JWT_ALGORITHM],
)
```
Verifies the token and returns its claims/payload.

## Example Postman setup
- Login: `POST http://localhost:8002/auth/login`
- Body → raw → JSON:
  ```json
  {
    \"username\": \"juhi\",
    \"password\": \"test123\"
  }
  ```
- Copy `access_token` from the response.
- Protected request: `GET http://localhost:8002/whoami`
- Authorization tab → **Bearer Token** → paste the token.

## Key points
- `Bearer` is the authentication scheme; it is not part of the JWT itself.
- A valid JWT is signed, not encrypted. Do not store passwords or secrets in its payload.
- A token is a possession-based credential: anyone who steals it may try to use it until it expires.
- Use HTTPS in production and never commit tokens or real secrets to GitHub.
- Authentication answers **“Who are you?”**; authorization answers **“What are you allowed to access?”** Role-based authorization is a separate feature we will add later.
"""
path = Path("/mnt/data/Bearer_Token_Notes.md")
path.write_text(content, encoding="utf-8")
print(f"Created: {path}")

