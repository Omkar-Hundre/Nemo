"""Autonomous agent workflow orchestrator with tool dispatch and budget synthesis."""

# 1. Standard library imports
import json
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.agent.state import AgentState
from nemo.agent.verifier import OutcomeVerifier
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.memory.repository import MemoryRepository
from nemo.tools.registry import ToolRegistry

# 4. Types, Protocols, Schemas
SYSTEM_PROMPT_TEMPLATE = """You are NEMO, an AI-native developer operating assistant on Windows with senior-developer rigor.
Your objective is: {objective}

Available Tools:
{tools_schema}

{memory_context}

Core Principles & Rules:
1. DELIBERATION & DEPTH: Before taking any action, clearly define your `thought` (evidence analysis) and `hypothesis` (what this step will verify or achieve).
2. ROOT CAUSE OVER SYMPTOMS: When diagnosing or fixing issues, do not patch surface errors. Trace the real call flow, inspect definitions, and resolve root causes.
3. GROUND TRUTH VERIFICATION: Never assume a file exists or syntax is valid without inspection. File writes and code changes undergo strict verification gates before task completion.
4. TOOL HIERARCHY:
   - For understanding or summarizing a project: invoke `get_codebase_summary` FIRST.
   - For finding functions/classes/callers: use `lookup_symbol` or `search_code`.
   - Never traverse folders recursively with `list_directory` when search or summary tools exist.
5. RESPONSE FORMAT: Output EXACTLY ONE JSON block:
   For taking an action:
   ```json
   {{
     "thought": "<reasoning on current facts and observations>",
     "hypothesis": "<what this action will prove or achieve>",
     "action": "tool_call",
     "tool": "<tool_name>",
     "arguments": {{...}}
   }}
   ```
   For completing the objective:
   ```json
   {{
     "thought": "<synthesis of verified ground-truth evidence>",
     "action": "finish",
     "answer": "<complete, detailed final answer>"
   }}
   ```
Output pure valid JSON. No conversational preamble before the JSON block.
"""

