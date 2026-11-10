"""Command Line Interface entry point for NEMO."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import sys

# 2. Third-party imports
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

# 3. Local / internal imports
from nemo import __version__
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.cli.doctor import run_doctor
from nemo.config.settings import get_settings
from nemo.database.connection import init_db, resolve_database_url
from nemo.execution.sessions.manager import SessionManager
from nemo.execution.shells.native import NativeSubprocessExecutor
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

app.add_typer(sessions_app, name="sessions")
app.add_typer(memory_app, name="memory")
app.add_typer(project_app, name="project")

console = Console()
session_mgr = SessionManager()
memory_repo = MemoryRepository()
project_repo = ProjectRepository()


@app.command()
def version() -> None:
    """Display NEMO version."""
    console.print(f"[bold cyan]NEMO[/bold cyan] version [bold green]{__version__}[/bold green]")


@app.command()
def status() -> None:
    """Display current system and environment status (fast, local only)."""
    settings = get_settings()
    has_key = bool(settings.nvidia_api_key and settings.nvidia_api_key.startswith("nvapi-"))
    db_url = resolve_database_url()
    content = (
        f"[bold]Version:[/bold] {__version__}\n"
        f"[bold]Shell:[/bold] {settings.default_shell}\n"
        f"[bold]IDE:[/bold] {settings.default_ide}\n"
        f"[bold]Workspace:[/bold] {settings.workspace_root}\n"
        f"[bold]Database:[/bold] {db_url}\n"
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
