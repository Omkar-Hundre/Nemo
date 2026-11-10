"""Self-check verification test for Phase 10 daemon endpoints and Phase 11 setup wizard."""

# 1. Standard library imports
import asyncio

# 2. Third-party imports
import httpx
import pytest

# 3. Local / internal imports
from nemo.daemon.server import app as daemon_app
from nemo.cli.setup import run_setup_wizard

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_daemon_endpoints():
    """Verify local daemon REST endpoints using async ASGI transport."""
    transport = httpx.ASGITransport(app=daemon_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/v1/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # 2. Status check
        res = await client.get("/v1/status")
        assert res.status_code == 200
        assert "version" in res.json()

        # 3. Create terminal session
        res = await client.post("/v1/terminal/sessions", json={"shell": "powershell"})
        assert res.status_code == 200
        sess_data = res.json()
        sid = sess_data["session_id"]
        assert sid is not None

        # 4. Execute command in session
        res = await client.post(
            "/v1/terminal/execute",
            json={"session_id": sid, "command": "Write-Output 'DAEMON_TEST_OK'"},
        )
        assert res.status_code == 200
        exec_data = res.json()
        assert exec_data["exit_code"] == 0
        assert "DAEMON_TEST_OK" in exec_data["stdout"]

        # 5. Shutdown endpoint
        res_down = await client.post("/v1/shutdown")
        assert res_down.status_code == 200
        assert res_down.json()["status"] == "shutting_down"


@pytest.mark.asyncio
async def test_setup_wizard():
    """Verify setup wizard executes and reports status."""
    ok = await run_setup_wizard()
    assert ok, "Setup wizard should succeed with valid test environment"


def main():
    print("Running Phase 10 daemon and Phase 11 setup verification...")
    asyncio.run(test_daemon_endpoints())
    print("✓ Daemon ASGI endpoints verified!")
    asyncio.run(test_setup_wizard())
    print("✓ Setup wizard checks passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = ["test_daemon_endpoints", "test_setup_wizard"]

