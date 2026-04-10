"""User profile routes."""

from fastapi import APIRouter, Depends

from app.models.user import User
from app.services.auth import current_user

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def me(user: User = Depends(current_user)) -> dict[str, str | bool]:
    return {"email": user.email, "is_active": user.is_active}
