"""Data models for terminal session management."""

# 1. Standard library imports
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
import uuid

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.common.types import CommandResult

# 4. Types, Protocols, Schemas
class SessionStatus(str, Enum):
    """Lifecycle status of a terminal session."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class SessionInfo(BaseModel):
    """Metadata and runtime state for a managed terminal session."""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    shell: str = "powershell"
    cwd: str = Field(default_factory=lambda: str(Path.cwd()))
    pid: int | None = None
    status: SessionStatus = SessionStatus.IDLE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recent_output: list[str] = Field(default_factory=list)
    history: list[CommandResult] = Field(default_factory=list)

    def append_output(self, line: str, max_lines: int = 500) -> None:
        """Append line to output ring buffer."""
        self.recent_output.append(line)
        if len(self.recent_output) > max_lines:
            self.recent_output.pop(0)
        self.last_activity = datetime.now(timezone.utc)

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["SessionStatus", "SessionInfo"]
