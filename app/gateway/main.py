
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

BACKEND_URL = "http://127.0.0.1:8001"
JWT_SECRET = os.getenv("JWT_SECRET")
DEMO_USERNAME = os.getenv("DEMO_USERNAME", "juhi")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "test123")
JWT_ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    username: str
    password: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        base_url=BACKEND_URL,
        timeout=10.0,
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="Mini Security Gateway", lifespan=lifespan)


@app.post("/auth/login")
async def login(credentials: LoginRequest):
    if not JWT_SECRET:
        return JSONResponse(
            status_code=500,
            content={"detail": "JWT_SECRET is not configured",},
        )

    if (
        credentials.username != DEMO_USERNAME
        or credentials.password != DEMO_PASSWORD
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid username or password"},
        )

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": credentials.username,
            "role": "user",
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    return {"access_token": token, "token_type": "bearer"}


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
        username = payload.get("sub")
        if not username:
            raise jwt.InvalidTokenError("Missing subject")
    except jwt.InvalidTokenError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    client: httpx.AsyncClient = request.app.state.client
    body = await request.body()

    # Don't forward the client's token to the backend.
    forwarded_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {
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