# 5. Core logic / classes / functions
def extract_json_block(text: str) -> dict[str, Any] | None:
    """Extract and parse first valid JSON block from text."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else text.strip()
    try:
        return json.loads(candidate)
    except Exception:
        match_obj = re.search(r"(\{.*\})", text, re.DOTALL)
        if match_obj:
            try:
                return json.loads(match_obj.group(1))
            except Exception:
                pass
    return None


class AgentOrchestrator:
    """Supervises planning, tool invocation, and verification loops."""

    def __init__(
        self,
        provider: NvidiaNimProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        memory_repo: MemoryRepository | None = None,
        verifier: OutcomeVerifier | None = None,
    ) -> None:
        self.provider = provider or NvidiaNimProvider()
        self.tools = tool_registry or ToolRegistry()
        self.memory = memory_repo or MemoryRepository()
        self.verifier = verifier

    async def run(
        self,
        objective: str,
        working_directory: Path | str | None = None,
        project_id: str | None = None,
        max_iterations: int = 12,
    ) -> AgentState:
        """Execute autonomous loop until goal is reached with verification gate and reflection."""
        cwd = str(Path(working_directory).resolve()) if working_directory else str(Path.cwd())
        state = AgentState(
            objective=objective,
            working_directory=cwd,
            project_id=project_id,
            max_iterations=max_iterations,
        )

        verifier = self.verifier or OutcomeVerifier(workspace_root=cwd)

        # Retrieve relevant memories
        memories = await self.memory.search_memories(objective, project_id=project_id, limit=5)
        mem_str = ""
        if memories:
            mem_str = "Long-Term Project Memories:\n" + "\n".join(f"- {m.content}" for m in memories)

        # Format tool definitions
        tool_defs = [t.model_dump() for t in self.tools.get_definitions()]
        tools_str = json.dumps(tool_defs, indent=2)

        system_msg = SYSTEM_PROMPT_TEMPLATE.format(
            objective=objective,
            tools_schema=tools_str,
            memory_context=mem_str,
        )

        messages = [
            ChatMessage(role="system", content=system_msg),
            ChatMessage(role="user", content=f"Execute task: {objective}"),
        ]

        while state.iteration < state.max_iterations and not state.completed:
            state.iteration += 1

            llm_res = await self.provider.generate(messages, temperature=0.2, max_tokens=2048)
            action_data = extract_json_block(llm_res.content)

            if not action_data:
                state.completed = True
                state.final_answer = llm_res.content
                break

            # Capture thought & hypothesis into deliberation history
            if "thought" in action_data or "hypothesis" in action_data:
                state.deliberation_history.append({
                    "iteration": state.iteration,
                    "thought": action_data.get("thought", ""),
                    "hypothesis": action_data.get("hypothesis", ""),
                })

            action_type = action_data.get("action")
            if action_type == "finish":
                # Ground-truth verification gate
                verification_passed = True
                verification_errors: list[str] = []

                # 1. Verify all modified or created files
                for rel_path in state.modified_files:
                    v_res = await verifier.verify_file_created_or_modified(rel_path)
                    state.verification_results.append(v_res.model_dump())
                    if not v_res.verified:
                        verification_passed = False
                        verification_errors.append(v_res.details)

                # 2. If files were modified, verify project test suite passes
                if state.modified_files and verification_passed:
                    t_res = await verifier.verify_test_suite_passes()
                    state.verification_results.append(t_res.model_dump())
                    if not t_res.verified:
                        verification_passed = False
                        verification_errors.append(f"Regression in test suite: {t_res.details}")

                if not verification_passed:
                    # Reject finish and trigger corrective deliberation
                    messages.append(ChatMessage(role="assistant", content=llm_res.content))
                    feedback = (
                        "Verification Gate REJECTED your finish action. Ground-truth checks failed:\n"
                        + "\n".join(f"- {e}" for e in verification_errors)
                        + "\nYou must analyze and fix these issues before finishing."
                    )
                    messages.append(ChatMessage(role="user", content=feedback))
                    continue

                state.verified = True
                state.completed = True
                state.final_answer = action_data.get("answer", "Task completed.")
                break

            # Handle both {"action": "tool_call", "tool": "..."} and {"action": "<tool_name>"} or {"tool": "..."}
            tool_name = action_data.get("tool")
            if not tool_name and action_type and action_type not in ("finish", "tool_call"):
                tool_name = action_type

            if tool_name and self.tools.get_tool(tool_name):
                tool_args = action_data.get("arguments", {})

                # Track written / modified files
                if tool_name == "write_file" and "path" in tool_args:
                    file_path = str(tool_args["path"])
                    if file_path not in state.modified_files:
                        state.modified_files.append(file_path)

                # Execute tool
                tool_result = await self.tools.execute(
                    name=tool_name,
                    arguments=tool_args,
                    context={"working_directory": state.working_directory, "project_id": state.project_id},
                )

                step_record = {
                    "iteration": state.iteration,
                    "tool": tool_name,
                    "arguments": tool_args,
                    "thought": action_data.get("thought", ""),
                    "hypothesis": action_data.get("hypothesis", ""),
                    "success": tool_result.success,
                    "data": tool_result.data,
                    "error": tool_result.error,
                }
                state.tool_history.append(step_record)

                messages.append(ChatMessage(role="assistant", content=llm_res.content))

                # Reflection challenge if tool failed
                if not tool_result.success:
                    obs_content = json.dumps({
                        "tool": tool_name,
                        "success": False,
                        "error": tool_result.error,
                        "reflection_required": (
                            "Action failed. Provide structured reflection: "
                            "why did this hypothesis fail, what is the root cause, and what is your alternative strategy?"
                        ),
                    })
                else:
                    obs_content = json.dumps({
                        "tool": tool_name,
                        "success": True,
                        "result": tool_result.data,
                    })
                messages.append(ChatMessage(role="user", content=f"Observation: {obs_content}"))
            else:
                state.completed = True
                state.final_answer = llm_res.content
                break

        # Fallback Synthesis: If budget reached without explicit finish, synthesize from tool observations
        if not state.completed and state.iteration >= state.max_iterations:
            synthesis_prompt = (
                f"You have reached the observation budget ({state.max_iterations} steps). "
                f"Based strictly on all the tool outputs and data collected above, synthesize a complete, detailed, "
                f"and professional answer to the original objective: '{objective}'."
            )
            messages.append(ChatMessage(role="user", content=synthesis_prompt))
            final_res = await self.provider.generate(messages, temperature=0.3, max_tokens=3000)
            state.completed = True
            state.final_answer = final_res.content

        return state

    async def diagnose_error(self, failed_command: str, exit_code: int, stdout: str, stderr: str) -> str:
        """Phase 9 root-cause error diagnosis and repair suggestion."""
        prompt = (
            f"The following development command failed:\n"
            f"Command: {failed_command}\n"
            f"Exit Code: {exit_code}\n\n"
            f"STDOUT:\n{stdout[:1500]}\n\n"
            f"STDERR:\n{stderr[:1500]}\n\n"
            f"Provide a root cause analysis and the exact command or fix required. Be concise."
        )
        msg = [
            ChatMessage(role="system", content="You are NEMO, an expert systems diagnostician. Diagnose root cause, not symptom."),
            ChatMessage(role="user", content=prompt),
        ]
        res = await self.provider.generate(msg, temperature=0.1, max_tokens=1024)
        return res.content

# 6. Public exports
__all__ = ["AgentOrchestrator", "extract_json_block"]
