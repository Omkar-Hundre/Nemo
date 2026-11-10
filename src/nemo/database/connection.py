"""Database connection, migration, backup, and session lifecycle management."""

# 1. Standard library imports
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

# 2. Third-party imports
from sqlalchemy import inspect, text
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


def _sync_schema_sync(sync_conn) -> None:
    """Create missing tables and add missing columns to existing tables idempotently."""
    Base.metadata.create_all(sync_conn)

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    for table_name, table in Base.metadata.tables.items():
        if table_name in existing_tables:
            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(dialect=sync_conn.dialect)
                    default_clause = ""
                    if str(col_type).upper() in ("JSON", "TEXT") and "metadata" in col.name:
                        default_clause = " DEFAULT '{}'"
                    sync_conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}")
                    )

    if "memory_items" in existing_tables:
        sync_conn.execute(text("UPDATE memory_items SET metadata = '{}' WHERE metadata IS NULL"))


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create database tables and apply schema evolution idempotently."""
    eng = engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(_sync_schema_sync)


def get_sqlite_path(db_url: str | None = None) -> Path | None:
    """Extract filesystem path from SQLite database URL if applicable."""
    url = db_url or resolve_database_url()
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        return Path(url[len(prefix):])
    prefix_sync = "sqlite:///"
    if url.startswith(prefix_sync):
        return Path(url[len(prefix_sync):])
    return None


def backup_database(destination: Path | str | None = None) -> Path:
    """Perform atomic hot backup of local SQLite database."""
    source_path = get_sqlite_path()
    if not source_path or not source_path.exists():
        raise FileNotFoundError(f"Database file not found at {source_path}")

    if destination:
        dest_path = Path(destination).resolve()
    else:
        backup_dir = Path.home() / ".nemo" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest_path = backup_dir / f"nemo_backup_{timestamp}.db"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(source_path)
    dst_conn = sqlite3.connect(dest_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    return dest_path


def restore_database(source: Path | str) -> Path:
    """Restore local SQLite database from a backup file."""
    src_path = Path(source).resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"Backup file does not exist: {src_path}")

    target_path = get_sqlite_path()
    if not target_path:
        raise ValueError("Cannot determine target SQLite database path.")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(target_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    return target_path


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
    "get_sqlite_path",
    "backup_database",
    "restore_database",
]

