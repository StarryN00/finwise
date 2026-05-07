"""
Database module - Async SQLAlchemy with SQLite for testing.
For production, use PostgreSQL via DATABASE_URL env var.
"""
import os
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# Use SQLite for testing if DATABASE_URL is not set or explicitly set to "sqlite+aiosqlite:"
_use_sqlite = os.environ.get("DATABASE_URL", "").startswith("sqlite") or os.environ.get("TESTING", "").lower() == "true"

if _use_sqlite:
    _db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./finwise_test.db")
else:
    _db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/finwise"
    )


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    _db_url,
    echo=os.environ.get("DB_ECHO", "false").lower() == "true",
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables. Call on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose engine. Call on shutdown."""
    await engine.dispose()