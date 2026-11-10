"""Interactive developer REPL with deterministic command routing and AI streaming."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import sys

# 2. Third-party imports
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# 3. Local / internal imports
from nemo import __version__
from nemo.agent.orchestrator import AgentOrchestrator, extract_json_block
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

    # Configure persistent command history for Up/Down arrow navigation
    prompt_session = None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        history_file = Path.home() / ".nemo" / "history.txt"
        history_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_session = PromptSession(history=FileHistory(str(history_file)))
    except Exception:
        prompt_session = None

    while True:
        try:
            if prompt_session is not None and sys.stdin.isatty():
                user_input = (await prompt_session.prompt_async("nemo> ")).strip()
            else:
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

        # Strip optional "task " prefix if user typed it
        target_goal = user_input[5:].strip() if user_input.lower().startswith("task ") else user_input

        # Execute all natural language requests with full tool capabilities & context continuity
        with console.status("[bold green]Deliberating, executing, and verifying..."):
            state = await orchestrator.run(objective=target_goal, working_directory=curr_dir)

        if state.tool_history:
            console.print("\n[bold]Execution Steps:[/bold]")
            for rec in state.tool_history:
                icon = "[green]✓[/green]" if rec["success"] else "[red]✗[/red]"
                thought_str = f" | [italic dim]{rec['thought'][:50]}...[/italic dim]" if rec.get("thought") else ""
                console.print(f" {icon} [bold cyan]{rec['tool']}[/bold cyan] [dim]{rec['arguments']}[/dim]{thought_str}")

        if state.verification_results:
            console.print("\n[bold]Verification Gate Results:[/bold]")
            for v in state.verification_results:
                v_icon = "[green]✓[/green]" if v["verified"] else "[red]✗[/red]"
                console.print(f" {v_icon} [{v['ground_truth_source']}] {v['details']}")

        if state.extracted_memories:
            console.print("\n[bold cyan]🧠 Auto-Learned Knowledge Added to Memory:[/bold cyan]")
            for m in state.extracted_memories:
                console.print(f" • [green]{m['content']}[/green] [dim]({m['type']})[/dim]")

        ans = state.final_answer or "Completed."
        parsed = extract_json_block(ans)
        if parsed and parsed.get("action") == "finish" and "answer" in parsed:
            ans = parsed["answer"]

        console.print("\n[bold]Outcome:[/bold]\n")
        console.print(Markdown(ans))
        console.print()

# 6. Public exports
__all__ = ["run_interactive_chat", "is_native_command", "is_action_intent", "KNOWN_NATIVE_PREFIXES", "ACTION_INTENT_PREFIXES"]

