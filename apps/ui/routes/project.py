"""GET /project/{slug} — project detail route (stub, real impl in Task 15)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/project/{slug}")
def project(slug: str) -> dict[str, str]:
    return {"stub": "project route placeholder", "slug": slug}
