"""Command Line Interface entry point for NEMO."""

# 1. Standard library imports
import asyncio
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

# 2. Third-party imports
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import typer
import uvicorn

# 3. Local / internal imports
from nemo import __version__
from nemo.agent.orchestrator import AgentOrchestrator, extract_json_block
from nemo.agent.verifier import OutcomeVerifier
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.cli.doctor import run_doctor
from nemo.cli.setup import run_setup_wizard
from nemo.config.settings import get_settings
from nemo.daemon.client import DaemonClient
from nemo.daemon.server import app as daemon_fastapi_app
from nemo.database.connection import (
    backup_database,
    init_db,
    resolve_database_url,
    restore_database,
)
from nemo.execution.sessions.manager import SessionManager
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.intelligence.indexer import ProjectIndexer
from nemo.intelligence.packages import PackageManagerDetector
from nemo.integrations.ide.registry import IDERegistry
from nemo.memory.repository import ConversationRepository, MemoryRepository, ProjectRepository
from nemo.worker.service import BackgroundWorker

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
worker_app = typer.Typer(
    name="worker",
    help="Manage background maintenance and indexing worker.",
)
history_app = typer.Typer(
    name="history",
    help="Inspect, list, and manage conversation and task sessions.",
)

app.add_typer(sessions_app, name="sessions")
app.add_typer(memory_app, name="memory")
app.add_typer(project_app, name="project")
app.add_typer(index_app, name="index")
app.add_typer(ide_app, name="ide")
app.add_typer(daemon_app, name="daemon")
app.add_typer(worker_app, name="worker")
app.add_typer(history_app, name="history")

console = Console()
session_mgr = SessionManager()
memory_repo = MemoryRepository()
project_repo = ProjectRepository()
ide_registry = IDERegistry()
daemon_client = DaemonClient()
worker_service = BackgroundWorker()


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
        pid_file = Path.home() / ".nemo" / "daemon.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))
        console.print(f"[green]Daemon started in background (PID {proc.pid}) at http://127.0.0.1:{port}[/green]")
        return

    console.print(f"[bold cyan]Starting NEMO Daemon on http://127.0.0.1:{port}...[/bold cyan]")
    uvicorn.run(daemon_fastapi_app, host="127.0.0.1", port=port, log_level="info")


@daemon_app.command("stop")
def daemon_stop(
    port: int = typer.Option(8765, "--port", "-p", help="Port of daemon server."),
) -> None:
    """Stop running local background daemon server."""
    pid_file = Path.home() / ".nemo" / "daemon.pid"
    stopped = False

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            res = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            pid_file.unlink(missing_ok=True)
            if res.returncode == 0:
                stopped = True
        except Exception:
            pass

    from nemo.tools.builtin import PortManagerTool
    pm = PortManagerTool()
    owner = pm._find_port_owner(port)
    if owner:
        res = subprocess.run(["taskkill", "/PID", str(owner["pid"]), "/T", "/F"], capture_output=True)
        if res.returncode == 0:
            stopped = True

    if stopped:
        console.print("[green]Daemon stopped successfully.[/green]")
    else:
        console.print(f"[dim]No running daemon found on port {port}.[/dim]")


@daemon_app.command("autostart")
def daemon_autostart(
    enable: bool = typer.Option(False, "--enable", "-e", help="Enable automatic background daemon start at Windows logon."),
    disable: bool = typer.Option(False, "--disable", "-d", help="Disable automatic background daemon start."),
) -> None:
    """Manage automatic daemon startup at Windows logon."""
    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    script_path = startup_dir / "nemo-daemon.cmd"

    if enable:
        startup_dir.mkdir(parents=True, exist_ok=True)
        nemo_exe = shutil.which("nemo")
        if nemo_exe:
            batch_content = f'@echo off\r\nstart "" /B "{nemo_exe}" daemon start --detach\r\n'
        else:
            batch_content = f'@echo off\r\nstart "" /B "{sys.executable}" -m uvicorn nemo.daemon.server:app --port 8765 --host 127.0.0.1\r\n'

        script_path.write_text(batch_content, encoding="utf-8")
        console.print("[bold green]Auto-start ENABLED.[/bold green]")
        console.print(f"[dim]Registered startup script: {script_path}[/dim]")
        return

    if disable:
        if script_path.exists():
            script_path.unlink()
            console.print("[green]Auto-start DISABLED. Removed startup script.[/green]")
        else:
            console.print("[dim]Auto-start is already disabled.[/dim]")
        return

    if script_path.exists():
        console.print("[bold green]Auto-start is currently ENABLED.[/bold green]")
        console.print(f"[dim]Registered at: {script_path}[/dim]")
    else:
        console.print("[bold yellow]Auto-start is currently DISABLED.[/bold yellow]")
        console.print("[dim]Enable with: 'nemo daemon autostart --enable'[/dim]")


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


