"""Autonomous agent workflow orchestrator with tool dispatch and budget synthesis."""

# 1. Standard library imports
import json
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.agent.context import SessionContextManager
from nemo.agent.state import AgentState
from nemo.agent.verifier import OutcomeVerifier
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.memory.repository import ConversationRepository, MemoryRepository, TaskRepository
from nemo.tools.registry import ToolRegistry

# 4. Types, Protocols, Schemas
SYSTEM_PROMPT_TEMPLATE = """You are NEMO, an AI-native developer operating assistant on Windows with senior-developer rigor.
NEMO is a persistent development operating environment — coordinating environments, analyzing architectures, running processes, and executing verified operations (not a blind code-mutator).
Your objective is: {objective}

Available Tools:
{tools_schema}

{memory_context}
{recent_context}

Core Principles & Rules:
1. DELIBERATION & DEPTH: Before taking any action, clearly define your `thought` (evidence analysis) and `hypothesis` (what this step will verify or achieve).
2. OPERATING & ANALYSIS OVER MUTATION: Prioritize deep inspection, environment management, and dependency coordination over writing unnecessary code.
3. GROUND TRUTH VERIFICATION: Never assume a process started, port is listening, or syntax is valid without ground-truth inspection.
4. TOOL HIERARCHY & WORKFLOW INTELLIGENCE:
   - For codebase overview: invoke `get_codebase_summary` FIRST.
   - For relationship & caller inspection: invoke `query_code_graph` to see who calls a symbol or what modules depend on it.
   - For structural AST search: invoke `ast_grep` to find functions, decorators, or calls without fragile text regex.
   - For locating files across workspace: invoke `find_files` with glob patterns instead of traversing with `list_directory`.
   - For creating folders: invoke `create_folder`. Fast native directory creation.
   - For creating or writing files: invoke `write_file`. Fast native file write.
     CRITICAL: NEVER use PowerShell echo/Out-File/terminal commands to create files or folders! Write pure raw text/code without PowerShell backtick escaping.
   - For Git push, CI/CD, Netlify, or Vercel deployment: ALWAYS invoke `analyze_deployment` first to audit git remotes, verify .gitignore prevents .env leaks, and validate build scripts.
   - For project initialization & servers: invoke `inspect_project_environment` to inspect dependencies. If missing, install them. For dev servers (e.g. `npm run dev`), check ports with `port_manager`, invoke `launch_background_process`, verify with `http_probe`, then call `open_browser`.
   - For scaffolding new stacks (React TypeScript, Next.js, FastAPI, Node): invoke `scaffold_project`.
   - For reading documents (.pdf, .docx, .csv): invoke `read_document`.
   - For generating reports and docs: invoke `generate_document` (.docx, .html, .md).
   - For presentations: invoke `generate_presentation` (HTML slide deck with keyboard arrows).
   - For environment variables & missing secrets: invoke `inspect_env_config`.
   - For inspecting code modifications before declaring completion: invoke `git_diff`.
   - For SQLite database introspection, listing tables, and running queries: invoke `database_inspector`. For Nemo's internal database, pass `path: '~/.nemo/nemo.db'`.
   - For testing REST/HTTP endpoints, webhooks, or API latency: invoke `api_tester`.
   - For live hardware metrics (CPU, RAM, disk), listening ports, or process management: invoke `system_inspector`.
   - For Git operations (branches, staged diffs, semantic commits, push readiness): invoke `git_operations`.
   - For Windows clipboard copy/paste, toast notifications, hard ringing alarms, or floating desktop widgets (timers & Pomodoro): invoke `desktop_integration` (action: 'notify', 'set_alarm', 'set_timer', 'start_pomodoro', 'list_alarms', 'cancel_alarm'). E.g., for a 6 PM alarm, invoke `desktop_integration` with `action='set_alarm', time='18:00'`. For a desktop floating timer, invoke with `action='set_timer', minutes=25`. For a custom Pomodoro, invoke with `action='start_pomodoro', focus_minutes=25, break_minutes=5`.
   - CRITICAL WORKSPACE INTEGRITY: NEVER write temporary scripts (.ps1, .bat) to the workspace for setting alarms, timers, or desktop actions. ALWAYS use `desktop_integration`.
   - For web search, technical documentation scraping, package info, or online research: invoke `web_researcher`.
   - Never traverse folders recursively with `list_directory` when search or summary tools exist.
5. CONVERSATIONAL & PATH CONTINUITY: If the user says 'that folder', 'that file', or references a previous step, resolve the path to the exact target folder/file referenced in Recent Context above, rather than defaulting to the current root.
6. RESPONSE FORMAT: Output EXACTLY ONE JSON block per turn (never concatenate multiple tool calls or JSON blocks into one turn):
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
    text_clean = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_clean, re.DOTALL)
    candidate = match.group(1) if match else text_clean
    try:
        res = json.loads(candidate, strict=False)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    match_obj = re.search(r"(\{.*\})", text_clean, re.DOTALL)
    if match_obj:
        try:
            res = json.loads(match_obj.group(1), strict=False)
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    # Ponytail: Parse first valid JSON object using raw_decode even when multiple JSON blocks are concatenated
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text_clean):
        idx = text_clean.find("{", pos)
        if idx == -1:
            break
        try:
            obj, _ = decoder.raw_decode(text_clean[idx:])
            if isinstance(obj, dict) and ("action" in obj or "tool" in obj or "thought" in obj):
                return obj
            pos = idx + 1
        except Exception:
            pos = idx + 1

    # Ponytail: Robust fallback for LLM finish actions where "answer" has unescaped raw newlines or quotes
    if '"action"' in text_clean and '"finish"' in text_clean and '"answer"' in text_clean:
        ans_match = re.search(r'"answer"\s*:\s*"(.*)', text_clean, re.DOTALL)
        if ans_match:
            raw_val = ans_match.group(1)
            raw_val = re.sub(r'"\s*\}*\s*$', "", raw_val)
            return {"action": "finish", "answer": raw_val.strip()}

    return None


class AgentOrchestrator:
    """Supervises planning, tool invocation, and verification loops."""

    def __init__(
        self,
        provider: NvidiaNimProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        memory_repo: MemoryRepository | None = None,
        conv_repo: ConversationRepository | None = None,
        task_repo: TaskRepository | None = None,
        verifier: OutcomeVerifier | None = None,
    ) -> None:
        self.provider = provider or NvidiaNimProvider()
        self.tools = tool_registry or ToolRegistry()
        self.memory = memory_repo or MemoryRepository()
        self.conv_repo = conv_repo or ConversationRepository()
        self.task_repo = task_repo or TaskRepository()
        self.verifier = verifier

    async def run(
        self,
        objective: str,
        working_directory: Path | str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        max_iterations: int = 12,
    ) -> AgentState:
        """Execute autonomous loop until goal is reached with verification gate and reflection."""
        cwd = str(Path(working_directory).resolve()) if working_directory else str(Path.cwd())
        state = AgentState(
            objective=objective,
            working_directory=cwd,
            project_id=project_id,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
        )

        # Establish or retrieve persistent conversation session
        if conversation_id:
            conv = await self.conv_repo.get_conversation(conversation_id)
            if conv:
                state.conversation_id = conv.id
            else:
                conv = await self.conv_repo.create_conversation(title=objective[:60], project_id=project_id)
                state.conversation_id = conv.id
        else:
            conv = await self.conv_repo.create_conversation(title=objective[:60], project_id=project_id)
            state.conversation_id = conv.id

        # Record user message in DB
        await self.conv_repo.add_message(state.conversation_id, "user", objective)

        verifier = self.verifier or OutcomeVerifier(workspace_root=cwd)

        # Retrieve relevant memories
        memories = await self.memory.search_memories(objective, project_id=project_id, limit=5)
        mem_str = ""
        if memories:
            mem_str = "Long-Term Project Memories:\n" + "\n".join(f"- {m.content}" for m in memories)

        # Context continuity across multi-turn interactions
        context_mgr = SessionContextManager()
        recent_context = context_mgr.get_recent_context(objective)

        # Format tool definitions
        tool_defs = [t.model_dump() for t in self.tools.get_definitions()]
        tools_str = json.dumps(tool_defs, indent=2)

        system_msg = SYSTEM_PROMPT_TEMPLATE.format(
            objective=objective,
            tools_schema=tools_str,
            memory_context=mem_str,
            recent_context=recent_context,
        )

        messages = [
            ChatMessage(role="system", content=system_msg),
        ]

        # Inject previous conversation messages for conversational continuity if resuming
        if conversation_id:
            prior_msgs = await self.conv_repo.get_messages(state.conversation_id, limit=20)
            # Exclude the current message we just added
            for pm in prior_msgs[:-1]:
                messages.append(ChatMessage(role=pm.role, content=pm.content))

        messages.append(ChatMessage(role="user", content=f"Execute task: {objective}"))

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

                # 2. If files were modified, verify project test suite passes (skips for non-code files)
                if state.modified_files and verification_passed:
                    t_res = await verifier.verify_test_suite_passes(modified_files=state.modified_files)
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
            parsed_final = extract_json_block(final_res.content)
            if parsed_final and "answer" in parsed_final:
                state.final_answer = parsed_final["answer"]
            else:
                state.final_answer = final_res.content

        # Automated Memory Consolidation: Extract durable technical facts from completed task
        if state.completed and state.final_answer:
            try:
                from nemo.memory.extractor import MemoryExtractor
                extractor = MemoryExtractor(provider=self.provider, repository=self.memory)
                new_mems = await extractor.extract_and_persist(
                    objective=objective,
                    observations=state.tool_history,
                    outcome=state.final_answer,
                    project_id=project_id,
                )
                state.extracted_memories = [
                    {"id": m.id, "content": m.content, "type": m.type}
                    for m in new_mems
                ]
            except Exception:
                pass

        # Persist session context for successive turn continuity
        try:
            context_mgr.save_context(
                objective=objective,
                outcome=state.final_answer or "",
                tool_history=state.tool_history,
                working_directory=cwd,
            )
        except Exception:
            pass

        # Record assistant answer in conversation history and audit task
        if state.final_answer and state.conversation_id:
            try:
                await self.conv_repo.add_message(state.conversation_id, "assistant", state.final_answer)
                await self.task_repo.record_task(objective=objective, thread_id=state.conversation_id, status="completed")
            except Exception:
                pass

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
