"""Common data types and schemas across NEMO."""

# 1. Standard library imports
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

# 2. Third-party imports
# (None)

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class RiskLevel(str, Enum):
    """Authorization and safety risk classification."""
    L0 = "L0"  # Read-only, inspection, harmless
    L1 = "L1"  # Routine builds, tests, trusted project operations
    L2 = "L2"  # Source code changes, config updates
    L3 = "L3"  # Destructive actions, system-level or admin operations


class CommandResult(BaseModel):
    """Execution result for a shell command."""
    command: str
    shell: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    timed_out: bool = False

    @property
    def is_success(self) -> bool:
        """True if process exited with 0 and did not time out."""
        return self.exit_code == 0 and not self.timed_out


class ToolResult(BaseModel):
    """Standardized result returned by any agent tool."""
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["RiskLevel", "CommandResult", "ToolResult"]
