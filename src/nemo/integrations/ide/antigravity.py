"""Antigravity IDE integration adapter."""

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
class AntigravityAdapter(IDEAdapter):
    """Adapter for Antigravity IDE."""
    name: str = "antigravity"

    def _find_executable(self) -> Path | None:
        """Locate Antigravity executable in PATH or standard installation directories."""
        exe = shutil.which("antigravity.cmd") or shutil.which("antigravity.exe") or shutil.which("antigravity")
        if exe:
            return Path(exe)

        # Standard Windows installation path
        default_path = Path.home() / "AppData" / "Local" / "Programs" / "Antigravity" / "Antigravity.exe"
        if default_path.exists():
            return default_path
        return None

    async def detect(self) -> bool:
        """Return True if Antigravity is installed."""
        return self._find_executable() is not None

    async def get_executable_path(self) -> Path | None:
        """Return Antigravity executable path."""
        return self._find_executable()

    async def open_project(self, path: Path | str) -> bool:
        """Launch Antigravity with target workspace."""
        exe = self._find_executable()
        if not exe:
            return False
        target = str(Path(path).resolve())
        proc = await asyncio.create_subprocess_exec(
            str(exe), target,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return proc.returncode in (None, 0)

    async def open_file(self, path: Path | str, line: int | None = None) -> bool:
        """Open specific file in Antigravity."""
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
        return proc.returncode in (None, 0)

# 6. Public exports
__all__ = ["AntigravityAdapter"]

