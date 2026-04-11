"""GET / — index route (stub, real implementation in Task 15)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def index() -> dict[str, str]:
    return {"stub": "index route placeholder — replaced in Task 15"}
