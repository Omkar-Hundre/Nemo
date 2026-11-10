"""Comprehensive test suite for deep deliberation, reflection, and ground-truth verification."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.agent.orchestrator import AgentOrchestrator
from nemo.agent.verifier import OutcomeVerifier, VerificationResult
from nemo.ai.schemas import LLMResponse
from nemo.common.types import ToolResult
from nemo.intelligence.packages import PackageManagerDetector
from nemo.tools.registry import ToolRegistry

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_deliberation_tracking_in_orchestrator():
    """Verify that structured thoughts and hypotheses are captured in deliberation history."""
    provider_mock = MagicMock()
    # Step 1: Deliberation with tool call; Step 2: Deliberation with finish
    provider_mock.generate = AsyncMock(side_effect=[
        LLMResponse(
            content='```json\n{\n  "thought": "Need to check codebase summary",\n  "hypothesis": "Summary provides architecture overview",\n  "action": "tool_call",\n  "tool": "get_codebase_summary",\n  "arguments": {}\n}\n```',
            model="test-model",
        ),
        LLMResponse(
            content='```json\n{\n  "thought": "Architecture is understood and verified",\n  "action": "finish",\n  "answer": "Complete codebase analysis verified."\n}\n```',
            model="test-model",
        ),
    ])

    tools_mock = MagicMock(spec=ToolRegistry)
    tools_mock.get_definitions.return_value = []
    tools_mock.get_tool.return_value = MagicMock()
    tools_mock.execute = AsyncMock(return_value=ToolResult(success=True, data={"summary": "NEMO core"}))

    memory_mock = MagicMock()
    memory_mock.search_memories = AsyncMock(return_value=[])

    orchestrator = AgentOrchestrator(
        provider=provider_mock,
        tool_registry=tools_mock,
        memory_repo=memory_mock,
    )

    state = await orchestrator.run(objective="Understand project architecture", max_iterations=5)

    assert state.completed
    assert len(state.deliberation_history) >= 1
    assert state.deliberation_history[0]["thought"] == "Need to check codebase summary"
    assert state.deliberation_history[0]["hypothesis"] == "Summary provides architecture overview"
    assert "Complete codebase analysis verified" in (state.final_answer or "")


@pytest.mark.asyncio
async def test_reflection_on_tool_failure():
    """Verify that a tool failure triggers a reflection prompt in the next observation."""
    provider_mock = MagicMock()
    captured_messages = []

    async def mock_generate(messages, **kwargs):
        captured_messages.extend(messages)
        if len(captured_messages) < 4:
            return LLMResponse(
                content='```json\n{"action": "tool_call", "tool": "search_code", "arguments": {"query": "fail"}}\n```',
                model="test-model",
            )
        return LLMResponse(
            content='```json\n{"action": "finish", "answer": "Recovered after reflection."}\n```',
            model="test-model",
        )

    provider_mock.generate = AsyncMock(side_effect=mock_generate)

    tools_mock = MagicMock(spec=ToolRegistry)
    tools_mock.get_definitions.return_value = []
    tools_mock.get_tool.return_value = MagicMock()
    # First execution fails
    tools_mock.execute = AsyncMock(return_value=ToolResult(success=False, error="IndexNotFoundException"))

    memory_mock = MagicMock()
    memory_mock.search_memories = AsyncMock(return_value=[])

    orchestrator = AgentOrchestrator(
        provider=provider_mock,
        tool_registry=tools_mock,
        memory_repo=memory_mock,
    )

    state = await orchestrator.run(objective="Find symbol with failing tool", max_iterations=3)

    assert state.completed
    # Verify observation contained reflection requirement
    reflection_found = any(
        "reflection_required" in m.content for m in captured_messages if m.role == "user"
    )
    assert reflection_found


@pytest.mark.asyncio
async def test_verification_gate_blocks_invalid_syntax():
    """Verify that OutcomeVerifier rejects invalid Python syntax and prevents finish."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        bad_file = tmp_root / "broken.py"
        bad_file.write_text("def invalid_syntax( broken", encoding="utf-8")

        verifier = OutcomeVerifier(workspace_root=tmp_root)
        result = await verifier.verify_file_created_or_modified("broken.py")

        assert not result.verified
        assert result.ground_truth_source == "ast_syntax"
        assert "SyntaxError" in result.details


@pytest.mark.asyncio
async def test_verification_gate_enforced_by_orchestrator():
    """Verify orchestrator rejects finish action when modified file fails verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)

        verifier_mock = MagicMock(spec=OutcomeVerifier)
        # Mock file verification failure on first check, success on second
        verifier_mock.verify_file_created_or_modified = AsyncMock(side_effect=[
            VerificationResult(verified=False, ground_truth_source="ast_syntax", details="SyntaxError on line 1"),
            VerificationResult(verified=True, ground_truth_source="filesystem", details="Verified valid"),
        ])
        verifier_mock.verify_test_suite_passes = AsyncMock(
            return_value=VerificationResult(verified=True, ground_truth_source="test_suite", details="OK")
        )

        provider_mock = MagicMock()
        provider_mock.generate = AsyncMock(side_effect=[
            # 1. Agent modifies file
            LLMResponse(
                content='```json\n{"action": "tool_call", "tool": "write_file", "arguments": {"path": "module.py", "content": "..."}}\n```',
                model="test-model",
            ),
            # 2. Agent tries to finish prematurely
            LLMResponse(
                content='```json\n{"action": "finish", "answer": "Done prematurely."}\n```',
                model="test-model",
            ),
            # 3. After rejection, agent finishes legitimately
            LLMResponse(
                content='```json\n{"action": "finish", "answer": "Fixed and completed."}\n```',
                model="test-model",
            ),
        ])

        tools_mock = MagicMock(spec=ToolRegistry)
        tools_mock.get_definitions.return_value = []
        tools_mock.get_tool.return_value = MagicMock()
        tools_mock.execute = AsyncMock(return_value=ToolResult(success=True, data={"bytes_written": 10}))

        memory_mock = MagicMock()
        memory_mock.search_memories = AsyncMock(return_value=[])

        orchestrator = AgentOrchestrator(
            provider=provider_mock,
            tool_registry=tools_mock,
            memory_repo=memory_mock,
            verifier=verifier_mock,
        )

        state = await orchestrator.run(objective="Refactor module", working_directory=tmp_root, max_iterations=5)

        assert state.completed
        assert state.verified
        assert "Fixed and completed" in (state.final_answer or "")
        assert len(state.verification_results) >= 2


def test_package_manager_detector_current_project():
    """Verify package manager detector discovers Python ecosystem in NEMO codebase."""
    ecosystems = PackageManagerDetector.detect(Path.cwd())
    assert len(ecosystems) >= 1
    py_eco = next(e for e in ecosystems if e.ecosystem == "python")
    assert py_eco.manifest_file == "pyproject.toml"
    assert "pytest" in py_eco.validate_command


# 6. Public exports
__all__ = [
    "test_deliberation_tracking_in_orchestrator",
    "test_reflection_on_tool_failure",
    "test_verification_gate_blocks_invalid_syntax",
    "test_verification_gate_enforced_by_orchestrator",
    "test_package_manager_detector_current_project",
]
