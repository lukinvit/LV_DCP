"""Database engine and session lifecycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global _engine, _factory
    _engine = create_async_engine("postgresql+asyncpg://localhost/sample")
    _factory = async_sessionmaker(_engine, expire_on_commit=False)


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncSession:
    assert _factory is not None, "init_db not called"
    async with _factory() as session:
        yield session
