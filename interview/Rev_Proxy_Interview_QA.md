# Rev Proxy — Possible Interview Questions & Answers

## Basics

### 1. What is Rev Proxy?
It's a reverse proxy gateway. The client sends requests to the gateway, the gateway forwards them to a backend, and then returns the backend's response.

### 2. Why are we building it?
To create one entry point where security checks and traffic handling can be added before requests reach backend services.

### 3. What is a reverse proxy?
A server that receives requests on behalf of backend servers and forwards requests/responses between clients and those servers.

### 4. Are the gateway and backend the same server?
They are separate FastAPI applications running on different ports. The gateway is on `8002`; the demo backend is on `8001`.

### 5. What does `BACKEND_NAME` mean?
It's a label returned by the backend so we can tell which instance handled a request. Currently it defaults to `backend-1`; it doesn't mean we already have multiple backends.

## Request flow and code

### 6. Walk me through a request to `/api/data`.
The browser sends `GET /api/data` to port `8002`. FastAPI matches `/{path:path}` and calls `forward_request`. The gateway uses HTTPX to send the request to port `8001`. The backend's `/api/data` route returns JSON. HTTPX receives it, and the gateway returns its body and status to the browser.

### 7. What does `@app.api_route("/{path:path}", ...)` do?
It lets one handler catch different paths and the listed HTTP methods. For example, `/api/data` gives `path="api/data"`.

### 8. Why use HTTPX?
FastAPI handles the incoming request, but we need an HTTP client to send a separate request to the backend. HTTPX does that.

### 9. Why `httpx.AsyncClient`?
It supports asynchronous HTTP requests and connection reuse. We create one client and reuse it instead of creating a new client for every request.

### 10. Why use `lifespan`?
To create the HTTPX client at gateway startup and close it cleanly at shutdown.

### 11. What is `request`?
It's FastAPI's incoming `Request` object. It provides the HTTP method, headers, query parameters, URL and body.

### 12. What does `await request.body()` do?
It reads the incoming request body as bytes so the gateway can forward it to the backend.

### 13. What do `method`, `url`, `params`, `content` and `headers` do in `client.request()`?
- `method`: forwards GET/POST/etc.
- `url`: forwards the path to the configured backend.
- `params`: forwards query parameters.
- `content`: forwards the request body.
- `headers`: forwards the allowed headers.

### 14. What is `upstream_response`?
It's the response received from the backend, including its status code, headers and body.

### 15. How does the response return to the client?
The gateway builds a FastAPI `Response` using the backend response's body, status code and filtered headers.

## Headers

### 16. Why do we exclude some headers?
Because some headers describe the original HTTP connection. The gateway creates a separate connection to the backend, so blindly copying connection-specific headers can cause incorrect behavior.

### 17. Why exclude `Host`?
The incoming `Host` points to the gateway, while the outgoing request targets the backend. We let the HTTP client set the appropriate upstream host.

### 18. Why exclude `Connection` and `Keep-Alive`?
They describe connection behavior for one hop. They should not simply be copied to another connection.

### 19. Why exclude `Transfer-Encoding` and `Content-Length`?
They describe how the original message body is framed. The outgoing HTTP client should manage the outgoing request's framing and length.

### 20. Why use `key.lower()`?
HTTP header names are case-insensitive. Lowercasing makes the exclusion check work for `Host`, `HOST`, or `host`.

### 21. What does the dictionary comprehension do?
It loops over incoming headers and builds a new dictionary containing only headers not present in the exclusion list.

### 22. Do we exclude all headers?
No. We keep most headers, including useful ones like `Content-Type` and `Authorization`, unless their names are in the exclusion list. Authentication checks are not implemented yet.

## Errors and reliability

### 23. What happens if the backend is down?
HTTPX raises a request error. Our gateway catches `httpx.RequestError` and returns HTTP `502 Bad Gateway`.

### 24. What happens if the backend times out?
Our gateway catches `httpx.TimeoutException` first and returns HTTP `504 Gateway Timeout`.

### 25. Why catch timeout before `RequestError`?
A timeout is a more specific HTTPX request error. Catching it first lets us return `504` instead of the general `502`.

### 26. What does `timeout=10.0` mean?
HTTPX uses a 10-second timeout setting for request operations. It does not mean every request always waits exactly 10 seconds.

### 27. What is implemented today?
Basic request forwarding, response returning, header filtering, and handling for upstream connection errors and timeouts.

### 28. What isn't implemented yet?
JWT authentication, role-based access, rate limiting, request filtering, multiple backend load balancing, health checks/failover, structured logging/metrics, and Docker deployment.

## FastAPI and Python concepts

### 29. FastAPI vs. Uvicorn?
FastAPI defines the application and routes. Uvicorn runs the application as an HTTP server.

### 30. What do `async` and `await` mean here?
They let the gateway wait for network I/O asynchronously so it doesn't need to block the whole event loop while waiting for the backend.

### 31. Why is `Response` used?
To return the backend's response body and status code through the gateway.

### 32. Are the four backend endpoints four separate servers?
No. `/health`, `/whoami`, `/api/data`, and `/slow` are four routes in one backend application. Multiple servers would require running separate backend instances.

## Honest limitation to mention
This is currently a learning-stage reverse proxy. It doesn't yet implement the planned security controls, and production-grade HTTP details such as comprehensive hop-by-hop header handling and streaming still need work.
