"""Database connection and session lifecycle management."""

# 1. Standard library imports
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# 2. Third-party imports
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# 3. Local / internal imports
from nemo.config.settings import get_settings
from nemo.database.models import Base

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def resolve_database_url() -> str:
    """Return configured database URL or fallback to local SQLite."""
    # Check environment override
    settings = get_settings()
    custom_url = getattr(settings, "database_url", None)
    if custom_url:
        return str(custom_url)

    # Local fallback path: ~/.nemo/nemo.db
    db_path = Path.home() / ".nemo" / "nemo.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def get_engine(db_url: str | None = None) -> AsyncEngine:
    """Get or create singleton async SQLAlchemy engine."""
    global _engine
    if _engine is None or db_url is not None:
        url = db_url or resolve_database_url()
        _engine = create_async_engine(
            url,
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    """Get or create singleton async sessionmaker."""
    global _session_factory
    if _session_factory is None or engine is not None:
        eng = engine or get_engine()
        _session_factory = async_sessionmaker(
            bind=eng,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create database tables idempotently."""
    eng = engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Provide transactional async session scope."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# 6. Public exports
__all__ = [
    "resolve_database_url",
    "get_engine",
    "get_session_factory",
    "init_db",
    "get_db_session",
]

