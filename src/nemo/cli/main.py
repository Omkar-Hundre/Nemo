"""Command Line Interface entry point for NEMO."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import subprocess
import sys

# 2. Third-party imports
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer
import uvicorn

# 3. Local / internal imports
from nemo import __version__
from nemo.agent.orchestrator import AgentOrchestrator, extract_json_block
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.cli.doctor import run_doctor
from nemo.cli.setup import run_setup_wizard
from nemo.config.settings import get_settings
from nemo.daemon.client import DaemonClient
from nemo.daemon.server import app as daemon_fastapi_app
from nemo.database.connection import init_db, resolve_database_url
from nemo.execution.sessions.manager import SessionManager
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.intelligence.indexer import ProjectIndexer
from nemo.integrations.ide.registry import IDERegistry
from nemo.memory.repository import MemoryRepository, ProjectRepository

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
app = typer.Typer(
    name="nemo",
    help="AI-Native Developer Operating Environment for Windows.",
    add_completion=False,
)
sessions_app = typer.Typer(
    name="sessions",
    help="Manage persistent terminal sessions and background jobs.",
)
memory_app = typer.Typer(
    name="memory",
    help="Inspect, query, and manage long-term developer memories.",
)
project_app = typer.Typer(
    name="project",
    help="Register and inspect workspace projects.",
)
index_app = typer.Typer(
    name="index",
    help="Scan, hash, and incrementally index project codebases.",
)
ide_app = typer.Typer(
    name="ide",
    help="Detect and coordinate with code editors (Antigravity, VS Code).",
)
daemon_app = typer.Typer(
    name="daemon",
    help="Manage local background daemon server.",
)

app.add_typer(sessions_app, name="sessions")
app.add_typer(memory_app, name="memory")
app.add_typer(project_app, name="project")
app.add_typer(index_app, name="index")
app.add_typer(ide_app, name="ide")
app.add_typer(daemon_app, name="daemon")

console = Console()
session_mgr = SessionManager()
memory_repo = MemoryRepository()
project_repo = ProjectRepository()
ide_registry = IDERegistry()
daemon_client = DaemonClient()


@app.callback(invoke_without_command=True)
def default_main(ctx: typer.Context) -> None:
    """Default invocation with no arguments launches interactive chat REPL."""
    if ctx.invoked_subcommand is None:
        from nemo.cli.chat import run_interactive_chat
        asyncio.run(run_interactive_chat())


@app.command()
def chat() -> None:
    """Launch persistent conversational development operating session."""
    from nemo.cli.chat import run_interactive_chat
    asyncio.run(run_interactive_chat())


@app.command()
def version() -> None:
    """Display NEMO version."""
    console.print(f"[bold cyan]NEMO[/bold cyan] version [bold green]{__version__}[/bold green]")


@app.command()
def setup(
    api_key: str | None = typer.Option(None, "--api-key", "-k", help="NVIDIA NIM API key (starts with nvapi-)."),
) -> None:
    """Run full interactive setup and verification wizard."""
    asyncio.run(run_setup_wizard(custom_key=api_key))


@app.command()
def status() -> None:
    """Display current system and environment status (fast, local only)."""
    settings = get_settings()
    has_key = bool(settings.nvidia_api_key and settings.nvidia_api_key.startswith("nvapi-"))
    db_url = resolve_database_url()
    daemon_online = asyncio.run(daemon_client.is_running())

    content = (
        f"[bold]Version:[/bold] {__version__}\n"
        f"[bold]Shell:[/bold] {settings.default_shell}\n"
        f"[bold]IDE:[/bold] {settings.default_ide}\n"
        f"[bold]Workspace:[/bold] {settings.workspace_root}\n"
        f"[bold]Database:[/bold] {db_url}\n"
        f"[bold]Daemon:[/bold] {'[green]ONLINE[/green] (http://127.0.0.1:8765)' if daemon_online else '[dim]OFFLINE[/dim]'}\n"
        f"[bold]Model:[/bold] {settings.nvidia_model}\n"
        f"[bold]API Key:[/bold] {'[green]Configured[/green]' if has_key else '[red]Missing[/red]'}"
    )
    console.print(Panel(content, title="[bold cyan]NEMO Status[/bold cyan]", border_style="cyan"))


@app.command()
def doctor(
    test_api: bool = typer.Option(
        False,
        "--test-api",
        "-t",
        help="Perform a live ping to NVIDIA NIM endpoint.",
    )
) -> None:
    """Diagnose local setup, dependencies, and connections."""
    run_doctor(test_api=test_api)


@app.command()
def run(
    command: str = typer.Argument(..., help="Terminal command to execute."),
    shell: str = typer.Option("powershell", "--shell", "-s", help="Target shell (powershell, cmd, bash)."),
    session: str | None = typer.Option(None, "--session", help="Run inside persistent session id."),
    background: bool = typer.Option(False, "--background", "-b", help="Launch in background."),
    timeout: float = typer.Option(600.0, "--timeout", help="Timeout in seconds."),
) -> None:
    """Execute command natively with process tracking and exit codes."""
    if session:
        sess = session_mgr.get_session(session)
        if not sess:
            console.print(f"[bold red]Session '{session}' not found.[/bold red]")
            sys.exit(1)
        if background:
            session_mgr.launch_background(session, command)
            console.print(f"[green]Background command launched in session [bold]{session}[/bold][/green]")
            return

        result = asyncio.run(session_mgr.execute(session, command, timeout_seconds=timeout))
    else:
        executor = NativeSubprocessExecutor(default_shell=shell)
        result = asyncio.run(executor.execute(command, timeout_seconds=timeout))

    if result.stdout:
        console.print(result.stdout, end="")
    if result.stderr:
        console.print(f"[red]{result.stderr}[/red]", end="")

    if not result.is_success:
        console.print(f"[bold red]Exit code: {result.exit_code}[/bold red]")
        sys.exit(result.exit_code)


# --- Daemon Commands ---
@daemon_app.command("start")
def daemon_start(
    port: int = typer.Option(8765, "--port", "-p", help="Port for local daemon server."),
    detach: bool = typer.Option(False, "--detach", "-d", help="Run detached in background."),
) -> None:
    """Start local background daemon server."""
    if detach:
        cmd = [sys.executable, "-m", "uvicorn", "nemo.daemon.server:app", "--port", str(port), "--host", "127.0.0.1"]
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        console.print(f"[green]Daemon started in background (PID {proc.pid}) at http://127.0.0.1:{port}[/green]")
        return

    console.print(f"[bold cyan]Starting NEMO Daemon on http://127.0.0.1:{port}...[/bold cyan]")
    uvicorn.run(daemon_fastapi_app, host="127.0.0.1", port=port, log_level="info")


@daemon_app.command("status")
def daemon_status() -> None:
    """Check if local daemon is running and display metrics."""
    running = asyncio.run(daemon_client.is_running())
    if not running:
        console.print("[dim]Daemon is OFFLINE.[/dim]")
        return

    info = asyncio.run(daemon_client.get_status())
    console.print(Panel(
        f"[bold green]Daemon is ONLINE[/bold green]\n"
        f"Version: {info.get('version')}\n"
        f"Workspace: {info.get('workspace_root')}\n"
        f"Active Sessions: {info.get('active_sessions_count')}\n"
        f"Total Sessions: {info.get('total_sessions_count')}",
        title="[bold cyan]NEMO Daemon[/bold cyan]",
        border_style="green",
    ))


# --- Sessions Commands ---
@sessions_app.command("create")
def create_session(
    shell: str = typer.Option("powershell", "--shell", "-s", help="Shell type (powershell, cmd, bash)."),
    cwd: str | None = typer.Option(None, "--cwd", help="Working directory."),
) -> None:
    """Create a new managed persistent session."""
    target_path = Path(cwd) if cwd else Path.cwd()
    s = session_mgr.create_session(shell=shell, cwd=target_path)
    console.print(f"[green]Created session [bold]{s.session_id}[/bold] ({s.shell}) in {s.cwd}[/green]")


@sessions_app.command("list")
def list_sessions() -> None:
    """List all registered terminal sessions."""
    sessions = session_mgr.list_sessions()
    if not sessions:
        console.print("[dim]No active terminal sessions.[/dim]")
        return

    table = Table(title="Managed Terminal Sessions", border_style="bright_blue")
    table.add_column("Session ID", style="bold cyan", width=12)
    table.add_column("Shell", width=12)
    table.add_column("PID", width=8)
    table.add_column("Status", width=12)
    table.add_column("Working Directory", style="dim white")

    for s in sessions:
        color = "green" if s.status.value == "running" else "yellow" if s.status.value == "idle" else "dim"
        table.add_row(
            s.session_id,
            s.shell,
            str(s.pid or "-"),
            f"[{color}]{s.status.value.upper()}[/{color}]",
            s.cwd,
        )

    console.print(table)


@sessions_app.command("show")
def show_session(
    session_id: str = typer.Argument(..., help="Session ID to inspect."),
) -> None:
    """Display session status and recent buffered output lines."""
    s = session_mgr.get_session(session_id)
    if not s:
        console.print(f"[bold red]Session '{session_id}' not found.[/bold red]")
        sys.exit(1)

    console.print(f"[bold cyan]Session {s.session_id}[/bold cyan] ({s.status.value.upper()}) | Shell: {s.shell} | PID: {s.pid or '-'}")
    console.print(f"CWD: {s.cwd}")
    console.print("\n[bold]Recent Output:[/bold]")
    if not s.recent_output:
        console.print("[dim](No output recorded)[/dim]")
    else:
        for line in s.recent_output[-30:]:
            console.print(line)


@sessions_app.command("stop")
def stop_session(
    session_id: str = typer.Argument(..., help="Session ID to terminate."),
) -> None:
    """Terminate an active session and its process tree."""
    stopped = asyncio.run(session_mgr.terminate(session_id))
    if stopped:
        console.print(f"[green]Session [bold]{session_id}[/bold] terminated.[/green]")
    else:
        console.print(f"[red]Failed to terminate session '{session_id}'.[/red]")


# --- Memory Commands ---
@memory_app.command("init")
def memory_init() -> None:
    """Initialize database tables for memory and projects."""
    asyncio.run(init_db())
    console.print("[bold green]Database schema initialized successfully.[/bold green]")


@memory_app.command("list")
def memory_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum memories to list."),
) -> None:
    """List recent memories."""
    asyncio.run(init_db())
    items = asyncio.run(memory_repo.list_memories(limit=limit))
    if not items:
        console.print("[dim]No memories stored yet.[/dim]")
        return

    table = Table(title="Stored Memories", border_style="bright_blue")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Type", width=12)
    table.add_column("Scope", width=10)
    table.add_column("Content", style="white")

    for m in items:
        table.add_row(m.id[:8], m.type, m.scope, m.content)

    console.print(table)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query string."),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results."),
) -> None:
    """Search memories by content keywords."""
    asyncio.run(init_db())
    items = asyncio.run(memory_repo.search_memories(query, limit=limit))
    if not items:
        console.print(f"[dim]No memories matching '{query}'.[/dim]")
        return

    table = Table(title=f"Memory Search: '{query}'", border_style="bright_blue")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Type", width=12)
    table.add_column("Content", style="white")

    for m in items:
        table.add_row(m.id[:8], m.type, m.content)

    console.print(table)


@app.command()
def remember(
    fact: str = typer.Argument(..., help="Fact or technical decision to remember."),
    scope: str = typer.Option("global", "--scope", "-s", help="Memory scope ('global' or 'project')."),
    type: str = typer.Option("fact", "--type", "-t", help="Memory type ('fact', 'decision', 'preference')."),
) -> None:
    """Record a new fact or technical decision in memory."""
    asyncio.run(init_db())
    item = asyncio.run(memory_repo.add_memory(content=fact, scope=scope, memory_type=type))
    console.print(f"[green]Remembered [dim]({item.id[:8]})[/dim]:[/green] {item.content}")


# --- Project Commands ---
@project_app.command("add")
def project_add(
    path: str = typer.Argument(..., help="Path to project workspace."),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name for project."),
) -> None:
    """Register a project workspace."""
    asyncio.run(init_db())
    p = Path(path).resolve()
    if not p.exists():
        console.print(f"[bold red]Path does not exist: {p}[/bold red]")
        sys.exit(1)

    proj_name = name or p.name
    proj = asyncio.run(project_repo.register_project(name=proj_name, root_path=p))
    console.print(f"[green]Project registered [bold]{proj.name}[/bold] [dim]({proj.id[:8]})[/dim] at {proj.root_path}[/green]")


@project_app.command("list")
def project_list() -> None:
    """List all registered projects."""
    asyncio.run(init_db())
    projects = asyncio.run(project_repo.list_projects())
    if not projects:
        console.print("[dim]No projects registered yet.[/dim]")
        return

    table = Table(title="Registered Projects", border_style="bright_blue")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Name", style="bold cyan", width=20)
    table.add_column("Root Path", style="white")

    for p in projects:
        table.add_row(p.id[:8], p.name, p.root_path)

    console.print(table)


# --- Indexing Commands ---
@index_app.callback(invoke_without_command=True)
def index_default(
    ctx: typer.Context,
    path: str = typer.Argument(".", help="Workspace directory to index."),
    force: bool = typer.Option(False, "--force", "-f", help="Force complete re-indexing without hash cache."),
) -> None:
    """Scan and incrementally index codebase."""
    if ctx.invoked_subcommand is not None:
        return

    target = Path(path).resolve()
    if not target.exists():
        console.print(f"[bold red]Path does not exist: {target}[/bold red]")
        sys.exit(1)

    indexer = ProjectIndexer(target)
    with console.status(f"[bold cyan]Indexing {target.name}..."):
        report = indexer.run_index(force=force)

    table = Table(title=f"Indexing Report: {target.name}", border_style="bright_blue")
    table.add_column("Metric", style="bold white", width=20)
    table.add_column("Value", style="cyan")

    table.add_row("Total Files", str(report.total_files))
    table.add_row("Indexed / Changed", f"[green]{report.indexed_files}[/green]")
    table.add_row("Skipped (Unchanged)", f"[yellow]{report.skipped_files}[/yellow]")
    table.add_row("Duration", f"{report.duration_ms} ms")
    if report.languages:
        langs_str = ", ".join(f"{lang} ({cnt})" for lang, cnt in sorted(report.languages.items()))
        table.add_row("Languages", langs_str)

    console.print(table)


# --- IDE Commands ---
@ide_app.command("list")
def ide_list() -> None:
    """Detect and list supported IDEs on Windows."""
    adapters = asyncio.run(ide_registry.list_available())
    table = Table(title="Supported IDEs", border_style="bright_blue")
    table.add_column("Editor", style="bold cyan", width=15)
    table.add_column("Status", width=12)
    table.add_column("Executable Path", style="dim white")

    for ad in adapters:
        status_text = "[green]INSTALLED[/green]" if ad["detected"] else "[dim]NOT FOUND[/dim]"
        table.add_row(ad["name"].capitalize(), status_text, ad["executable"] or "-")

    console.print(table)


@ide_app.command("open")
def ide_open(
    path: str = typer.Argument(".", help="Project directory or registered name."),
    editor: str | None = typer.Option(None, "--editor", "-e", help="Specific editor (antigravity, vscode)."),
) -> None:
    """Launch IDE with target project workspace."""
    target_path = Path(path).resolve()
    success = asyncio.run(ide_registry.open_project(target_path, preferred_ide=editor))
    if success:
        console.print(f"[green]Opened workspace in IDE: {target_path}[/green]")
    else:
        console.print(f"[bold red]Failed to open workspace in IDE ({editor or 'default'}).[/bold red]")
        sys.exit(1)


@ide_app.command("open-file")
def ide_open_file(
    file: str = typer.Argument(..., help="Path to file to open."),
    line: int | None = typer.Option(None, "--line", "-l", help="Target line number."),
    editor: str | None = typer.Option(None, "--editor", "-e", help="Specific editor (antigravity, vscode)."),
) -> None:
    """Open specific file in IDE, optionally at line."""
    target_file = Path(file).resolve()
    if not target_file.exists():
        console.print(f"[bold red]File does not exist: {target_file}[/bold red]")
        sys.exit(1)

    success = asyncio.run(ide_registry.open_file(target_file, line=line, preferred_ide=editor))
    if success:
        console.print(f"[green]Opened {target_file.name}:{line or 1}[/green]")
    else:
        console.print(f"[bold red]Failed to open file in IDE.[/bold red]")
        sys.exit(1)


# --- Autonomous Agent Commands ---
@app.command()
def task(
    objective: str = typer.Argument(..., help="High-level objective for autonomous agent."),
    max_steps: int = typer.Option(8, "--max-steps", "-m", help="Maximum execution steps."),
) -> None:
    """Run autonomous multi-step agent workflow with tool execution and verification."""
    async def _run_agent():
        await init_db()
        orchestrator = AgentOrchestrator()
        console.print(f"[bold cyan]Starting task:[/bold cyan] {objective}")

        with console.status("[bold green]Planning and executing steps..."):
            state = await orchestrator.run(objective=objective, max_iterations=max_steps)

        console.print("\n[bold]Execution Steps:[/bold]")
        for record in state.tool_history:
            status_icon = "[green]✓[/green]" if record["success"] else "[red]✗[/red]"
            console.print(f" {status_icon} [bold cyan]{record['tool']}[/bold cyan] [dim]{record['arguments']}[/dim]")

        ans = state.final_answer or "Completed."
        parsed = extract_json_block(ans)
        if parsed and parsed.get("action") == "finish" and "answer" in parsed:
            ans = parsed["answer"]
        console.print(f"\n[bold]Final Outcome:[/bold]\n{ans}")

    asyncio.run(_run_agent())


@app.command()
def diagnose(
    command: str = typer.Argument(..., help="Command that failed or needs troubleshooting."),
) -> None:
    """Run command, capture error output, and perform root-cause diagnosis via Nemotron."""
    async def _diagnose():
        executor = NativeSubprocessExecutor()
        console.print(f"[dim]Running command:[/dim] {command}")
        result = await executor.execute(command)

        if result.is_success:
            console.print(f"[green]Command succeeded (exit code 0). No error detected.[/green]")
            if result.stdout:
                console.print(result.stdout)
            return

        console.print(f"[red]Command failed with exit code {result.exit_code}[/red]")
        orchestrator = AgentOrchestrator()
        with console.status("[bold cyan]Diagnosing root cause..."):
            analysis = await orchestrator.diagnose_error(
                failed_command=command,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        console.print(Panel(analysis, title="[bold red]Root Cause Diagnosis[/bold red]", border_style="red"))

    asyncio.run(_diagnose())


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Natural language question or request."),
) -> None:
    """Ask a question to NVIDIA Nemotron with memory recall."""
    async def _stream_query():
        await init_db()
        memories = await memory_repo.search_memories(prompt, limit=5)
        memory_context = ""
        if memories:
            memory_context = "\n\nRelevant long-term memories:\n" + "\n".join(f"- {m.content}" for m in memories)

        provider = NvidiaNimProvider()
        system_prompt = (
            "You are NEMO, an AI-native developer operating assistant for Windows."
            + memory_context
        )
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=prompt),
        ]
        async for chunk in provider.stream(messages):
            console.print(chunk, end="", highlight=False)
        console.print()

    try:
        asyncio.run(_stream_query())
    except Exception as exc:
        console.print(f"[bold red]Error communicating with NVIDIA NIM: {exc}[/bold red]")
        sys.exit(1)


# 6. Public exports
__all__ = ["app"]

if __name__ == "__main__":
    app()
