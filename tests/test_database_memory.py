"""Production-grade in-depth test suite for database models and memory repository."""

# 1. Standard library imports
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sqlite3
import tempfile

# 2. Third-party imports
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 3. Local / internal imports
from nemo.database.connection import backup_database, init_db, restore_database
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


@pytest.mark.asyncio
async def test_database_schema_evolution_and_backup_restore(monkeypatch):
    """Verify that init_db automatically migrates legacy databases without data loss and tests hot backup/restore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        legacy_db_file = Path(tmpdir) / "legacy_nemo.db"

        # 1. Manually create an older schema lacking 'metadata' column
        con = sqlite3.connect(legacy_db_file)
        con.execute("""
            CREATE TABLE memory_items (
                id VARCHAR(36) PRIMARY KEY,
                scope VARCHAR(50) DEFAULT 'global',
                project_id VARCHAR(36),
                type VARCHAR(50) DEFAULT 'fact',
                subject VARCHAR(200),
                predicate VARCHAR(100),
                object VARCHAR(200),
                content TEXT NOT NULL,
                importance FLOAT DEFAULT 1.0,
                confidence FLOAT DEFAULT 1.0,
                status VARCHAR(50) DEFAULT 'active',
                created_at DATETIME,
                updated_at DATETIME
            )
        """)
        con.execute("""
            INSERT INTO memory_items (id, scope, content, importance, confidence, status)
            VALUES ('legacy-uuid-1', 'global', 'Legacy memory record without metadata column', 1.0, 1.0, 'active')
        """)
        con.commit()
        con.close()

        # 2. Point engine to legacy db and run init_db
        test_url = f"sqlite+aiosqlite:///{legacy_db_file.as_posix()}"
        engine = create_async_engine(test_url, echo=False)
        await init_db(engine)

        # 3. Verify 'metadata' column was safely added
        con_check = sqlite3.connect(legacy_db_file)
        cols = [c[1] for c in con_check.execute("PRAGMA table_info(memory_items)").fetchall()]
        con_check.close()
        assert "metadata" in cols, "metadata column must be added by init_db"

        # 4. Verify existing record can be queried via MemoryRepository without error
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

        @asynccontextmanager
        async def session_provider():
            async with session_factory() as sess:
                yield sess
                await sess.commit()

        mem_repo = MemoryRepository(session_provider=session_provider)
        mem = await mem_repo.get_memory("legacy-uuid-1")
        assert mem is not None
        assert mem.content == "Legacy memory record without metadata column"
        assert mem.metadata_ == {}

        await engine.dispose()

        # 5. Test atomic hot backup & restore
        monkeypatch.setattr("nemo.database.connection.resolve_database_url", lambda: test_url)
        backup_file = Path(tmpdir) / "backup_archive.db"
        saved_backup = backup_database(destination=backup_file)
        assert saved_backup.exists()

        # Modify original database
        con_modify = sqlite3.connect(legacy_db_file)
        con_modify.execute("DELETE FROM memory_items")
        con_modify.commit()
        con_modify.close()

        # Restore from backup
        restored_file = restore_database(source=backup_file)
        assert restored_file == legacy_db_file

        con_restored = sqlite3.connect(legacy_db_file)
        count = con_restored.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
        con_restored.close()
        assert count == 1, "Backup restoration must restore all data intact"


@pytest.mark.asyncio
async def test_automated_memory_extraction():
    """Verify that MemoryExtractor parses LLM extraction and persists deduplicated memories."""
    async with create_test_db() as db:
        mem_repo: MemoryRepository = db["mem_repo"]

        class MockNimProvider:
            async def generate(self, messages, **kwargs):
                from nemo.ai.schemas import LLMResponse
                content = json.dumps([
                    {"content": "Frontend is built with React 19 and Tailwind", "type": "decision", "importance": 1.0, "subject": "frontend"},
                    {"content": "Dev server default port is 5173", "type": "fact", "importance": 0.9, "subject": "networking"},
                ])
                return LLMResponse(content=content, model="nemotron-mock")

        from nemo.memory.extractor import MemoryExtractor
        extractor = MemoryExtractor(provider=MockNimProvider(), repository=mem_repo)

        # 1. First run: extracts and persists 2 memories
        new_mems = await extractor.extract_and_persist(
            objective="Setup React frontend",
            observations=[{"tool": "scaffold_project", "success": True}],
            outcome="React app scaffolded successfully on port 5173",
        )
        assert len(new_mems) == 2
        assert new_mems[0].metadata_.get("auto_extracted") is True

        # 2. Second run with same facts: deduplication must prevent re-inserting identical memories
        duplicate_run = await extractor.extract_and_persist(
            objective="Inspect React frontend",
            observations=[{"tool": "inspect_project_environment", "success": True}],
            outcome="Frontend is built with React 19 and Tailwind",
        )
        assert len(duplicate_run) == 0

        # 3. Total memories in repo remains 2
        all_stored = await mem_repo.list_memories()
        assert len(all_stored) == 2


# 6. Public exports
__all__ = [
    "create_test_db",
    "test_project_lifecycle_and_idempotency",
    "test_memory_scoping_and_cross_project_isolation",
    "test_memory_superseding_and_conflict_resolution",
    "test_multi_keyword_search_and_importance_ranking",
    "test_concurrent_memory_writes",
    "test_edge_cases_and_sanitization",
    "test_database_schema_evolution_and_backup_restore",
    "test_automated_memory_extraction",
]
