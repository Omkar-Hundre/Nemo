"""Native Windows subprocess command executor."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import shutil
import time

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.common.types import CommandResult
from nemo.execution.shells.base import ShellExecutor

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def resolve_shell_executable(shell: str) -> list[str]:
    """Map logical shell name to executable command prefix."""
    s = shell.lower().strip()
    if s in ("pwsh", "powershell"):
        # Prefer modern PowerShell 7 if in PATH, fallback to Windows PowerShell
        exe = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
        return [exe, "-NoProfile", "-NonInteractive", "-Command"]
    if s == "cmd":
        return ["cmd.exe", "/c"]
    if s in ("bash", "gitbash"):
        exe = shutil.which("bash.exe") or "bash.exe"
        return [exe, "-c"]
    return [s]


class NativeSubprocessExecutor(ShellExecutor):
    """Executes commands via asyncio subprocess."""

    def __init__(self, default_shell: str = "powershell") -> None:
        self.default_shell = default_shell

    async def execute(
        self,
        command: str,
        cwd: Path | None = None,
        timeout_seconds: float = 600.0,
    ) -> CommandResult:
        """Run command in child process, collect stdout/stderr, enforce timeout."""
        prefix = resolve_shell_executable(self.default_shell)
        cmd_args = [*prefix, command]
        start_time = time.perf_counter()

        proc = None
        timed_out = False
        stdout_text = ""
        stderr_text = ""
        exit_code = -1

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode if proc.returncode is not None else -1

        except asyncio.TimeoutError:
            timed_out = True
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            stderr_text = f"Command timed out after {timeout_seconds} seconds."
            exit_code = 124

        except Exception as exc:
            stderr_text = f"Subprocess launch error: {exc}"
            exit_code = 1

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return CommandResult(
            command=command,
            shell=self.default_shell,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=round(duration_ms, 2),
            timed_out=timed_out,
        )

# 6. Public exports
__all__ = ["NativeSubprocessExecutor", "resolve_shell_executable"]

