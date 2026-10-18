
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from app.gateway.rate_limiter import TokenBucketRateLimiter
import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel


# Configuration
BACKEND_URL = "http://127.0.0.1:8001"

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"

DEMO_USERNAME = os.getenv("DEMO_USERNAME", "juhi")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "test123")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


class LoginRequest(BaseModel):
    username: str
    password: str


# Create and close the reusable HTTP client
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        base_url=BACKEND_URL,
        timeout=10.0,
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="Mini Security Gateway", lifespan=lifespan)
rate_limiter = TokenBucketRateLimiter(
    capacity=10,
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
    client: httpx.AsyncClient = request.app.state.client

    try:
        backend_response = await client.get("/admin")
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
    if not JWT_SECRET:
        return JSONResponse(
            status_code=500,
            content={"detail": "JWT_SECRET is not configured"},
        )

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

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
            content={"detail": "Invalid or expired token(Login Again pls)"},
            headers={"WWW-Authenticate": "Bearer"},
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


    client: httpx.AsyncClient = request.app.state.client
    body = await request.body()

    # Do not forward the client's token to the backend
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

    try:
        upstream_response = await client.request(
            method=request.method,
            url="/" + path,
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

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
