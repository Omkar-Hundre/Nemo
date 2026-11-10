"""Cursor AI Code Editor integration adapter."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import shutil

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.integrations.ide.base import IDEAdapter

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class CursorAdapter(IDEAdapter):
    """Adapter for Cursor AI Code Editor."""
    name: str = "cursor"

    def _find_executable(self) -> Path | None:
        """Locate cursor CLI in PATH or default Windows installation folders."""
        exe = shutil.which("cursor.cmd") or shutil.which("cursor.exe") or shutil.which("cursor")
        if exe:
            return Path(exe)

        # Standard Windows User install paths
        candidates = [
            Path.home() / "AppData" / "Local" / "Programs" / "cursor" / "resources" / "app" / "bin" / "cursor.cmd",
            Path.home() / "AppData" / "Local" / "Programs" / "cursor" / "Cursor.exe",
            Path("C:/Program Files/Cursor/Cursor.exe"),
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    async def detect(self) -> bool:
        """Return True if Cursor is discovered."""
        return self._find_executable() is not None

    async def get_executable_path(self) -> Path | None:
        """Return executable path."""
        return self._find_executable()

    async def open_project(self, path: Path | str) -> bool:
        """Open workspace folder in Cursor."""
        exe = self._find_executable()
        if not exe:
            return False
        target = str(Path(path).resolve())
        proc = await asyncio.create_subprocess_exec(
            str(exe), target,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

    async def open_file(self, path: Path | str, line: int | None = None) -> bool:
        """Open file in Cursor with optional line targeting."""
        exe = self._find_executable()
        if not exe:
            return False
        target = str(Path(path).resolve())
        args = [str(exe)]
        if line is not None:
            args.extend(["-g", f"{target}:{line}"])
        else:
            args.append(target)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

# 6. Public exports
__all__ = ["CursorAdapter"]
