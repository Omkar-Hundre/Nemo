"""Background worker task definitions for indexing, graph synchronization, and memory maintenance."""

# 1. Standard library imports
from pathlib import Path
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.database.connection import init_db
from nemo.intelligence.graph import CodeKnowledgeGraph, ProjectGraphBuilder
from nemo.intelligence.indexer import IndexReport, ProjectIndexer
from nemo.memory.repository import MemoryRepository

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
async def task_run_indexing(workspace_path: Path | str, force: bool = False) -> IndexReport:
    """Execute background incremental indexing."""
    target = Path(workspace_path).resolve()
    indexer = ProjectIndexer(target)
    return indexer.run_index(force=force)


async def task_build_knowledge_graph(project_name: str, workspace_path: Path | str) -> CodeKnowledgeGraph:
    """Generate in-memory code graph and Cypher projection."""
    target = Path(workspace_path).resolve()
    py_files = list(target.rglob("*.py"))
    # Filter out venv / git
    clean_files = [f for f in py_files if ".venv" not in f.parts and ".git" not in f.parts]
    return ProjectGraphBuilder.build_graph(project_name=project_name, root_path=target, python_files=clean_files)


async def task_consolidate_memories(project_id: str | None = None) -> dict[str, int]:
    """Inspect and deduplicate active memories."""
    await init_db()
    repo = MemoryRepository()
    items = await repo.list_memories(project_id=project_id, limit=200)

    seen_contents = set()
    archived_count = 0

    for item in items:
        norm = item.content.strip().lower()
        if norm in seen_contents:
            await repo.delete_memory(item.id)
            archived_count += 1
        else:
            seen_contents.add(norm)

    return {"total_checked": len(items), "duplicates_archived": archived_count}

# 6. Public exports
__all__ = ["task_run_indexing", "task_build_knowledge_graph", "task_consolidate_memories"]

