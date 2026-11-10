"""Visual Studio Code integration adapter."""

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
class VSCodeAdapter(IDEAdapter):
    """Adapter for Visual Studio Code."""
    name: str = "vscode"

    def _find_executable(self) -> Path | None:
        """Locate code CLI in PATH or default Windows installation folders."""
        exe = shutil.which("code.cmd") or shutil.which("code.exe") or shutil.which("code")
        if exe:
            return Path(exe)

        # Standard Windows User install path
        user_path = Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
        if user_path.exists():
            return user_path
        return None

    async def detect(self) -> bool:
        """Return True if VS Code is discovered."""
        return self._find_executable() is not None

    async def get_executable_path(self) -> Path | None:
        """Return executable path."""
        return self._find_executable()

    async def open_project(self, path: Path | str) -> bool:
        """Open workspace folder in VS Code."""
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
        """Open file in VS Code with optional line targeting."""
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
__all__ = ["VSCodeAdapter"]

