"""JSON endpoints (stub, real impl in Task 15)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/ping")
def ping() -> dict[str, str]:
    return {"pong": "ok"}
