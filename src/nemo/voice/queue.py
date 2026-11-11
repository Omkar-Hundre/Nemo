"""Idempotent priority task queue and concurrent execution manager for Nemo."""

# 1. Standard library imports
import asyncio
from dataclasses import dataclass, field
import hashlib
import logging
import threading
import time
from typing import Any, Callable
import uuid

# 2. Third-party imports
# (None)

# 3. Local imports
from nemo.agent.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class NemoTask:
    id: str
    name: str
    status: str = "queued"  # queued, running, completed, cancelled, failed
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "result": self.result,
        }


class IdempotentTaskQueue:
    """Manages concurrent task queues, semantic deduplication, and priority tiers."""

    DEBOUNCE_WINDOW_SEC = 15.0

    def __init__(
        self,
        on_state_change: Callable[[str, str], Any] | None = None,
        on_tasks_updated: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> None:
        self.on_state_change = on_state_change
        self.on_tasks_updated = on_tasks_updated

        self.tasks: list[NemoTask] = []
        self._recent_commands: dict[str, float] = {}
        self._current_task: NemoTask | None = None
        self._current_future: asyncio.Task | None = None
        self._queue: asyncio.Queue[NemoTask] = asyncio.Queue()
        self._lock = threading.Lock()
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def start_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start background queue processing consumer."""
        self._loop = loop
        self._running = True
        loop.create_task(self._process_queue_loop())

    def stop_worker(self) -> None:
        """Stop background worker."""
        self._running = False
        self.cancel_all()

    def submit_command(self, raw_cmd: str) -> NemoTask | None:
        """Submit command with semantic deduplication and priority tier routing."""
        cmd = raw_cmd.strip()
        if not cmd:
            return None

        # Check Tier 1: Stop / Cancel keywords
        normalized = cmd.lower()
        if normalized in ("stop", "cancel", "abort", "kill", "stop all", "cancel task"):
            self.cancel_all()
            if self.on_state_change:
                self.on_state_change("sleeping", "Tasks Cancelled")
            return None

        # Check Tier 2: Status check
        if normalized in ("status", "what are you doing", "what is running", "show processes"):
            if self.on_state_change:
                msg = f"Running: {self._current_task.name}" if self._current_task else "All tasks idle"
                self.on_state_change("sleeping", msg)
            return None

        # Tier 3: Idempotency Debounce
        cmd_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            last_seen = self._recent_commands.get(cmd_hash, 0.0)
            if (now - last_seen) < self.DEBOUNCE_WINDOW_SEC:
                logger.info("Ignoring duplicate command within debounce window: '%s'", cmd)
                return None
            self._recent_commands[cmd_hash] = now

        task = NemoTask(id=uuid.uuid4().hex[:8], name=cmd, status="queued")
        with self._lock:
            self.tasks.append(task)

        self._notify_tasks()

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._queue.put(task), self._loop)

        return task

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a specific task by ID."""
        with self._lock:
            for task in self.tasks:
                if task.id == task_id:
                    task.status = "cancelled"
                    if self._current_task and self._current_task.id == task_id and self._current_future:
                        self._current_future.cancel()
                    self._notify_tasks()
                    return True
        return False

    def cancel_all(self) -> None:
        """Cancel all running and queued tasks."""
        with self._lock:
            if self._current_task and self._current_task.status == "running":
                self._current_task.status = "cancelled"
                if self._current_future:
                    self._current_future.cancel()
            for task in self.tasks:
                if task.status == "queued":
                    task.status = "cancelled"
        self._notify_tasks()

    async def _process_queue_loop(self) -> None:
        """Continuously pulls tasks from queue and executes via AgentOrchestrator."""
        while self._running:
            try:
                task = await self._queue.get()
                if task.status == "cancelled":
                    self._queue.task_done()
                    continue

                task.status = "running"
                self._current_task = task
                self._notify_tasks()

                if self.on_state_change:
                    display_title = task.name if len(task.name) <= 24 else task.name[:21] + "..."
                    self.on_state_change("working", f"Executing: {display_title}")

                # Execute task via AgentOrchestrator
                orchestrator = AgentOrchestrator()
                self._current_future = asyncio.current_task()

                try:
                    state = await orchestrator.run(objective=task.name)
                    task.status = "completed"
                    task.result = state.final_answer or "Success"
                    task.completed_at = time.time()
                    if self.on_state_change:
                        self.on_state_change("sleeping", "Task Complete ✓")
                except asyncio.CancelledError:
                    task.status = "cancelled"
                    if self.on_state_change:
                        self.on_state_change("sleeping", "Task Cancelled")
                except Exception as e:
                    task.status = "failed"
                    task.result = str(e)
                    if self.on_state_change:
                        self.on_state_change("sleeping", f"Error: {e}")
                finally:
                    self._current_task = None
                    self._current_future = None
                    self._notify_tasks()
                    self._queue.task_done()

            except Exception as e:
                logger.error("Error in task queue runner: %s", e)
                await asyncio.sleep(0.5)

    def _notify_tasks(self) -> None:
        """Broadcast updated task list to UI."""
        if self.on_tasks_updated:
            # Send latest 15 tasks
            recent = [t.to_dict() for t in self.tasks[-15:]]
            self.on_tasks_updated(recent)

