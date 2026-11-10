"""Self-check verification test for Phase 8 agent tools and Phase 9 diagnosis."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import tempfile

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.agent.orchestrator import extract_json_block
from nemo.common.types import RiskLevel
from nemo.security.policy import SecurityPolicy
from nemo.tools.builtin import ReadFileTool, TerminalTool, WriteFileTool
from nemo.tools.registry import ToolRegistry

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_security_policy_and_boundaries():
    """Verify risk assessment and workspace path traversal containment."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        policy = SecurityPolicy(workspace_root=root)

        # Safe within workspace
        assert policy.is_path_safe(root / "src" / "test.py")

        # Unsafe traversal outside workspace
        assert not policy.is_path_safe(root.parent / "sensitive.txt")

        # Command risk evaluation
        assert policy.assess_command_risk("git status") == RiskLevel.L0
        assert policy.assess_command_risk("pytest") == RiskLevel.L1
        assert policy.assess_command_risk("npm install express") == RiskLevel.L2
        assert policy.assess_command_risk("rmdir /s /q C:\\Windows") == RiskLevel.L3


async def async_test_tool_execution():
    """Verify tool execution via ToolRegistry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        policy = SecurityPolicy(workspace_root=root)
        registry = ToolRegistry(policy=policy)

        # 1. Write file tool
        write_res = await registry.execute(
            name="write_file",
            arguments={"path": "demo.txt", "content": "NEMO AGENT OK"},
            context={"working_directory": str(root)},
        )
        assert write_res.success
        assert (root / "demo.txt").exists()

        # 2. Read file tool
        read_res = await registry.execute(
            name="read_file",
            arguments={"path": "demo.txt"},
            context={"working_directory": str(root)},
        )
        assert read_res.success
        assert read_res.data["content"] == "NEMO AGENT OK"

        # 3. Security blocked action outside workspace
        blocked_res = await registry.execute(
            name="write_file",
            arguments={"path": "../../escaped.txt", "content": "bad"},
            context={"working_directory": str(root)},
        )
        assert not blocked_res.success
        assert "Blocked" in (blocked_res.error or "") or "denied" in (blocked_res.error or "")

        # 4. Terminal tool execution
        term_res = await registry.execute(
            name="terminal_execute",
            arguments={"command": "Write-Output 'TOOL_OK'"},
            context={"working_directory": str(root)},
        )
        assert term_res.success
        assert "TOOL_OK" in term_res.data["stdout"]


def test_json_block_extraction():
    """Verify robust extraction of agent action JSON."""
    markdown_wrapped = "Thought: I should check directory.\n```json\n{\"action\": \"tool_call\", \"tool\": \"list_directory\", \"arguments\": {}}\n```"
    data = extract_json_block(markdown_wrapped)
    assert data is not None
    assert data["action"] == "tool_call"
    assert data["tool"] == "list_directory"

    raw_json = '{"action": "finish", "answer": "Done."}'
    data2 = extract_json_block(raw_json)
    assert data2 is not None
    assert data2["action"] == "finish"
    assert data2["answer"] == "Done."


def main():
    print("Running Phase 8 & 9 agent tools and diagnosis verification...")
    test_security_policy_and_boundaries()
    print("✓ Security policy and boundary checks passed!")
    asyncio.run(async_test_tool_execution())
    print("✓ Tool registry execution and security sandbox checks passed!")
    test_json_block_extraction()
    print("✓ Agent JSON block extraction checks passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = ["test_security_policy_and_boundaries", "async_test_tool_execution", "test_json_block_extraction"]
