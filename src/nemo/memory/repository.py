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
COMMON_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with",
    "is", "are", "was", "were", "and", "or", "not", "be", "this",
    "that", "it", "from", "by", "as", "into", "all", "your", "my",
    "can", "you", "we", "i", "me", "do", "does", "did", "have", "has",
    "inside", "where", "what", "how", "who", "which", "there", "then",
    "here", "some", "any", "so", "up", "out", "about",
}


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
        metadata: dict | None = None,
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
            metadata_=metadata or {},
        )
        async with self.session_provider() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def get_memory(self, memory_id: str) -> MemoryItem | None:
        """Retrieve memory item by ID."""
        async with self.session_provider() as session:
            stmt = select(MemoryItem).where(MemoryItem.id == memory_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        importance: float | None = None,
        status: str | None = None,
        metadata: dict | None = None,
    ) -> MemoryItem | None:
        """Update fields of an existing memory item."""
        async with self.session_provider() as session:
            stmt = select(MemoryItem).where(MemoryItem.id == memory_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                return None
            if content is not None:
                item.content = content
            if importance is not None:
                item.importance = importance
            if status is not None:
                item.status = status
            if metadata is not None:
                item.metadata_ = metadata
            await session.commit()
            await session.refresh(item)
            return item

    async def supersede_memory(
        self,
        old_memory_id: str,
        new_content: str,
        importance: float = 1.0,
        subject: str | None = None,
        predicate: str | None = None,
        obj: str | None = None,
    ) -> MemoryItem | None:
        """Atomically mark old memory as superseded and insert replacement memory."""
        async with self.session_provider() as session:
            stmt = select(MemoryItem).where(MemoryItem.id == old_memory_id)
            result = await session.execute(stmt)
            old_item = result.scalar_one_or_none()
            if not old_item:
                return None
            old_item.status = "superseded"

            new_item = MemoryItem(
                content=new_content,
                scope=old_item.scope,
                project_id=old_item.project_id,
                type=old_item.type,
                subject=subject or old_item.subject,
                predicate=predicate or old_item.predicate,
                object=obj or old_item.object,
                importance=importance,
                status="active",
                metadata_={"supersedes": old_memory_id},
            )
            session.add(new_item)
            await session.commit()
            await session.refresh(new_item)
            return new_item

    async def search_memories(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search active memories by significant keyword query in content or subject."""
        raw_tokens = [t.strip(".,!?:;\"'()[]{}") for t in query.lower().split()]
        tokens = [t for t in raw_tokens if len(t) >= 3 and t not in COMMON_STOPWORDS]
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

    async def get_by_id(self, project_id: str) -> Project | None:
        """Find project by unique ID."""
        async with self.session_provider() as session:
            stmt = select(Project).where(Project.id == project_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

    async def delete_project(self, project_id: str) -> bool:
        """Remove project and cascade its records without deleting directory."""
        async with self.session_provider() as session:
            stmt = select(Project).where(Project.id == project_id)
            res = await session.execute(stmt)
            proj = res.scalar_one_or_none()
            if not proj:
                return False
            await session.delete(proj)
            await session.commit()
            return True

# 6. Public exports
__all__ = ["MemoryRepository", "ProjectRepository"]

