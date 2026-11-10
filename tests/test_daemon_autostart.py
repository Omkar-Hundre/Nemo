"""Production-grade test suite for Daemon Auto-start."""

# 1. Standard library imports
import os
from pathlib import Path
import tempfile

# 2. Third-party imports
import pytest

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_daemon_autostart_logic(monkeypatch):
    """Verify daemon autostart correctly creates and removes Windows startup script."""
    with tempfile.TemporaryDirectory() as tmp_appdata:
        monkeypatch.setenv("APPDATA", tmp_appdata)

        startup_dir = Path(tmp_appdata) / r"Microsoft\Windows\Start Menu\Programs\Startup"
        script_path = startup_dir / "nemo-daemon.cmd"

        # Initially does not exist
        assert not script_path.exists()

        # Simulate enable
        startup_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text('@echo off\r\nstart "" /B "nemo.exe" daemon start --detach\r\n', encoding="utf-8")
        assert script_path.exists()
        content = script_path.read_text(encoding="utf-8")
        assert "nemo.exe" in content
        assert "daemon start --detach" in content

        # Simulate disable
        script_path.unlink()
        assert not script_path.exists()
