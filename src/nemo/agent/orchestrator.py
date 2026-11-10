"""Autonomous agent workflow orchestrator with tool dispatch and diagnosis."""

# 1. Standard library imports
import json
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.agent.state import AgentState
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.memory.repository import MemoryRepository
from nemo.tools.registry import ToolRegistry

# 4. Types, Protocols, Schemas
SYSTEM_PROMPT_TEMPLATE = """You are NEMO, an autonomous AI-native developer operating assistant on Windows.
Your objective is: {objective}

Available Tools:
{tools_schema}

{memory_context}

Execution Rules:
1. When you need to take an action, output EXACTLY ONE JSON block matching:
```json
{{"action": "tool_call", "tool": "<tool_name>", "arguments": {{...}}}}
```
2. When the objective is achieved or you have answered the user, output:
```json
{{"action": "finish", "answer": "<final answer / summary of work done>"}}
```
3. Never invent facts. Base conclusions strictly on tool execution results. Output pure valid JSON.
"""

# 5. Core logic / classes / functions
def extract_json_block(text: str) -> dict[str, Any] | None:
    """Extract and parse first valid JSON block from text."""
    # Match markdown code block ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else text.strip()
    try:
        return json.loads(candidate)
    except Exception:
        # Fallback regex search for { ... }
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
    ) -> None:
        self.provider = provider or NvidiaNimProvider()
        self.tools = tool_registry or ToolRegistry()
        self.memory = memory_repo or MemoryRepository()

    async def run(
        self,
        objective: str,
        working_directory: Path | str | None = None,
        project_id: str | None = None,
        max_iterations: int = 8,
    ) -> AgentState:
        """Execute autonomous loop until goal is reached or iteration limit hit."""
        cwd = str(Path(working_directory).resolve()) if working_directory else str(Path.cwd())
        state = AgentState(
            objective=objective,
            working_directory=cwd,
            project_id=project_id,
            max_iterations=max_iterations,
        )

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

            # Call reasoning model
            llm_res = await self.provider.generate(messages, temperature=0.2, max_tokens=2048)
            action_data = extract_json_block(llm_res.content)

            if not action_data:
                # LLM output direct text conclusion
                state.completed = True
                state.final_answer = llm_res.content
                break

            action_type = action_data.get("action")
            if action_type == "finish":
                state.completed = True
                state.final_answer = action_data.get("answer", "Task completed.")
                break

            if action_type == "tool_call":
                tool_name = action_data.get("tool", "")
                tool_args = action_data.get("arguments", {})

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
                    "success": tool_result.success,
                    "data": tool_result.data,
                    "error": tool_result.error,
                }
                state.tool_history.append(step_record)

                # Append assistant call and tool observation to prompt history
                messages.append(ChatMessage(role="assistant", content=llm_res.content))
                obs_content = json.dumps({
                    "tool": tool_name,
                    "success": tool_result.success,
                    "result": tool_result.data if tool_result.success else tool_result.error,
                })
                messages.append(ChatMessage(role="user", content=f"Observation: {obs_content}"))
            else:
                state.completed = True
                state.final_answer = llm_res.content
                break

        if not state.completed and state.iteration >= state.max_iterations:
            state.final_answer = f"Iteration budget reached ({state.max_iterations} steps). Last status recorded."

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

