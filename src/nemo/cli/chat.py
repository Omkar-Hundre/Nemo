"""Interactive developer REPL with deterministic command routing and AI streaming."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import sys

# 2. Third-party imports
from rich.console import Console
from rich.panel import Panel

# 3. Local / internal imports
from nemo import __version__
from nemo.agent.orchestrator import AgentOrchestrator
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.config.settings import get_settings
from nemo.database.connection import init_db
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.intelligence.indexer import ProjectIndexer
from nemo.memory.repository import MemoryRepository, ProjectRepository

# 4. Types, Protocols, Schemas
KNOWN_NATIVE_PREFIXES = (
    "git", "dir", "ls", "cd", "python", "py", "node", "npm",
    "pnpm", "yarn", "uv", "pip", "pytest", "cargo", "docker",
    "cat", "type", "cls", "clear", "echo", "whoami", "get-childitem",
    "get-content", "get-date", "set-location",
)

ACTION_INTENT_PREFIXES = (
    "initialize", "init ", "start ", "launch ", "setup ",
    "scaffold ", "install ", "build ", "run dev", "run start",
)

# 5. Core logic / classes / functions
console = Console()


def is_native_command(line: str) -> bool:
    """Deterministic detection of shell commands to avoid LLM token overhead."""
    first_token = line.strip().split()[0].lower() if line.strip() else ""
    return first_token in KNOWN_NATIVE_PREFIXES


def is_action_intent(text: str) -> bool:
    """Detect if natural language instruction intends operational execution."""
    t = text.lower().strip()
    return any(t.startswith(prefix) for prefix in ACTION_INTENT_PREFIXES)


async def run_interactive_chat() -> None:
    """Launch persistent interactive developer operating session."""
    await init_db()
    settings = get_settings()
    curr_dir = Path.cwd()

    # Load active project
    proj_repo = ProjectRepository()
    project = await proj_repo.get_by_path(curr_dir)
    project_name = project.name if project else curr_dir.name

    # Check index status
    indexer = ProjectIndexer(curr_dir)
    indexed_files = len(indexer.get_indexed_files())

    # Render Welcome Banner
    banner = (
        f"[bold cyan]NEMO ASSISTANT[/bold cyan] [green]● Connected[/green]\n\n"
        f"[bold]Active Project:[/bold]  {project_name} [dim]({curr_dir})[/dim]\n"
        f"[bold]IDE Adapter:[/bold]     {settings.default_ide}\n"
        f"[bold]Memory System:[/bold]   Synchronized\n"
        f"[bold]Code Index:[/bold]      {indexed_files} files up to date\n\n"
        f"[dim]Type natural language requests or native terminal commands. 'exit' to quit.[/dim]"
    )
    console.print(Panel(banner, title=f"[bold]NEMO v{__version__} — Developer Runtime[/bold]", border_style="cyan"))

    executor = NativeSubprocessExecutor(default_shell=settings.default_shell)
    provider = NvidiaNimProvider()
    mem_repo = MemoryRepository()
    orchestrator = AgentOrchestrator()

    history: list[ChatMessage] = []

    while True:
        try:
            user_input = console.input("[bold cyan]nemo>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session closed.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        # Fast deterministic native command passthrough
        if is_native_command(user_input):
            res = await executor.execute(user_input)
            if res.stdout:
                console.print(res.stdout, end="")
            if res.stderr:
                console.print(f"[red]{res.stderr}[/red]", end="")
            if not res.is_success:
                console.print(f"[dim red]Exit code: {res.exit_code}[/dim red]")
            continue

        # Built-in direct remember command
        if user_input.lower().startswith("remember "):
            fact = user_input[9:].strip()
            item = await mem_repo.add_memory(content=fact, scope="project", project_id=project.id if project else None)
            console.print(f"[green]Remembered [dim]({item.id[:8]})[/dim]:[/green] {item.content}")
            continue

        # Autonomous operational task trigger (explicit 'task <...>' or detected operational action intent)
        is_task_cmd = user_input.lower().startswith("task ")
        if is_task_cmd or is_action_intent(user_input):
            goal = user_input[5:].strip() if is_task_cmd else user_input
            console.print(f"[bold cyan]Executing operational action:[/bold cyan] {goal}")
            with console.status("[bold green]Deliberating and executing..."):
                state = await orchestrator.run(objective=goal, working_directory=curr_dir)
            for rec in state.tool_history:
                icon = "[green]✓[/green]" if rec["success"] else "[red]✗[/red]"
                thought_str = f" | [italic dim]{rec['thought'][:50]}...[/italic dim]" if rec.get("thought") else ""
                console.print(f" {icon} [cyan]{rec['tool']}[/cyan] [dim]{rec['arguments']}[/dim]{thought_str}")
            if state.verification_results:
                for v in state.verification_results:
                    v_icon = "[green]✓[/green]" if v["verified"] else "[red]✗[/red]"
                    console.print(f" {v_icon} [{v['ground_truth_source']}] {v['details']}")
            console.print(f"\n{state.final_answer or 'Completed.'}\n")
            continue

        # Conversational reasoning with memory context
        memories = await mem_repo.search_memories(user_input, project_id=project.id if project else None, limit=5)
        mem_ctx = ""
        if memories:
            mem_ctx = "\nRelevant memories:\n" + "\n".join(f"- {m.content}" for m in memories)

        system_prompt = (
            "You are NEMO, an expert AI-native developer assistant operating across the developer's Windows environment."
            + mem_ctx
        )
        msgs = [ChatMessage(role="system", content=system_prompt), *history[-6:], ChatMessage(role="user", content=user_input)]

        full_reply = []
        try:
            async for chunk in provider.stream(msgs):
                console.print(chunk, end="", highlight=False)
                full_reply.append(chunk)
            console.print()
            history.append(ChatMessage(role="user", content=user_input))
            history.append(ChatMessage(role="assistant", content="".join(full_reply)))
        except Exception as exc:
            console.print(f"[bold red]Inference error: {exc}[/bold red]")

# 6. Public exports
__all__ = ["run_interactive_chat", "is_native_command", "is_action_intent", "KNOWN_NATIVE_PREFIXES", "ACTION_INTENT_PREFIXES"]

