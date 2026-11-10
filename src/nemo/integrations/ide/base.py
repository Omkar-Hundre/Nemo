"""IDE adapter protocol definition."""

# 1. Standard library imports
from pathlib import Path
from typing import Protocol

# 2. Third-party imports
# (None)

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class IDEAdapter(Protocol):
    """Protocol for interacting with external code editors."""
    name: str

    async def detect(self) -> bool:
        """Check if IDE is installed on machine."""
        ...

    async def get_executable_path(self) -> Path | None:
        """Return resolved path to IDE executable if found."""
        ...

    async def open_project(self, path: Path | str) -> bool:
        """Launch IDE with target project workspace."""
        ...

    async def open_file(self, path: Path | str, line: int | None = None) -> bool:
        """Open specific file in IDE, optionally navigating to line."""
        ...

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["IDEAdapter"]
