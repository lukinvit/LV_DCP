"""Authentication routes — login, logout, refresh token."""

from fastapi import APIRouter, Depends, HTTPException

from app.models.user import User
from app.services.auth import authenticate, issue_tokens, refresh_access_token
from app.services.db import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(email: str, password: str, db=Depends(get_session)) -> dict[str, str]:
    user = await authenticate(db, email, password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    access, refresh = await issue_tokens(db, user)
    return {"access_token": access, "refresh_token": refresh}


@router.post("/refresh")
async def refresh(refresh_token: str, db=Depends(get_session)) -> dict[str, str]:
    access = await refresh_access_token(db, refresh_token)
    return {"access_token": access}
