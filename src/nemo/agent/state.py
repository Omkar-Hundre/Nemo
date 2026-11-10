"""State schema for agent task workflows."""

# 1. Standard library imports
from pathlib import Path
from typing import Any
import uuid

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class AgentState(BaseModel):
    """Runtime execution state for autonomous agent tasks."""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    objective: str
    working_directory: str = Field(default_factory=lambda: str(Path.cwd()))
    project_id: str | None = None
    iteration: int = 0
    max_iterations: int = 10
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    deliberation_history: list[dict[str, Any]] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    verified: bool = False
    completed: bool = False
    final_answer: str | None = None
    error: str | None = None

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["AgentState"]

