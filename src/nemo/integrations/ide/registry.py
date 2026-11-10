"""Registry for discovering and routing commands to IDE adapters."""

# 1. Standard library imports
from pathlib import Path

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.config.settings import get_settings
from nemo.integrations.ide.antigravity import AntigravityAdapter
from nemo.integrations.ide.base import IDEAdapter
from nemo.integrations.ide.cursor import CursorAdapter
from nemo.integrations.ide.vscode import VSCodeAdapter

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class IDERegistry:
    """Manages registered IDE adapters and default editor resolution."""

    def __init__(self) -> None:
        self._adapters: dict[str, IDEAdapter] = {
            "antigravity": AntigravityAdapter(),
            "vscode": VSCodeAdapter(),
            "cursor": CursorAdapter(),
        }

    def register(self, adapter: IDEAdapter) -> None:
        """Register a custom IDE adapter."""
        self._adapters[adapter.name.lower()] = adapter

    def get(self, name: str) -> IDEAdapter | None:
        """Retrieve adapter by name."""
        return self._adapters.get(name.lower())

    async def list_available(self) -> list[dict]:
        """Return list of supported IDEs and their current detection status."""
        results = []
        for name, adapter in self._adapters.items():
            installed = await adapter.detect()
            exe = await adapter.get_executable_path()
            results.append({
                "name": name,
                "detected": installed,
                "executable": str(exe) if exe else None,
            })
        return results

    async def resolve_adapter(self, preferred: str | None = None) -> IDEAdapter | None:
        """Resolve target adapter based on preference or system detection."""
        target_name = preferred or get_settings().default_ide
        adapter = self.get(target_name)
        if adapter and await adapter.detect():
            return adapter

        # Fallback to any detected IDE
        for ad in self._adapters.values():
            if await ad.detect():
                return ad
        return None

    async def open_project(self, path: Path | str, preferred_ide: str | None = None) -> bool:
        """Open workspace folder using resolved IDE."""
        adapter = await self.resolve_adapter(preferred_ide)
        if not adapter:
            return False
        return await adapter.open_project(path)

    async def open_file(
        self,
        path: Path | str,
        line: int | None = None,
        preferred_ide: str | None = None,
    ) -> bool:
        """Open specific file using resolved IDE."""
        adapter = await self.resolve_adapter(preferred_ide)
        if not adapter:
            return False
        return await adapter.open_file(path, line)

# 6. Public exports
__all__ = ["IDERegistry"]

