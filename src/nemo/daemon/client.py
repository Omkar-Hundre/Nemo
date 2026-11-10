"""Client for interacting with local NEMO daemon."""

# 1. Standard library imports
from typing import Any

# 2. Third-party imports
import httpx

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class DaemonClient:
    """HTTP client communicating with the local background daemon."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def is_running(self) -> bool:
        """Check if background daemon is actively listening."""
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                res = await client.get(f"{self.base_url}/v1/health")
                return res.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any] | None:
        """Retrieve status from daemon."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/v1/status")
                return res.json() if res.status_code == 200 else None
        except Exception:
            return None

    async def create_session(self, shell: str = "powershell", cwd: str | None = None) -> dict[str, Any] | None:
        """Request daemon to create persistent terminal session."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {"shell": shell, "cwd": cwd}
                res = await client.post(f"{self.base_url}/v1/terminal/sessions", json=payload)
                return res.json() if res.status_code == 200 else None
        except Exception:
            return None

    async def execute_command(
        self,
        session_id: str,
        command: str,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any] | None:
        """Send command to daemon for execution inside session."""
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds + 5.0) as client:
                payload = {
                    "session_id": session_id,
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                }
                res = await client.post(f"{self.base_url}/v1/terminal/execute", json=payload)
                return res.json() if res.status_code == 200 else None
        except Exception:
            return None

# 6. Public exports
__all__ = ["DaemonClient"]
