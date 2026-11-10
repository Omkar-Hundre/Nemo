"""Self-check verification test for Phase 0 foundation."""

# 1. Standard library imports
import asyncio
from pathlib import Path

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo import __version__
from nemo.config.settings import get_settings
from nemo.common.types import CommandResult
from nemo.execution.shells.native import NativeSubprocessExecutor, resolve_shell_executable

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_settings_load():
    """Verify settings load .env key correctly."""
    settings = get_settings()
    assert settings.nvidia_api_key.startswith("nvapi-"), "NVIDIA key should load from .env"
    assert settings.default_shell == "powershell"


def test_shell_resolution():
    """Verify shell prefix mapping."""
    pwsh_cmd = resolve_shell_executable("powershell")
    assert any("powershell" in c.lower() or "pwsh" in c.lower() for c in pwsh_cmd)
    cmd_cmd = resolve_shell_executable("cmd")
    assert cmd_cmd == ["cmd.exe", "/c"]


def test_native_subprocess_execution():
    """Verify synchronous and asynchronous command execution with exit code."""
    executor = NativeSubprocessExecutor(default_shell="powershell")
    result: CommandResult = asyncio.run(executor.execute("Write-Output 'NEMO_OK'"))
    assert result.is_success, f"Command failed with exit code: {result.exit_code}"
    assert "NEMO_OK" in result.stdout


if __name__ == "__main__":
    print(f"Running NEMO v{__version__} foundation checks...")
    test_settings_load()
    print("✓ Settings check passed")
    test_shell_resolution()
    print("✓ Shell resolution check passed")
    test_native_subprocess_execution()
    print("✓ Subprocess execution check passed")
    print("All foundation checks passed successfully!")

# 6. Public exports
__all__ = ["test_settings_load", "test_shell_resolution", "test_native_subprocess_execution"]
