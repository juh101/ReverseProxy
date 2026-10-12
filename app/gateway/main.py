
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

BACKEND_URL = "http://127.0.0.1:8001"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        base_url=BACKEND_URL,
        timeout=10.0,
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="Mini Security Gateway", lifespan=lifespan)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def forward_request(path: str, request: Request):
    client: httpx.AsyncClient = request.app.state.client

    body = await request.body()

    upstream_response = await client.request(
        method=request.method,
        url="/" + path,
        params=request.query_params,
        content=body,
        headers={
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
            }
        },
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