@memory_app.command("status")
def memory_status() -> None:
    """Display memory storage metrics and health."""
    async def _status():
        await init_db()
        items = await memory_repo.list_memories(limit=1000)
        db_url = resolve_database_url()
        global_count = sum(1 for m in items if m.scope == "global")
        project_count = sum(1 for m in items if m.scope == "project")
        console.print(Panel(
            f"[bold]Database URL:[/bold] {db_url}\n"
            f"[bold]Active Memories:[/bold] {len(items)}\n"
            f"[bold]Global Memories:[/bold] {global_count}\n"
            f"[bold]Project Memories:[/bold] {project_count}",
            title="[bold cyan]NEMO Memory Storage Status[/bold cyan]",
            border_style="cyan",
        ))
    asyncio.run(_status())


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


@memory_app.command("inspect")
def memory_inspect(
    memory_id: str = typer.Argument(..., help="Memory ID to inspect."),
) -> None:
    """Inspect full details of a specific memory record."""
    async def _inspect():
        await init_db()
        item = await memory_repo.get_memory(memory_id)
        if not item:
            items = await memory_repo.list_memories(limit=500)
            matches = [m for m in items if m.id.startswith(memory_id)]
            item = matches[0] if matches else None
        if not item:
            console.print(f"[bold red]Memory record '{memory_id}' not found.[/bold red]")
            sys.exit(1)

        console.print(Panel(
            f"[bold]ID:[/bold] {item.id}\n"
            f"[bold]Type:[/bold] {item.type}\n"
            f"[bold]Scope:[/bold] {item.scope}\n"
            f"[bold]Status:[/bold] {item.status}\n"
            f"[bold]Importance:[/bold] {item.importance}\n"
            f"[bold]Confidence:[/bold] {item.confidence}\n"
            f"[bold]Project ID:[/bold] {item.project_id or 'None'}\n"
            f"[bold]Subject:[/bold] {item.subject or '-'}\n"
            f"[bold]Created At:[/bold] {item.created_at}\n"
            f"[bold]Metadata:[/bold] {item.metadata_}\n\n"
            f"[bold]Content:[/bold]\n{item.content}",
            title=f"[bold cyan]Memory Record ({item.id[:8]})[/bold cyan]",
            border_style="cyan",
        ))
    asyncio.run(_inspect())


@memory_app.command("forget")
def memory_forget(
    memory_id: str = typer.Argument(..., help="Memory ID to forget/archive."),
) -> None:
    """Archive a memory record so it is no longer retrieved."""
    async def _forget():
        await init_db()
        target_id = memory_id
        item = await memory_repo.get_memory(memory_id)
        if not item:
            items = await memory_repo.list_memories(limit=500)
            matches = [m for m in items if m.id.startswith(memory_id)]
            if matches:
                target_id = matches[0].id
        deleted = await memory_repo.delete_memory(target_id)
        if deleted:
            console.print(f"[green]Memory [bold]{target_id[:8]}[/bold] archived successfully.[/green]")
        else:
            console.print(f"[bold red]Memory record '{memory_id}' not found.[/bold red]")
            sys.exit(1)
    asyncio.run(_forget())


