
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from app.gateway.rate_limiter import TokenBucketRateLimiter
import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from app.gateway.waf import (
    MAX_BODY_SIZE,
    is_bad_path,
    is_suspicious,
)
import asyncio


# Configuration
BACKENDS = [
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8003",
    "http://127.0.0.1:8004",
    "http://127.0.0.1:8005",
]


class BackendPool:
    def __init__(self, backends: list[str]):
        if not backends:
            raise ValueError("At least one backend is required")

        self.backends = backends
        self.healthy_backends: set[str] = set()
        self.index = 0
        self.lock = asyncio.Lock()

    async def update_health(self, clients: dict):
        async def check(backend: str):
            try:
                response = await clients[backend].get(
                    f"{backend}/health"
                )
                return backend, response.status_code == 200
            except httpx.RequestError:
                return backend, False

        results = await asyncio.gather(
            *(check(backend) for backend in self.backends)
        )

        async with self.lock:
            self.healthy_backends = {
                backend
                for backend, healthy in results
                if healthy
            }

    async def next_backend(self) -> str | None:
        async with self.lock:
            if not self.healthy_backends:
                return None

            for offset in range(len(self.backends)):
                position = (self.index + offset) % len(self.backends)
                backend = self.backends[position]

                if backend in self.healthy_backends:
                    self.index = (position + 1) % len(self.backends)
                    return backend

            return None


backend_pool = BackendPool(BACKENDS)
# healthy_backends stores the backends that respond successfully to /health.
# update_health() checks all four backends.
# next_backend() skips unhealthy instances.
# If no healthy backend exists, it returns None.

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"

DEMO_USERNAME = os.getenv("DEMO_USERNAME", "juhi")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "test123")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


class LoginRequest(BaseModel):
    username: str
    password: str

# Periodically check whether backends are healthy.
async def health_check_loop(app: FastAPI):
    while True:
        await asyncio.sleep(5)
        await backend_pool.update_health(app.state.clients)

# Create and close the reusable HTTP client
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.clients = {
        backend: httpx.AsyncClient(timeout=10.0)
        for backend in BACKENDS
    }

    # Check backend health immediately at startup.
    await backend_pool.update_health(app.state.clients)

    health_task = asyncio.create_task(health_check_loop(app))

    try:
        yield
    finally:
        health_task.cancel()

        try:
            await health_task
        except asyncio.CancelledError:
            pass

        for client in app.state.clients.values():
            await client.aclose()

app = FastAPI(title="Mini Security Gateway", lifespan=lifespan)
rate_limiter = TokenBucketRateLimiter(
    capacity=5,
    refill_interval=10,
)

# 1. Login endpoint
@app.post("/auth/login")
async def login(credentials: LoginRequest):
    if not JWT_SECRET:
        return JSONResponse(
            status_code=500,
            content={"detail": "JWT_SECRET is not configured"},
        )

    if (
        credentials.username == DEMO_USERNAME
        and credentials.password == DEMO_PASSWORD
    ):
        role = "user"

    elif (
        credentials.username == ADMIN_USERNAME
        and credentials.password == ADMIN_PASSWORD
    ):
        role = "admin"

    else:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid username or password"},
        )

    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": credentials.username,
            "role": role,
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
    }


# 2. Separate admin endpoint

@app.get("/admin")
async def admin_dashboard(request: Request):
    if not JWT_SECRET:
        return JSONResponse(
            status_code=500,
            content={"detail": "JWT_SECRET is not configured"},
        )
    
    # Rate limit this client's requests
    client_id = (
        request.client.host
        if request.client
        else "unknown"
    )

    allowed = await rate_limiter.allow_request(client_id)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
            headers={"Retry-After": "10"},
        )


    # 1. Read the Bearer token
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Validate the JWT
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.InvalidTokenError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Check the user's role
    if payload.get("role") != "admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Admin access required"},
        )

    # 4. Forward the authorized request to the backend
    
    # Select a healthy backend.
    backend_url = await backend_pool.next_backend()

    if backend_url is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "No healthy backends available"},
        )

    client: httpx.AsyncClient = request.app.state.clients[backend_url]

    try:
        backend_response = await client.get(
            f"{backend_url}/admin"
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"detail": "Backend request timed out"},
        )
    except httpx.RequestError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Could not communicate with backend"},
        )

    # 5. Return the backend's response to the client
    return Response(
        content=backend_response.content,
        status_code=backend_response.status_code,
        media_type=backend_response.headers.get("content-type"),
    )


# 3. Catch-all route: authenticate and forward other requests
@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def forward_request(path: str, request: Request):
    # 1. Check JWT configuration
    if not JWT_SECRET:
        return JSONResponse(
            status_code=500,
            content={"detail": "JWT_SECRET is not configured"},
        )

    # 2. Extract the Bearer token
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Validate the JWT
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )

        if not payload.get("sub"):
            raise jwt.InvalidTokenError("Missing subject")

    except jwt.InvalidTokenError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token. Login again."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Rate-limit this client's requests
    client_id = (
        request.client.host
        if request.client
        else "unknown"
    )

    allowed = await rate_limiter.allow_request(client_id)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
            headers={"Retry-After": "10"},
        )

    # 5. WAF: Reject suspicious paths
    if is_bad_path(path):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid request path"},
        )

    # 6. WAF: Early check using Content-Length
    content_length = request.headers.get("content-length")

    if content_length is not None:
        try:
            if int(content_length) > MAX_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Content-Length"},
            )

    # 7. Read the request body
    body = await request.body()

    # 8. WAF: Check actual body size
    if len(body) > MAX_BODY_SIZE:
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large"},
        )

    # 9. WAF: Check query and body for suspicious patterns
    query = request.url.query
    body_text = body.decode("utf-8", errors="ignore")

    if is_suspicious(query) or is_suspicious(body_text):
        return JSONResponse(
            status_code=403,
            content={"detail": "Request blocked by WAF"},
        )

    # 10. Filter headers before forwarding
    excluded_request_headers = {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "authorization",
    }

    forwarded_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_request_headers
    }

    # 11. Round-robin: select the next backend
    
    # 11. Select a healthy backend.
    backend_url = await backend_pool.next_backend()

    if backend_url is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "No healthy backends available"},
        )

    client: httpx.AsyncClient = request.app.state.clients[backend_url]

    # 12. Forward the request to the selected backend
    try:
        upstream_response = await client.request(
            method=request.method,
            url=f"{backend_url}/{path}",
            params=request.query_params,
            content=body,
            headers=forwarded_headers,
        )

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"detail": "Backend request timed out"},
        )

    except httpx.RequestError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Could not communicate with backend"},
        )

    # 13. Filter hop-by-hop response headers
    excluded_response_headers = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in excluded_response_headers
    }

    # 14. Return the backend response to the client
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
