"""Scheduled cleanup of expired sessions."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


async def cleanup_expired_sessions(db: AsyncSession) -> int:
    stmt = delete(Session).where(Session.expires_at < datetime.utcnow())
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0