@memory_app.command("backup")
def memory_backup(
    destination: str | None = typer.Option(None, "--dest", "-d", help="Target backup file path."),
) -> None:
    """Create atomic backup snapshot of memory and project database."""
    try:
        backup_path = backup_database(destination)
        console.print(f"[bold green]Database successfully backed up to:[/bold green] {backup_path}")
    except Exception as exc:
        console.print(f"[bold red]Backup failed: {exc}[/bold red]")
        sys.exit(1)


@memory_app.command("restore")
def memory_restore(
    source: str = typer.Argument(..., help="Source database backup file to restore from."),
) -> None:
    """Restore memory and project database from a backup file."""
    try:
        restored_path = restore_database(source)
        console.print(f"[bold green]Database successfully restored to:[/bold green] {restored_path}")
    except Exception as exc:
        console.print(f"[bold red]Restore failed: {exc}[/bold red]")
        sys.exit(1)


@memory_app.command("export")
def memory_export(
    output: str | None = typer.Option(None, "--out", "-o", help="File to write exported JSON memories to."),
) -> None:
    """Export all active memories to JSON format."""
    async def _export():
        import json
        await init_db()
        items = await memory_repo.list_memories(limit=5000)
        export_data = [
            {
                "id": m.id,
                "scope": m.scope,
                "project_id": m.project_id,
                "type": m.type,
                "subject": m.subject,
                "predicate": m.predicate,
                "object": m.object,
                "content": m.content,
                "importance": m.importance,
                "confidence": m.confidence,
                "status": m.status,
                "metadata": m.metadata_,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in items
        ]
        payload = json.dumps(export_data, indent=2)
        if output:
            p = Path(output).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload, encoding="utf-8")
            console.print(f"[green]Exported {len(export_data)} memories to {p}[/green]")
        else:
            console.print(payload)
    asyncio.run(_export())


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


# --- Worker Commands ---
@worker_app.command("run")
def worker_run(
    once: bool = typer.Option(False, "--once", "-1", help="Run single maintenance pass (indexing, graph sync, memory consolidation) and exit."),
) -> None:
    """Run background maintenance worker for codebase indexing and memory consolidation."""
    async def _run():
        if once:
            console.print("[bold cyan]Running one-shot maintenance pass...[/bold cyan]")
            worker = BackgroundWorker()
            job1 = worker.enqueue("indexing", {"path": Path.cwd(), "force": False})
            job2 = worker.enqueue("graph_sync", {"project_name": Path.cwd().name, "path": Path.cwd()})
            job3 = worker.enqueue("memory_consolidation", {})
            worker.start()

            for _ in range(40):
                await asyncio.sleep(0.5)
                if all(j.status in ("completed", "failed") for j in [job1, job2, job3]):
                    break
            await worker.stop()

            table = Table(title="Maintenance Pass Summary", border_style="cyan")
            table.add_column("Task", style="bold cyan", width=24)
            table.add_column("Status", width=12)
            table.add_column("Result", style="white")

            for j in [job1, job2, job3]:
                status_color = "green" if j.status == "completed" else "red"
                table.add_row(j.name, f"[{status_color}]{j.status.upper()}[/{status_color}]", str(j.result or j.error))

            console.print(table)
        else:
            console.print("[bold cyan]Starting continuous background worker (Press Ctrl+C to stop)...[/bold cyan]")
            worker = BackgroundWorker()
            worker.start()
            try:
                while True:
                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                await worker.stop()
                console.print("[green]Worker stopped.[/green]")

    asyncio.run(_run())


@worker_app.command("index")
def worker_index(
    path: str = typer.Option(".", "--path", "-p", help="Directory path to index."),
    force: bool = typer.Option(False, "--force", "-f", help="Force full re-index."),
) -> None:
    """Trigger background indexing task."""
    async def _index():
        from nemo.worker.tasks import task_run_indexing
        with console.status("[bold cyan]Running indexing task..."):
            report = await task_run_indexing(workspace_path=path, force=force)
        console.print(f"[green]Indexed {report.indexed_files} files ({report.total_files} total) in {report.duration_ms}ms[/green]")

    asyncio.run(_index())


