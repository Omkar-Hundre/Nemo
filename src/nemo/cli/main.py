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
from nemo.execution.sessions.manager import SessionManager
from nemo.execution.shells.native import NativeSubprocessExecutor

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
app.add_typer(sessions_app, name="sessions")

console = Console()
session_mgr = SessionManager()


@app.command()
def version() -> None:
    """Display NEMO version."""
    console.print(f"[bold cyan]NEMO[/bold cyan] version [bold green]{__version__}[/bold green]")


@app.command()
def status() -> None:
    """Display current system and environment status (fast, local only)."""
    settings = get_settings()
    has_key = bool(settings.nvidia_api_key and settings.nvidia_api_key.startswith("nvapi-"))
    content = (
        f"[bold]Version:[/bold] {__version__}\n"
        f"[bold]Shell:[/bold] {settings.default_shell}\n"
        f"[bold]IDE:[/bold] {settings.default_ide}\n"
        f"[bold]Workspace:[/bold] {settings.workspace_root}\n"
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


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Natural language question or request."),
) -> None:
    """Ask a question to NVIDIA Nemotron and stream the response."""
    async def _stream_query():
        provider = NvidiaNimProvider()
        messages = [
            ChatMessage(
                role="system",
                content="You are NEMO, an AI-native developer operating assistant.",
            ),
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
