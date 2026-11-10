"""Memory and project repository for durable entity persistence."""

# 1. Standard library imports
from pathlib import Path

# 2. Third-party imports
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# 3. Local / internal imports
from nemo.database.connection import get_db_session, init_db
from nemo.database.models import MemoryItem, Project

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class MemoryRepository:
    """CRUD and query operations for long-term memory items."""

    def __init__(self, session_provider=get_db_session) -> None:
        self.session_provider = session_provider

    async def add_memory(
        self,
        content: str,
        scope: str = "project",
        project_id: str | None = None,
        memory_type: str = "fact",
        subject: str | None = None,
        predicate: str | None = None,
        obj: str | None = None,
        importance: float = 1.0,
    ) -> MemoryItem:
        """Persist a new memory fact or decision."""
        item = MemoryItem(
            content=content,
            scope=scope,
            project_id=project_id,
            type=memory_type,
            subject=subject,
            predicate=predicate,
            object=obj,
            importance=importance,
            status="active",
        )
        async with self.session_provider() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def search_memories(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search active memories by keyword query in content or subject."""
        tokens = query.lower().split()
        if not tokens:
            return []

        async with self.session_provider() as session:
            stmt = select(MemoryItem).where(MemoryItem.status == "active")
            if project_id:
                # Include both project-specific memories and global memories
                stmt = stmt.where(
                    or_(
                        MemoryItem.project_id == project_id,
                        MemoryItem.scope == "global",
                    )
                )

            # Match any token in content or subject
            conditions = [
                or_(
                    MemoryItem.content.ilike(f"%{token}%"),
                    MemoryItem.subject.ilike(f"%{token}%"),
                )
                for token in tokens
            ]
            stmt = stmt.where(or_(*conditions)).order_by(
                MemoryItem.importance.desc(),
                MemoryItem.created_at.desc(),
            ).limit(limit)

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_memories(
        self,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """List active memories."""
        async with self.session_provider() as session:
            stmt = select(MemoryItem).where(MemoryItem.status == "active")
            if project_id:
                stmt = stmt.where(
                    or_(
                        MemoryItem.project_id == project_id,
                        MemoryItem.scope == "global",
                    )
                )
            stmt = stmt.order_by(MemoryItem.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_memory(self, memory_id: str) -> bool:
        """Mark memory as archived/deleted."""
        async with self.session_provider() as session:
            stmt = select(MemoryItem).where(MemoryItem.id == memory_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                return False
            item.status = "archived"
            await session.commit()
            return True


class ProjectRepository:
    """Registration and lookup for local codebases."""

    def __init__(self, session_provider=get_db_session) -> None:
        self.session_provider = session_provider

    async def register_project(self, name: str, root_path: Path | str) -> Project:
        """Register or retrieve an existing project workspace."""
        canonical_path = str(Path(root_path).resolve())
        async with self.session_provider() as session:
            stmt = select(Project).where(Project.root_path == canonical_path)
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return existing

            project = Project(name=name, root_path=canonical_path, status="active")
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project

    async def list_projects(self) -> list[Project]:
        """List all registered projects."""
        async with self.session_provider() as session:
            stmt = select(Project).where(Project.status == "active").order_by(Project.name.asc())
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_by_path(self, path: Path | str) -> Project | None:
        """Find project by filesystem path."""
        canonical_path = str(Path(path).resolve())
        async with self.session_provider() as session:
            stmt = select(Project).where(Project.root_path == canonical_path)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

# 6. Public exports
__all__ = ["MemoryRepository", "ProjectRepository"]

