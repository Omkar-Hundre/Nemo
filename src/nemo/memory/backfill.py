"""Bootstrapper and backfill utility for Nemo Knowledge Graph, Developer Profile, and Historical RAG."""

# 1. Standard library imports
import asyncio
import logging
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.memory.repository import MemoryRepository, TaskRepository, UserProfileRepository

logger = logging.getLogger(__name__)


# 5. Core logic / classes / functions
class KnowledgeGraphBootstrapper:
    """Populates developer identity and baseline Knowledge Graph triplets idempotently."""

    def __init__(
        self,
        mem_repo: MemoryRepository | None = None,
        user_repo: UserProfileRepository | None = None,
        task_repo: TaskRepository | None = None,
    ) -> None:
        self.mem_repo = mem_repo or MemoryRepository()
        self.user_repo = user_repo or UserProfileRepository()
        self.task_repo = task_repo or TaskRepository()

    async def run(self) -> dict[str, Any]:
        """Bootstrap profile and knowledge graph triplets."""
        # 1. Initialize Developer Profile
        profile = await self.user_repo.get_or_create_profile(name="Omkar")

        # 2. Seed Baseline Knowledge Graph Triplets
        triplets = [
            ("Omkar", "uses_editor", "Antigravity IDE", "Developer primary editor is Antigravity IDE.", "profile", 1.0),
            ("Omkar", "prefers_browser", "Brave Browser", "Developer primary browser is Brave.", "profile", 1.0),
            ("Omkar", "prefers_music", "YouTube Music", "Productivity music streams on music.youtube.com.", "preference", 0.9),
            ("Omkar", "engineering_standard", "Ponytail Senior Dev", "Minimal code, zero AI fluff, stdlib first, 1 runnable test file.", "preference", 1.0),
            ("Nemo", "core_runtime", "Python 3.12 + UV", "Built natively on Python 3.12 with UV package manager.", "architecture", 1.0),
            ("Nemo", "implements", "Transactional Undo Journal", "LIFO atomic rollback for files and folders via ~/.nemo/journal/.", "architecture", 1.0),
            ("Nemo", "implements", "Productive Mode Orchestrator", "Automates Brave YouTube Music and Antigravity IDE launch.", "architecture", 1.0),
            ("Nemo", "implements", "Real-Time Token Streaming", "Live step cards and token-level streaming execution.", "architecture", 1.0),
            ("Nemo", "implements", "Cross-Drive File Operations", "Safe file transfers across D: and local partitions.", "architecture", 1.0),
            ("Nemo", "memory_engine", "Unified Semantic RAG & Knowledge Graph", "Dense vector search across 115+ historical tasks and decisions.", "architecture", 1.0),
        ]

        seeded_triplets = 0
        for subj, pred, obj, content, mtype, imp in triplets:
            await self.mem_repo.add_triplet(
                subject=subj,
                predicate=pred,
                obj=obj,
                content=content,
                memory_type=mtype,
                importance=imp,
                scope="global",
            )
            seeded_triplets += 1

        # 3. Ensure baseline memory item exists
        await self.mem_repo.add_triplet(
            subject="Nemo",
            predicate="backend_framework",
            obj="FastAPI",
            content="Backend framework is FastAPI and uses Python 3.12.",
            memory_type="decision",
            importance=1.0,
            scope="global",
        )

        return {
            "developer": profile.name,
            "triplets_seeded": seeded_triplets,
            "preferences": profile.preferences,
        }


# 6. Public exports
__all__ = ["KnowledgeGraphBootstrapper"]