@worker_app.command("consolidate")
def worker_consolidate(
    project_id: str | None = typer.Option(None, "--project-id", help="Optional project ID scope."),
) -> None:
    """Run memory consolidation and deduplication pass."""
    async def _consolidate():
        from nemo.worker.tasks import task_consolidate_memories
        with console.status("[bold cyan]Consolidating and deduplicating memories..."):
            res = await task_consolidate_memories(project_id=project_id)
        console.print(f"[green]Checked {res['total_checked']} memories; archived {res['duplicates_archived']} duplicates.[/green]")

    asyncio.run(_consolidate())


# --- Conversation & History Commands ---
@history_app.command("list")
def history_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum conversation sessions to list."),
) -> None:
    """List recent conversation sessions and autonomous task history."""
    async def _list():
        await init_db()
        from nemo.cli.chat import format_relative_time
        repo = ConversationRepository()
        convs = await repo.list_conversations(limit=limit)
        if not convs:
            console.print("[dim]No conversation history found.[/dim]")
            return

        table = Table(title="Conversation & Task History", border_style="cyan")
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Session ID", style="bold cyan", width=12)
        table.add_column("Title / Objective", style="white")
        table.add_column("Activity", style="dim", width=12)
        table.add_column("Messages", justify="right", width=10)

        for i, c in enumerate(convs):
            rel_time = format_relative_time(c.created_at)
            msg_count = str(len(c.messages)) if c.messages else "0"
            table.add_row(str(i + 1), c.id[:8], c.title, rel_time, msg_count)

        console.print(table)
        console.print("[dim]Use 1-based numbers: 'nemo resume 2' or 'nemo history show 2'[/dim]")

    asyncio.run(_list())


@history_app.command("show")
def history_show(
    conversation_id: str = typer.Argument(..., help="Conversation ID, 1-based number (#), or title keyword."),
) -> None:
    """Show transcript of a conversation session."""
    async def _show():
        await init_db()
        repo = ConversationRepository()
        convs = await repo.list_conversations(limit=100)
        c = None

        if conversation_id.isdigit():
            idx = int(conversation_id) - 1
            if 0 <= idx < len(convs):
                c = convs[idx]
        if not c:
            matched = [cv for cv in convs if cv.id.startswith(conversation_id) or conversation_id.lower() in cv.title.lower()]
            if matched:
                c = matched[0]

        if not c:
            console.print(f"[red]No conversation found matching '{conversation_id}'[/red]")
            return

        console.print(Panel(f"[bold cyan]Session:[/bold cyan] {c.title}\n[dim]ID: {c.id} | Created: {c.created_at}[/dim]", border_style="cyan"))

        messages = await repo.get_messages(c.id, limit=100)
        for msg in messages:
            role_style = "bold green" if msg.role == "user" else "bold blue"
            console.print(f"[{role_style}]{msg.role.upper()}:[/{role_style}]")
            console.print(msg.content)
            console.print("[dim]" + "─" * 40 + "[/dim]")

    asyncio.run(_show())


@history_app.command("delete")
def history_delete(
    conversation_id: str = typer.Argument(..., help="Conversation ID or 1-based number (#) to delete."),
) -> None:
    """Delete a conversation session and all its messages."""
    async def _del():
        await init_db()
        repo = ConversationRepository()
        convs = await repo.list_conversations(limit=100)
        c = None

        if conversation_id.isdigit():
            idx = int(conversation_id) - 1
            if 0 <= idx < len(convs):
                c = convs[idx]
        if not c:
            matched = [cv for cv in convs if cv.id.startswith(conversation_id)]
            if matched:
                c = matched[0]

        if not c:
            console.print(f"[red]No conversation found matching '{conversation_id}'[/red]")
            return
        deleted = await repo.delete_conversation(c.id)
        if deleted:
            console.print(f"[green]Deleted conversation {c.id[:8]} ({c.title})[/green]")
        else:
            console.print(f"[red]Failed to delete conversation.[/red]")

    asyncio.run(_del())


