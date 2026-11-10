"""Asynchronous background worker service executing queued maintenance jobs."""

# 1. Standard library imports
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.worker.tasks import (
    task_build_knowledge_graph,
    task_consolidate_memories,
    task_run_indexing,
)

# 4. Types, Protocols, Schemas
class WorkerJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str  # "indexing" | "graph_sync" | "memory_consolidation"
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"  # "queued" | "running" | "completed" | "failed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result: dict[str, Any] | None = None
    error: str | None = None


# 5. Core logic / classes / functions
class BackgroundWorker:
    """Worker service supervising background operations."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[WorkerJob] = asyncio.Queue()
        self._jobs: dict[str, WorkerJob] = {}
        self._running = False
        self._worker_task: asyncio.Task | None = None

    def enqueue(self, name: str, payload: dict[str, Any] | None = None) -> WorkerJob:
        """Enqueue a job for execution."""
        job = WorkerJob(name=name, payload=payload or {})
        self._jobs[job.job_id] = job
        self._queue.put_nowait(job)
        return job

    def get_job(self, job_id: str) -> WorkerJob | None:
        """Get job metadata and status."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[WorkerJob]:
        """List all tracked jobs."""
        return list(self._jobs.values())

    async def _execute_job(self, job: WorkerJob) -> None:
        """Dispatch job to its concrete task handler."""
        job.status = "running"
        try:
            if job.name == "indexing":
                target = job.payload.get("path", Path.cwd())
                force = job.payload.get("force", False)
                rep = await task_run_indexing(target, force=force)
                job.result = rep.model_dump()
            elif job.name == "graph_sync":
                name = job.payload.get("project_name", "DefaultProject")
                target = job.payload.get("path", Path.cwd())
                graph = await task_build_knowledge_graph(name, target)
                job.result = {"node_count": len(graph.nodes), "edge_count": len(graph.edges)}
            elif job.name == "memory_consolidation":
                proj_id = job.payload.get("project_id")
                res = await task_consolidate_memories(project_id=proj_id)
                job.result = res
            else:
                raise ValueError(f"Unknown job type: {job.name}")

            job.status = "completed"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)

    async def _run_loop(self) -> None:
        """Continuous consumer loop."""
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._execute_job(job)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def start(self) -> None:
        """Start worker consumer task."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully stop worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

# 6. Public exports
__all__ = ["WorkerJob", "BackgroundWorker"]

