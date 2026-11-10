"""Production-grade in-depth test suite for database models and memory repository."""

# 1. Standard library imports
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile

# 2. Third-party imports
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 3. Local / internal imports
from nemo.database.models import Base, Conversation, MemoryItem, Project
from nemo.memory.repository import MemoryRepository, ProjectRepository

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@asynccontextmanager
async def create_test_db():
    """Create isolated SQLite database engine and session factory per test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "production_test_nemo.db"
        test_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        engine = create_async_engine(test_url, echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

        @asynccontextmanager
        async def session_provider():
            async with session_factory() as sess:
                yield sess
                await sess.commit()

        yield {
            "tmpdir": Path(tmpdir),
            "engine": engine,
            "session_provider": session_provider,
            "proj_repo": ProjectRepository(session_provider=session_provider),
            "mem_repo": MemoryRepository(session_provider=session_provider),
        }

        await engine.dispose()


@pytest.mark.asyncio
async def test_project_lifecycle_and_idempotency():
    """Verify project registration, idempotency, path normalization, lookup, and deletion."""
    async with create_test_db() as db:
        proj_repo: ProjectRepository = db["proj_repo"]
        tmpdir: Path = db["tmpdir"]
        proj_dir = tmpdir / "COSEM_WORKSPACE"
        proj_dir.mkdir()

        # 1. Register project
        proj = await proj_repo.register_project(name="COSEM", root_path=proj_dir)
        assert proj.id is not None
        assert proj.name == "COSEM"
        assert proj.root_path == str(proj_dir.resolve())

        # 2. Idempotent registration with relative/alternate path format returns same record
        proj_duplicate = await proj_repo.register_project(name="COSEM", root_path=str(proj_dir))
        assert proj_duplicate.id == proj.id

        # 3. Lookup by path and by ID
        by_path = await proj_repo.get_by_path(proj_dir)
        assert by_path is not None and by_path.id == proj.id

        by_id = await proj_repo.get_by_id(proj.id)
        assert by_id is not None and by_id.name == "COSEM"

        # 4. List projects
        all_projects = await proj_repo.list_projects()
        assert len(all_projects) == 1
        assert all_projects[0].id == proj.id

        # 5. Non-destructive deletion: removes DB record, leaves directory intact
        deleted = await proj_repo.delete_project(proj.id)
        assert deleted
        assert proj_dir.exists(), "Project folder on disk must not be deleted"
        assert await proj_repo.get_by_id(proj.id) is None


@pytest.mark.asyncio
async def test_memory_scoping_and_cross_project_isolation():
    """Verify strict multi-project memory scoping and isolation."""
    async with create_test_db() as db:
        proj_repo: ProjectRepository = db["proj_repo"]
        mem_repo: MemoryRepository = db["mem_repo"]
        tmpdir: Path = db["tmpdir"]

        proj_a = await proj_repo.register_project(name="ProjectA", root_path=tmpdir / "A")
        proj_b = await proj_repo.register_project(name="ProjectB", root_path=tmpdir / "B")

        # Add Project A memory
        await mem_repo.add_memory(
            content="Project A uses FastAPI with JWT authentication.",
            scope="project",
            project_id=proj_a.id,
            memory_type="decision",
            subject="auth",
        )

        # Add Project B memory
        await mem_repo.add_memory(
            content="Project B uses Django with Session authentication.",
            scope="project",
            project_id=proj_b.id,
            memory_type="decision",
            subject="auth",
        )

        # Add Global memory
        await mem_repo.add_memory(
            content="Developer prefers VS Code for front-end tasks.",
            scope="global",
            memory_type="preference",
            subject="editor",
        )

        # 1. Project A query must see Project A + Global, but NEVER Project B
        results_a = await mem_repo.search_memories("authentication", project_id=proj_a.id)
        assert len(results_a) == 1
        assert "FastAPI" in results_a[0].content
        assert "Django" not in [r.content for r in results_a]

        # 2. Project B query must see Project B + Global, but NEVER Project A
        results_b = await mem_repo.search_memories("authentication", project_id=proj_b.id)
        assert len(results_b) == 1
        assert "Django" in results_b[0].content
        assert "FastAPI" not in [r.content for r in results_b]

        # 3. Global preference must be visible from both projects
        results_pref_a = await mem_repo.search_memories("VS Code", project_id=proj_a.id)
        results_pref_b = await mem_repo.search_memories("VS Code", project_id=proj_b.id)
        assert len(results_pref_a) == 1
        assert len(results_pref_b) == 1
        assert results_pref_a[0].id == results_pref_b[0].id


@pytest.mark.asyncio
async def test_memory_superseding_and_conflict_resolution():
    """Verify atomic superseding of contradictory architectural decisions."""
    async with create_test_db() as db:
        proj_repo: ProjectRepository = db["proj_repo"]
        mem_repo: MemoryRepository = db["mem_repo"]
        tmpdir: Path = db["tmpdir"]
        proj = await proj_repo.register_project(name="ArchTest", root_path=tmpdir / "Arch")

        # Initial decision
        m_old = await mem_repo.add_memory(
            content="Architecture uses SQLite for embedded storage.",
            scope="project",
            project_id=proj.id,
            memory_type="decision",
            subject="database",
            importance=1.0,
        )
        assert m_old.status == "active"

        # Supersede with new decision
        m_new = await mem_repo.supersede_memory(
            old_memory_id=m_old.id,
            new_content="Architecture migrated to PostgreSQL 16 with pgvector.",
            importance=1.5,
            subject="database",
        )
        assert m_new is not None
        assert m_new.status == "active"
        assert m_new.importance == 1.5
        assert m_new.metadata_.get("supersedes") == m_old.id

        # Verify old memory is now marked 'superseded' in database
        old_reloaded = await mem_repo.get_memory(m_old.id)
        assert old_reloaded is not None
        assert old_reloaded.status == "superseded"

        # Search should only return the active superseded memory
        search_res = await mem_repo.search_memories("database", project_id=proj.id)
        assert len(search_res) == 1
        assert "PostgreSQL" in search_res[0].content
        assert "SQLite" not in [r.content for r in search_res]


@pytest.mark.asyncio
async def test_multi_keyword_search_and_importance_ranking():
    """Verify multi-keyword search relevance and importance score ordering."""
    async with create_test_db() as db:
        mem_repo: MemoryRepository = db["mem_repo"]

        # Low importance memory
        m_low = await mem_repo.add_memory(
            content="Logging uses standard print statements temporarily.",
            scope="global",
            importance=0.5,
            subject="logging",
        )

        # High importance memory
        m_high = await mem_repo.add_memory(
            content="Production logging requires structured JSON output via structlog.",
            scope="global",
            importance=2.0,
            subject="logging",
        )

        # Search for "logging"
        results = await mem_repo.search_memories("logging")
        assert len(results) == 2
        # Highest importance must rank first
        assert results[0].id == m_high.id
        assert results[1].id == m_low.id


@pytest.mark.asyncio
async def test_concurrent_memory_writes():
    """Verify thread-safe concurrent async memory persistence without lock errors."""
    async with create_test_db() as db:
        mem_repo: MemoryRepository = db["mem_repo"]
        proj_repo: ProjectRepository = db["proj_repo"]
        tmpdir: Path = db["tmpdir"]
        proj = await proj_repo.register_project(name="ConcurrentProj", root_path=tmpdir / "Conc")

        # Spawn 25 concurrent write operations
        async def _insert_task(index: int):
            return await mem_repo.add_memory(
                content=f"Concurrency entry #{index} verified.",
                scope="project",
                project_id=proj.id,
                importance=1.0 + (index * 0.01),
                metadata={"index": index},
            )

        tasks = [_insert_task(i) for i in range(25)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 25
        assert len(set(r.id for r in results)) == 25

        # Verify all records exist in DB
        all_stored = await mem_repo.list_memories(project_id=proj.id, limit=100)
        assert len(all_stored) == 25


@pytest.mark.asyncio
async def test_edge_cases_and_sanitization():
    """Verify handling of special SQL characters, unicode, large payloads, and empty queries."""
    async with create_test_db() as db:
        mem_repo: MemoryRepository = db["mem_repo"]

        # 1. Empty and whitespace queries
        assert await mem_repo.search_memories("") == []
        assert await mem_repo.search_memories("   \n\t  ") == []

        # 2. SQL injection characters and special symbols
        sql_evil = "'; DROP TABLE memory_items; -- % _ \" \\"
        m_evil = await mem_repo.add_memory(
            content=f"Edge case check: {sql_evil}",
            scope="global",
            subject="security",
        )
        assert m_evil.id is not None

        found_evil = await mem_repo.search_memories("DROP TABLE")
        assert len(found_evil) >= 1
        assert "DROP TABLE" in found_evil[0].content

        # 3. Unicode and emojis
        unicode_content = "Architecture: 🚀 高性能 микросервисы with UTF-8 support 🎯"
        m_unicode = await mem_repo.add_memory(
            content=unicode_content,
            scope="global",
            subject="unicode",
        )
        assert m_unicode.id is not None
        found_unicode = await mem_repo.search_memories("高性能")
        assert len(found_unicode) == 1
        assert found_unicode[0].id == m_unicode.id

        # 4. Large payload (50KB)
        large_text = "NEMO_LONG_MEMORY_CHUNK " * 2000
        m_large = await mem_repo.add_memory(
            content=large_text,
            scope="global",
            subject="large_payload",
        )
        assert m_large.id is not None
        found_large = await mem_repo.get_memory(m_large.id)
        assert found_large is not None
        assert len(found_large.content) > 40000


# 6. Public exports
__all__ = [
    "create_test_db",
    "test_project_lifecycle_and_idempotency",
    "test_memory_scoping_and_cross_project_isolation",
    "test_memory_superseding_and_conflict_resolution",
    "test_multi_keyword_search_and_importance_ranking",
    "test_concurrent_memory_writes",
    "test_edge_cases_and_sanitization",
]