@app.command("resume")
def resume(
    conversation_id: str | None = typer.Argument(None, help="Optional conversation ID, 1-based number (#), or title keyword to resume."),
) -> None:
    """Resume interactive chat session with context and memory from a previous conversation."""
    from nemo.cli.chat import run_interactive_chat
    async def _resume():
        await init_db()
        repo = ConversationRepository()
        convs = await repo.list_conversations(limit=100)
        selected_id = None

        if conversation_id:
            if conversation_id.isdigit():
                idx = int(conversation_id) - 1
                if 0 <= idx < len(convs):
                    selected_id = convs[idx].id
                else:
                    console.print(f"[red]Invalid session number #{conversation_id}. Available: 1 to {len(convs)}[/red]")
                    return
            else:
                matches = [c for c in convs if conversation_id.lower() in c.title.lower()]
                if matches:
                    selected_id = matches[0].id
                else:
                    id_matches = [c for c in convs if c.id.startswith(conversation_id)]
                    if id_matches:
                        selected_id = id_matches[0].id
                    else:
                        console.print(f"[red]No conversation found matching '{conversation_id}'[/red]")
                        return

        await run_interactive_chat(initial_conversation_id=selected_id)

    asyncio.run(_resume())


# --- Autonomous Agent Commands ---
@app.command()
def task(
    objective: str = typer.Argument(..., help="High-level objective for autonomous agent."),
    max_steps: int = typer.Option(15, "--max-steps", "-m", help="Maximum execution steps."),
    conversation_id: str | None = typer.Option(None, "--conversation-id", "-c", help="Optional conversation ID to resume."),
) -> None:
    """Run autonomous multi-step agent workflow with tool execution and ground-truth verification."""
    async def _run_agent():
        await init_db()
        orchestrator = AgentOrchestrator()
        console.print(f"[bold cyan]Starting task:[/bold cyan] {objective}")

        with console.status("[bold green]Deliberating, executing, and verifying..."):
            state = await orchestrator.run(
                objective=objective,
                max_iterations=max_steps,
                conversation_id=conversation_id,
            )

        console.print("\n[bold]Execution Steps:[/bold]")
        for record in state.tool_history:
            status_icon = "[green]✓[/green]" if record["success"] else "[red]✗[/red]"
            thought_text = f" | [italic dim]{record['thought'][:60]}...[/italic dim]" if record.get("thought") else ""
            console.print(f" {status_icon} [bold cyan]{record['tool']}[/bold cyan] [dim]{record['arguments']}[/dim]{thought_text}")

        if state.verification_results:
            console.print("\n[bold]Verification Gate Results:[/bold]")
            for v in state.verification_results:
                v_icon = "[green]✓[/green]" if v["verified"] else "[red]✗[/red]"
                console.print(f" {v_icon} [{v['ground_truth_source']}] {v['details']}")

        ans = state.final_answer or "Completed."
        parsed = extract_json_block(ans)
        if parsed and parsed.get("action") == "finish" and "answer" in parsed:
            ans = parsed["answer"]
        console.print("\n[bold]Final Outcome:[/bold]\n")
        console.print(Markdown(ans))

        if state.extracted_memories:
            console.print("\n[bold cyan]🧠 Auto-Learned Project Knowledge Added to Memory:[/bold cyan]")
            for m in state.extracted_memories:
                console.print(f" • [green]{m['content']}[/green] [dim]({m['type']})[/dim]")

    asyncio.run(_run_agent())


@app.command("dependencies")
def dependencies(
    path: str = typer.Option(".", "--path", "-p", help="Directory to inspect for project dependencies."),
) -> None:
    """Inspect detected project manifests, lockfiles, package managers, and validation scripts."""
    target_path = Path(path).resolve()
    ecosystems = PackageManagerDetector.detect(target_path)
    if not ecosystems:
        console.print(f"[dim]No supported package manifests detected in {target_path}[/dim]")
        return

    table = Table(title=f"Detected Project Dependencies & Ecosystems ({target_path.name})", border_style="cyan")
    table.add_column("Ecosystem", style="bold cyan", width=12)
    table.add_column("Manifest File", style="green", width=18)
    table.add_column("Lock File", style="yellow", width=18)
    table.add_column("Package Manager", width=16)
    table.add_column("Validation Command", style="dim white")

    for eco in ecosystems:
        table.add_row(
            eco.ecosystem.capitalize(),
            eco.manifest_file,
            eco.lock_file or "-",
            eco.package_manager,
            eco.validate_command,
        )

    console.print(table)


