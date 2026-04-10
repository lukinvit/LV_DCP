"""Entrypoint — wires FastAPI app, routers, and lifespan."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.handlers import auth, profile
from app.services.db import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(lifespan=lifespan)
app.include_router(auth.router)
app.include_router(profile.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
