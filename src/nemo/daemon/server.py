"""FastAPI background daemon server providing local IPC endpoints."""

# 1. Standard library imports
from pathlib import Path
from typing import Any

# 2. Third-party imports
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo import __version__
from nemo.agent.orchestrator import AgentOrchestrator
from nemo.config.settings import get_settings
from nemo.execution.sessions.manager import SessionManager
from nemo.intelligence.indexer import IndexReport, ProjectIndexer

# 4. Types, Protocols, Schemas
class CreateTaskRequest(BaseModel):
    objective: str
    working_directory: str | None = None
    max_steps: int = 8


class CreateSessionRequest(BaseModel):
    shell: str = "powershell"
    cwd: str | None = None


class ExecuteCommandRequest(BaseModel):
    session_id: str
    command: str
    timeout_seconds: float = 300.0


class IndexRequest(BaseModel):
    path: str
    force: bool = False

# 5. Core logic / classes / functions
app = FastAPI(
    title="NEMO Background Daemon",
    version=__version__,
    description="Local IPC API for persistent sessions, background tasks, and indexing.",
)

session_manager = SessionManager()


@app.get("/v1/health")
async def health_check() -> dict[str, str]:
    """Daemon health and liveness."""
    return {"status": "ok", "version": __version__}


@app.get("/v1/status")
async def system_status() -> dict[str, Any]:
    """Overall daemon and environment status."""
    settings = get_settings()
    sessions = session_manager.list_sessions()
    return {
        "version": __version__,
        "shell": settings.default_shell,
        "ide": settings.default_ide,
        "workspace_root": str(settings.workspace_root),
        "active_sessions_count": len([s for s in sessions if s.status.value == "running"]),
        "total_sessions_count": len(sessions),
    }


@app.post("/v1/tasks")
async def create_agent_task(req: CreateTaskRequest) -> dict[str, Any]:
    """Execute autonomous agent workflow inside daemon."""
    orchestrator = AgentOrchestrator()
    state = await orchestrator.run(
        objective=req.objective,
        working_directory=req.working_directory,
        max_iterations=req.max_steps,
    )
    return {
        "task_id": state.task_id,
        "completed": state.completed,
        "steps_count": len(state.tool_history),
        "final_answer": state.final_answer,
        "history": state.tool_history,
    }


@app.get("/v1/terminal/sessions")
async def list_terminal_sessions() -> list[dict[str, Any]]:
    """List all managed terminal sessions."""
    return [s.model_dump() for s in session_manager.list_sessions()]


@app.post("/v1/terminal/sessions")
async def create_terminal_session(req: CreateSessionRequest) -> dict[str, Any]:
    """Register and spawn a persistent terminal session."""
    cwd_path = Path(req.cwd) if req.cwd else Path.cwd()
    session = session_manager.create_session(shell=req.shell, cwd=cwd_path)
    return session.model_dump()


@app.post("/v1/terminal/execute")
async def execute_in_terminal(req: ExecuteCommandRequest) -> dict[str, Any]:
    """Execute command inside session and capture output."""
    try:
        res = await session_manager.execute(
            session_id=req.session_id,
            command=req.command,
            timeout_seconds=req.timeout_seconds,
        )
        return res.model_dump()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")


@app.post("/v1/index/jobs")
async def trigger_index(req: IndexRequest) -> dict[str, Any]:
    """Trigger incremental codebase indexing."""
    target = Path(req.path).resolve()
    if not target.exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {target}")

    indexer = ProjectIndexer(target)
    report: IndexReport = indexer.run_index(force=req.force)
    return report.model_dump()

# 6. Public exports
__all__ = ["app", "session_manager"]