@app.command("verify")
def verify(
    file: str | None = typer.Option(None, "--file", "-f", help="Specific file path to verify exists and passes syntax validation."),
    test: bool = typer.Option(False, "--test", "-t", help="Run project validation / test suite to verify no regressions."),
) -> None:
    """Run ground-truth outcome verification against OS, filesystem, and AST syntax."""
    async def _run_verify():
        verifier = OutcomeVerifier()
        if file:
            res = await verifier.verify_file_created_or_modified(file)
            status_style = "bold green" if res.verified else "bold red"
            status_text = "VERIFIED" if res.verified else "FAILED"
            console.print(f"[{status_style}][{status_text}][/{status_style}] [{res.ground_truth_source}] {res.details}")
            if not res.verified:
                sys.exit(1)

        if test or not file:
            with console.status("[bold cyan]Running ground-truth test suite verification..."):
                t_res = await verifier.verify_test_suite_passes()
            status_style = "bold green" if t_res.verified else "bold red"
            status_text = "VERIFIED" if t_res.verified else "FAILED"
            console.print(f"[{status_style}][{status_text}][/{status_style}] [{t_res.ground_truth_source}] {t_res.details}")
            if not t_res.verified:
                if t_res.diagnostics.get("stderr_tail"):
                    console.print(f"[red]{t_res.diagnostics['stderr_tail']}[/red]")
                sys.exit(1)

    asyncio.run(_run_verify())


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


@app.command()
def speak(
    text: str = typer.Argument(..., help="Text message to speak aloud using Microsoft Neural Voice."),
    voice: str = typer.Option("jenny", "--voice", "-v", help="Persona alias ('jenny', 'guy', 'aria', 'prabhat', 'neerja')."),
    rate: str = typer.Option("+15%", "--rate", "-r", help="Speaking speed rate (e.g. '+15%', '+0%')."),
    save: str | None = typer.Option(None, "--save", "-s", help="Save synthesized MP3 to specified file path."),
    play: bool = typer.Option(True, "--play/--no-play", help="Play audio immediately through system speakers."),
) -> None:
    """Speak text aloud using Microsoft Natural Neural Voices with human intonation and emotion."""
    async def _speak():
        from nemo.voice.speaker import VoiceSpeaker
        speaker = VoiceSpeaker(default_voice=voice, default_rate=rate)
        resolved_voice = speaker.resolve_voice(voice)
        console.print(f"[bold cyan]Synthesizing ({resolved_voice} @ {rate}):[/bold cyan] {text}")

        if save:
            out_path = Path(save).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            saved = await speaker.generate_speech(text, voice=resolved_voice, rate=rate, output_file=out_path)
            console.print(f"[green]Audio saved to: {saved} ({saved.stat().st_size} bytes)[/green]")
            if play and platform.system() == "Windows":
                speaker.play_audio(saved, wait=True)
        else:
            played = await speaker.speak(text, voice=resolved_voice, rate=rate, wait=True)
            if played:
                console.print("[green]Playback completed.[/green]")
            else:
                console.print("[yellow]Audio synthesized (playback skipped or audio device busy).[/yellow]")

    asyncio.run(_speak())


# 6. Public exports
__all__ = ["app", "main"]


def main() -> None:
    """CLI entrypoint with automatic natural language prompt routing."""
    known_commands = {
        "chat", "setup", "version", "status", "doctor", "run", "daemon",
        "sessions", "memory", "project", "index", "ide", "worker", "task",
        "history", "resume", "speak",
        "dependencies", "verify", "diagnose", "ask", "remember",
        "--help", "-h", "--version", "-v",
    }
    if len(sys.argv) > 1 and sys.argv[1] not in known_commands and not sys.argv[1].startswith("-"):
        prompt_text = " ".join(sys.argv[1:])
        sys.argv = [sys.argv[0], "task", prompt_text]
    app()


if __name__ == "__main__":
    main()
