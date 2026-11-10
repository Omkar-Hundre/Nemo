"""Self-check verification test for Phase 3 terminal sessions."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import tempfile
import time

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.execution.sessions.manager import SessionManager
from nemo.execution.sessions.models import SessionStatus

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_session_lifecycle():
    """Verify session creation, execution, buffer recording, and termination."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "sessions.json"
        mgr = SessionManager(state_file=state_file)

        # 1. Create session
        sess = mgr.create_session(shell="powershell", cwd=Path(tmpdir))
        assert sess.session_id in [s.session_id for s in mgr.list_sessions()]
        assert sess.status == SessionStatus.IDLE

        # 2. Synchronous command execution
        res = await mgr.execute(sess.session_id, "Write-Output 'SESSION_TEST_OUTPUT'")
        assert res.is_success
        assert "SESSION_TEST_OUTPUT" in res.stdout
        assert any("SESSION_TEST_OUTPUT" in line for line in sess.recent_output)
        assert sess.status == SessionStatus.COMPLETED

        # 3. Background process launch and termination
        bg_sess = mgr.create_session(shell="powershell", cwd=Path(tmpdir))
        mgr.launch_background(bg_sess.session_id, "Start-Sleep -Seconds 15")
        assert bg_sess.status == SessionStatus.RUNNING
        assert bg_sess.pid is not None

        # Verify PID is alive
        assert SessionManager._is_pid_alive(bg_sess.pid)

        # 4. Terminate session
        terminated = await mgr.terminate(bg_sess.session_id)
        assert terminated
        assert bg_sess.status == SessionStatus.TERMINATED
        assert bg_sess.pid is None


def main():
    print("Running Phase 3 terminal session verification...")
    asyncio.run(test_session_lifecycle())
    print("✓ Phase 3 terminal session lifecycle check passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = ["test_session_lifecycle"]
