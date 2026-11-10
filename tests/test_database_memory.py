"""Self-check verification test for Phase 4 database and memory repository."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import tempfile

# 2. Third-party imports
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# 3. Local / internal imports
from nemo.database.models import Base
from nemo.memory.repository import MemoryRepository, ProjectRepository

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
async def async_test_database_and_memory():
    """Verify database schema creation and memory/project repository operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_nemo.db"
        test_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        engine = create_async_engine(test_url, echo=False)

        # Initialize schema
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def test_session():
            async with session_factory() as sess:
                yield sess
                await sess.commit()

        proj_repo = ProjectRepository(session_provider=test_session)
        mem_repo = MemoryRepository(session_provider=test_session)

        # 1. Register project
        proj = await proj_repo.register_project(name="COSEM", root_path=Path(tmpdir) / "COSEM")
        assert proj.id is not None
        assert proj.name == "COSEM"

        found_proj = await proj_repo.get_by_path(Path(tmpdir) / "COSEM")
        assert found_proj is not None
        assert found_proj.id == proj.id

        # 2. Add memories
        m1 = await mem_repo.add_memory(
            content="Project uses PostgreSQL for persistent data.",
            scope="project",
            project_id=proj.id,
            memory_type="decision",
            subject="database",
        )
        assert m1.id is not None

        m2 = await mem_repo.add_memory(
            content="Developer prefers PowerShell on Windows.",
            scope="global",
            memory_type="preference",
            subject="shell",
        )
        assert m2.id is not None

        # 3. Search memories
        results = await mem_repo.search_memories("PostgreSQL", project_id=proj.id)
        assert len(results) == 1
        assert "PostgreSQL" in results[0].content

        results_global = await mem_repo.search_memories("PowerShell", project_id=proj.id)
        assert len(results_global) == 1
        assert "PowerShell" in results_global[0].content

        # 4. Delete/archive memory
        deleted = await mem_repo.delete_memory(m1.id)
        assert deleted
        active = await mem_repo.list_memories(project_id=proj.id)
        assert m1.id not in [item.id for item in active]

        await engine.dispose()


def main():
    print("Running Phase 4 database and memory verification...")
    asyncio.run(async_test_database_and_memory())
    print("✓ Phase 4 database and memory repository checks passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = ["async_test_database_and_memory"]
