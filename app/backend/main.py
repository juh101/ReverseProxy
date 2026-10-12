
import asyncio
import os

from fastapi import FastAPI

app = FastAPI(title="Demo Backend")

BACKEND_NAME = os.getenv("BACKEND_NAME", "backend-1")


@app.get("/health")
async def health_check():
    return {"status": "ok", "backend": BACKEND_NAME}


@app.get("/whoami")
async def whoami():
    return {"message": "Request handled by backend", "backend": BACKEND_NAME}


@app.get("/api/data")
async def get_data():
    return {
        "message": "Hello from the backend!",
        "backend": BACKEND_NAME,
    }


@app.get("/slow")
async def slow_response():
    await asyncio.sleep(2)
    return {"message": "Slow response completed", "backend": BACKEND_NAME}
