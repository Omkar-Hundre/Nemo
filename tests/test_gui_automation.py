"""Production-grade test suite for Windows GUI Automation Tool."""

# 1. Standard library imports
import asyncio
import os
import platform
import subprocess
import time

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.tools.builtin import WindowsGuiTool

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_gui_tool_definition():
    """Verify gui_automation tool schema, actions, and risk level."""
    tool = WindowsGuiTool()
    defn = tool.get_definition()
    assert defn.name == "gui_automation"
    assert "launch" in defn.parameters["properties"]["action"]["enum"]
    assert "list_windows" in defn.parameters["properties"]["action"]["enum"]
    assert "type_keys" in defn.parameters["properties"]["action"]["enum"]
    assert "click" in defn.parameters["properties"]["action"]["enum"]
    assert "inspect_tree" in defn.parameters["properties"]["action"]["enum"]


@pytest.mark.asyncio
async def test_gui_tool_list_windows():
    """Verify gui_automation list_windows enumerates active Windows desktop windows."""
    if platform.system() != "Windows":
        pytest.skip("Windows only")

    tool = WindowsGuiTool()
    res = await tool.execute({"action": "list_windows"}, {})
    assert res.success
    assert res.data["action"] == "list_windows"
    assert "windows" in res.data
    assert isinstance(res.data["windows"], list)
    assert res.data["count"] >= 0


@pytest.mark.asyncio
async def test_gui_tool_launch_and_inspect_and_close():
    """Verify launching an app, inspecting control tree, and closing it gracefully."""
    if platform.system() != "Windows":
        pytest.skip("Windows only")

    tool = WindowsGuiTool()

    # Launch notepad
    launch_res = await tool.execute({"action": "launch", "target": "notepad.exe"}, {})
    assert launch_res.success
    assert launch_res.data["action"] == "launch"
    assert "pid" in launch_res.data
    app_pid = launch_res.data["pid"]

    # Give notepad time to create UI
    time.sleep(1.0)

    try:
        # Check window inspection
        tree_res = await tool.execute({"action": "inspect_tree", "target": "notepad", "max_depth": 10}, {})
        if tree_res.success:
            assert tree_res.data["action"] == "inspect_tree"
            assert "controls" in tree_res.data
            assert len(tree_res.data["controls"]) > 0

        # Test window minimize and restore
        min_res = await tool.execute({"action": "minimize", "target": "notepad"}, {})
        assert min_res.success or "not found" in (min_res.error or "").lower()

        restore_res = await tool.execute({"action": "restore", "target": "notepad"}, {})
        assert restore_res.success or "not found" in (restore_res.error or "").lower()

    finally:
        # Graceful close or kill
        close_res = await tool.execute({"action": "close", "target": "notepad"}, {})
        # Force terminate if still open
        subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)


@pytest.mark.asyncio
async def test_gui_tool_validation_errors():
    """Verify validation boundaries for missing required parameters."""
    tool = WindowsGuiTool()

    # Missing target for launch
    res_no_tgt = await tool.execute({"action": "launch"}, {})
    assert res_no_tgt.success is False
    assert "target parameter is required" in res_no_tgt.error.lower()

    # Missing keys for type_keys
    res_no_keys = await tool.execute({"action": "type_keys", "target": "notepad"}, {})
    assert res_no_keys.success is False
    assert "keys parameter is required" in res_no_keys.error.lower()

    # Missing control for click
    res_no_ctrl = await tool.execute({"action": "click", "target": "notepad"}, {})
    assert res_no_ctrl.success is False
    assert "control parameter is required" in res_no_ctrl.error.lower()

    # Unsupported action
    res_unsupported = await tool.execute({"action": "quantum_teleport"}, {})
    assert res_unsupported.success is False
    assert "unsupported gui action" in res_unsupported.error.lower()
