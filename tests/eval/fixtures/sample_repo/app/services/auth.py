"""Authentication service — password check, token issuance, refresh flow."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.user import User

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    from sqlalchemy import select
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or user.hashed_password != hash_password(password):
        return None
    return user


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(48)
    session = Session(
        user_id=user.id,
        access_token=access,
        refresh_token=refresh,
        expires_at=datetime.utcnow() + ACCESS_TTL,
    )
    db.add(session)
    await db.commit()
    return access, refresh


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    from sqlalchemy import select
    stmt = select(Session).where(Session.refresh_token == refresh_token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise ValueError("invalid refresh token")
    new_access = secrets.token_urlsafe(32)
    session.access_token = new_access
    session.expires_at = datetime.utcnow() + ACCESS_TTL
    await db.commit()
    return new_access


async def current_user(db: AsyncSession, access_token: str) -> User:
    from sqlalchemy import select
    stmt = select(Session).where(Session.access_token == access_token)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None or session.expires_at < datetime.utcnow():
        raise ValueError("expired or unknown token")
    user_stmt = select(User).where(User.id == session.user_id)
    return (await db.execute(user_stmt)).scalar_one()
