"""Production Remote Supabase Bridge for NEMO.

Enables bidirectional mobile phone control: Omkar can dispatch prompts,
voice dictation, and workflows from any smartphone, which Nemo executes on Windows
via AgentOrchestrator, streaming the results back to Supabase.
"""

# 1. Standard library imports
import asyncio
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

# 2. Third-party imports
# (None - strictly standard library for rock-solid zero-dep networking)

# 3. Local imports
from nemo.agent.orchestrator import AgentOrchestrator
from nemo.config.settings import get_settings

logger = logging.getLogger(__name__)


class NemoRemoteBridge:
    """Synchronizes tasks between Supabase cloud database and local Nemo execution engine."""

    def __init__(
        self,
        supabase_url: str | None = None,
        supabase_key: str | None = None,
        poll_interval: float = 1.5,
        on_task_start: Callable[[dict[str, Any]], None] | None = None,
        on_task_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        settings = get_settings()
        self.supabase_url = (supabase_url or settings.supabase_url).rstrip("/")
        self.supabase_key = supabase_key or settings.supabase_key
        self.poll_interval = max(0.5, poll_interval)
        self.on_task_start = on_task_start
        self.on_task_complete = on_task_complete
        self._stop_event = threading.Event()
        self._running = False

    def _headers(self, return_repr: bool = False) -> dict[str, str]:
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if return_repr:
            headers["Prefer"] = "return=representation"
        return headers

    def fetch_pending_tasks(self, limit: int = 1) -> list[dict[str, Any]]:
        """Fetch pending tasks ordered by creation time."""
        endpoint = f"{self.supabase_url}/rest/v1/nemo_remote_tasks"
        params = urllib.parse.urlencode({
            "status": "eq.pending",
            "order": "created_at.asc",
            "limit": str(limit),
        })
        url = f"{endpoint}?{params}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if 200 <= resp.status < 300:
                    payload = resp.read().decode("utf-8")
                    return json.loads(payload) if payload else []
        except Exception as exc:
            logger.debug("Remote bridge fetch error: %s", exc)
        return []

    def update_task_status(
        self,
        task_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> bool:
        """Update task status and result in Supabase."""
        endpoint = f"{self.supabase_url}/rest/v1/nemo_remote_tasks"
        params = urllib.parse.urlencode({"id": f"eq.{task_id}"})
        url = f"{endpoint}?{params}"

        now_iso = datetime.now(timezone.utc).isoformat()
        body_dict: dict[str, Any] = {
            "status": status,
            "updated_at": now_iso,
        }
        if result is not None:
            body_dict["result"] = result
        if error is not None:
            body_dict["error"] = error

        data = json.dumps(body_dict).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="PATCH")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.error("Failed to update task %s in Supabase: %s", task_id, exc)
            return False

    async def execute_task_async(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a single remote task asynchronously via fast-path or AgentOrchestrator."""
        import base64
        from pathlib import Path
        task_id = str(task.get("id"))
        prompt = str(task.get("prompt", "")).strip()

        if not prompt:
            self.update_task_status(task_id, status="failed", error="Empty prompt received.")
            return {"id": task_id, "status": "failed", "error": "Empty prompt."}

        logger.info("Executing remote phone task [%s]: %s", task_id, prompt)
        self.update_task_status(task_id, status="running")
        if self.on_task_start:
            self.on_task_start(task)

        # Fast path 1: Instant Screen Snapshot (0.3s, zero LLM tokens, 100% untruncated)
        prompt_lower = prompt.lower()
        if any(w in prompt_lower for w in ("snapshot", "screenshot", "screen shot", "show me my screen", "show screen")):
            from nemo.tools.builtin import capture_screen_optimized_jpeg_b64
            b64 = capture_screen_optimized_jpeg_b64()
            if b64:
                final_answer = f"Live Desktop Snapshot\n\n![Desktop Screen](data:image/jpeg;base64,{b64})"
                self.update_task_status(task_id, status="completed", result=final_answer)
                task["status"] = "completed"
                task["result"] = final_answer
                if self.on_task_complete:
                    self.on_task_complete(task)
                return task

        try:
            orchestrator = AgentOrchestrator()
            state = await orchestrator.run(objective=prompt)
            final_answer = state.final_answer or "Task completed successfully."

            # If a screenshot was captured during execution, ensure untruncated base64 image tag is attached
            snap_file = Path.home() / ".nemo" / "snapshots" / "latest.jpg"
            if snap_file.exists() and (time.time() - snap_file.stat().st_mtime) < 45.0:
                if "data:image" not in final_answer:
                    b64_data = base64.b64encode(snap_file.read_bytes()).decode("utf-8")
                    final_answer = f"{final_answer}\n\n![Desktop Screenshot](data:image/jpeg;base64,{b64_data})"

            self.update_task_status(task_id, status="completed", result=final_answer)
            task["status"] = "completed"
            task["result"] = final_answer
            if self.on_task_complete:
                self.on_task_complete(task)
            return task
        except Exception as exc:
            err_msg = str(exc)
            logger.error("Remote task execution error [%s]: %s", task_id, err_msg)
            self.update_task_status(task_id, status="failed", error=err_msg)
            task["status"] = "failed"
            task["error"] = err_msg
            if self.on_task_complete:
                self.on_task_complete(task)
            return task

    def execute_task_sync(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task in a new or existing event loop synchronously."""
        return asyncio.run(self.execute_task_async(task))

    def run_loop(self, stop_event: threading.Event | None = None) -> None:
        """Run the continuous polling loop in a worker thread."""
        stop = stop_event or self._stop_event
        self._running = True
        logger.info("Nemo Supabase Remote Bridge polling active (interval=%.1fs)...", self.poll_interval)

        while not stop.is_set():
            try:
                tasks = self.fetch_pending_tasks(limit=1)
                if tasks:
                    for task in tasks:
                        if stop.is_set():
                            break
                        self.execute_task_sync(task)
                time.sleep(self.poll_interval)
            except Exception as exc:
                logger.error("Error in remote bridge polling loop: %s", exc)
                time.sleep(self.poll_interval)
        self._running = False

    async def run_async(self, stop_event: asyncio.Event | None = None) -> None:
        """Run the continuous polling loop inside an asyncio event loop."""
        self._running = True
        logger.info("Nemo Supabase Remote Bridge async polling active (interval=%.1fs)...", self.poll_interval)

        while True:
            if stop_event and stop_event.is_set():
                break
            try:
                # Run network fetch in executor so event loop is never blocked
                tasks = await asyncio.to_thread(self.fetch_pending_tasks, 1)
                if tasks:
                    for task in tasks:
                        if stop_event and stop_event.is_set():
                            break
                        await self.execute_task_async(task)
                await asyncio.sleep(self.poll_interval)
            except Exception as exc:
                logger.error("Error in remote bridge async loop: %s", exc)
                await asyncio.sleep(self.poll_interval)
        self._running = False

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._stop_event.set()
