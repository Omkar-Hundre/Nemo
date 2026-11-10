"""Terminal session manager for coordinating persistent and background processes."""

# 1. Standard library imports
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.common.types import CommandResult
from nemo.execution.sessions.models import SessionInfo, SessionStatus
from nemo.execution.shells.native import resolve_shell_executable

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class SessionManager:
    """Coordinates lifecycle, execution, and output buffering of terminal sessions."""

    def __init__(self, state_file: Path | None = None) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._active_subprocesses: dict[str, asyncio.subprocess.Process] = {}
        self._state_file = state_file or (Path.home() / ".nemo" / "sessions.json")
        self._load_state()

    def _load_state(self) -> None:
        """Load session metadata from disk if available."""
        if not self._state_file.exists():
            return
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            for sid, data in raw.items():
                info = SessionInfo.model_validate(data)
                # Verify if recorded PID is still alive on Windows
                if info.status == SessionStatus.RUNNING and info.pid:
                    if not self._is_pid_alive(info.pid):
                        info.status = SessionStatus.TERMINATED
                        info.pid = None
                self._sessions[sid] = info
        except Exception:
            self._sessions.clear()

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if process ID is actively running."""
        try:
            # On Windows, OpenProcess via ctypes or tasklist check
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in check.stdout
        except Exception:
            return False

    def _persist_state(self) -> None:
        """Persist session metadata to disk."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            serializable = {
                sid: json.loads(info.model_dump_json())
                for sid, info in self._sessions.items()
            }
            self._state_file.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        except Exception:
            pass

    def create_session(
        self,
        shell: str = "powershell",
        cwd: Path | None = None,
    ) -> SessionInfo:
        """Create and register a new session."""
        target_cwd = cwd or Path.cwd()
        session = SessionInfo(
            shell=shell,
            cwd=str(target_cwd),
            status=SessionStatus.IDLE,
        )
        self._sessions[session.session_id] = session
        self._persist_state()
        return session

    def get_session(self, session_id: str) -> SessionInfo | None:
        """Retrieve session info by id."""
        session = self._sessions.get(session_id)
        if session and session.status == SessionStatus.RUNNING and session.pid:
            if not self._is_pid_alive(session.pid):
                session.status = SessionStatus.COMPLETED
                session.pid = None
                self._persist_state()
        return session

    def list_sessions(self) -> list[SessionInfo]:
        """Return list of all registered sessions with refreshed process status."""
        for s in self._sessions.values():
            if s.status == SessionStatus.RUNNING and s.pid:
                if not self._is_pid_alive(s.pid):
                    s.status = SessionStatus.COMPLETED
                    s.pid = None
        self._persist_state()
        return list(self._sessions.values())

    async def execute(
        self,
        session_id: str,
        command: str,
        timeout_seconds: float = 600.0,
    ) -> CommandResult:
        """Run command synchronously inside session context, capturing output."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found.")

        session.status = SessionStatus.RUNNING
        session.last_activity = datetime.now(timezone.utc)
        self._persist_state()

        prefix = resolve_shell_executable(session.shell)
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
                cwd=session.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            session.pid = proc.pid
            self._active_subprocesses[session_id] = proc
            self._persist_state()

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode if proc.returncode is not None else -1

            session.status = SessionStatus.COMPLETED if exit_code == 0 else SessionStatus.FAILED

        except asyncio.TimeoutError:
            timed_out = True
            await self.terminate(session_id)
            stderr_text = f"Command timed out after {timeout_seconds}s."
            exit_code = 124
            session.status = SessionStatus.FAILED

        except Exception as exc:
            stderr_text = f"Execution error: {exc}"
            exit_code = 1
            session.status = SessionStatus.FAILED

        finally:
            self._active_subprocesses.pop(session_id, None)
            session.pid = None

        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        res = CommandResult(
            command=command,
            shell=session.shell,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

        session.history.append(res)
        for line in stdout_text.splitlines():
            session.append_output(line)
        if stderr_text:
            for line in stderr_text.splitlines():
                session.append_output(f"[ERR] {line}")

        self._persist_state()
        return res

    def launch_background(
        self,
        session_id: str,
        command: str,
        log_path: Path | str | None = None,
    ) -> SessionInfo:
        """Spawn independent process on Windows detached from caller event loop."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found.")

        prefix = resolve_shell_executable(session.shell)
        cmd_args = [*prefix, command]

        # Use CREATE_NEW_PROCESS_GROUP on Windows to prevent signals bubbling to caller
        flags = subprocess.CREATE_NEW_PROCESS_GROUP

        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL
        if log_path:
            target_log = Path(log_path)
            if not target_log.is_absolute():
                target_log = Path(session.cwd) / target_log
            target_log.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(target_log, "a", encoding="utf-8", buffering=1)
            stdout_target = log_file
            stderr_target = log_file
            session.append_output(f"[LOG] Redirecting output to: {target_log}")

        proc = subprocess.Popen(
            cmd_args,
            cwd=session.cwd,
            stdout=stdout_target,
            stderr=stderr_target,
            creationflags=flags,
        )

        session.pid = proc.pid
        session.status = SessionStatus.RUNNING
        session.last_activity = datetime.now(timezone.utc)
        session.append_output(f"[BG] Started command (PID {proc.pid}): {command}")
        self._persist_state()
        return session

    async def terminate(self, session_id: str) -> bool:
        """Kill active process tree for session."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        proc = self._active_subprocesses.get(session_id)
        pid = proc.pid if proc else session.pid

        if pid:
            kill_cmd = shutil.which("taskkill.exe") or "taskkill"
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    kill_cmd, "/F", "/T", "/PID", str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proc.wait()
            except Exception:
                if proc:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

        self._active_subprocesses.pop(session_id, None)
        session.pid = None
        session.status = SessionStatus.TERMINATED
        session.last_activity = datetime.now(timezone.utc)
        self._persist_state()
        return True

# 6. Public exports
__all__ = ["SessionManager"]
