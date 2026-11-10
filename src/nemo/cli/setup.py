"""Setup wizard for configuring credentials, databases, and IDE integrations."""

# 1. Standard library imports
import asyncio
from pathlib import Path

# 2. Third-party imports
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# 3. Local / internal imports
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.cli.doctor import check_ide, check_python, check_shell
from nemo.config.settings import get_settings
from nemo.database.connection import init_db
from nemo.intelligence.indexer import ProjectIndexer
from nemo.memory.repository import ProjectRepository

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
console = Console()


async def run_setup_wizard(custom_key: str | None = None) -> bool:
    """Execute complete initial setup and dependency verification."""
    console.print(Panel(
        "[bold cyan]NEMO Setup Wizard[/bold cyan]\n"
        "[dim]Initializing AI-Native Operating Environment for Windows[/dim]",
        border_style="cyan"
    ))

    table = Table(title="Setup Steps", border_style="bright_blue")
    table.add_column("Step", style="bold white", width=25)
    table.add_column("Status", width=12)
    table.add_column("Details", style="dim white")

    # 1. Python check
    py_ok, py_det = check_python()
    table.add_row("1. Python Runtime", "[green]OK[/green]" if py_ok else "[red]FAIL[/red]", py_det)

    # 2. Shell check
    sh_ok, sh_det = check_shell()
    table.add_row("2. Windows Shell", "[green]OK[/green]" if sh_ok else "[yellow]WARN[/yellow]", sh_det)

    # 3. IDE check
    ide_ok, ide_det = check_ide()
    table.add_row("3. Editor Discovery", "[green]OK[/green]" if ide_ok else "[yellow]WARN[/yellow]", ide_det)

    # 4. Credentials
    settings = get_settings()
    key = custom_key or settings.nvidia_api_key
    if custom_key:
        env_file = Path(".env")
        env_file.write_text(f"NVIDIA_API_KEY={custom_key}\n", encoding="utf-8")
        settings.nvidia_api_key = custom_key

    has_key = bool(key and key.startswith("nvapi-"))
    table.add_row("4. NVIDIA NIM Key", "[green]OK[/green]" if has_key else "[red]MISSING[/red]", "Loaded from .env" if has_key else "Not set")

    # 5. API Live Ping
    api_ok = False
    api_det = "Skipped"
    if has_key:
        try:
            prov = NvidiaNimProvider(api_key=key)
            resp = await prov.generate([ChatMessage(role="user", content="Ping. Answer 'OK'.")], max_tokens=10, enable_thinking=False)
            api_ok = True
            api_det = f"Connected to {resp.model}"
        except Exception as exc:
            api_det = f"Error: {exc}"
    table.add_row("5. Model Inference", "[green]OK[/green]" if api_ok else "[red]FAIL[/red]", api_det)

    # 6. Database Init
    try:
        await init_db()
        db_ok = True
        db_det = "SQLite / PostgreSQL initialized"
    except Exception as exc:
        db_ok = False
        db_det = str(exc)
    table.add_row("6. Database Persistence", "[green]OK[/green]" if db_ok else "[red]FAIL[/red]", db_det)

    # 7. Project Registration & Initial Index
    try:
        proj_repo = ProjectRepository()
        curr_dir = Path.cwd()
        proj = await proj_repo.register_project(name=curr_dir.name, root_path=curr_dir)
        indexer = ProjectIndexer(curr_dir)
        report = indexer.run_index()
        idx_ok = True
        idx_det = f"Registered '{proj.name}', {report.total_files} files indexed"
    except Exception as exc:
        idx_ok = False
        idx_det = str(exc)
    table.add_row("7. Workspace Index", "[green]OK[/green]" if idx_ok else "[red]FAIL[/red]", idx_det)

    console.print(table)

    all_passed = py_ok and has_key and api_ok and db_ok and idx_ok
    if all_passed:
        console.print(Panel(
            "[bold green]NEMO Environment Ready![/bold green]\n"
            "You can now run commands like:\n"
            " • [cyan]nemo status[/cyan]\n"
            " • [cyan]nemo ask \"How is this project structured?\"[/cyan]\n"
            " • [cyan]nemo task \"Analyze codebase dependencies\"[/cyan]",
            border_style="green"
        ))
    else:
        console.print("[bold yellow]Setup finished with warnings. Review table above.[/bold yellow]")

    return all_passed

# 6. Public exports
__all__ = ["run_setup_wizard"]
