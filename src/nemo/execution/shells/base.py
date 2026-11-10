"""Shell execution interface contracts."""

# 1. Standard library imports
from pathlib import Path
from typing import Protocol

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.common.types import CommandResult

# 4. Types, Protocols, Schemas
class ShellExecutor(Protocol):
    """Protocol for executing terminal commands."""

    async def execute(
        self,
        command: str,
        cwd: Path | None = None,
        timeout_seconds: float = 600.0,
    ) -> CommandResult:
        """Execute a single command and return standard CommandResult."""
        ...

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["ShellExecutor"]
