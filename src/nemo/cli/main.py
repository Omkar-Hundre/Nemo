"""Command Line Interface entry point for NEMO."""

# 1. Standard library imports
import asyncio
import sys

# 2. Third-party imports
from rich.console import Console
from rich.panel import Panel
import typer

# 3. Local / internal imports
from nemo import __version__
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.cli.doctor import run_doctor
from nemo.config.settings import get_settings
from nemo.execution.shells.native import NativeSubprocessExecutor

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
app = typer.Typer(
    name="nemo",
    help="AI-Native Developer Operating Environment for Windows.",
    add_completion=False,
)
console = Console()


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
    timeout: float = typer.Option(600.0, "--timeout", help="Timeout in seconds."),
) -> None:
    """Execute a native command via subprocess and display exit code and output."""
    executor = NativeSubprocessExecutor(default_shell=shell)
    result = asyncio.run(executor.execute(command, timeout_seconds=timeout))

    if result.stdout:
        console.print(result.stdout, end="")
    if result.stderr:
        console.print(f"[red]{result.stderr}[/red]", end="")

    if not result.is_success:
        console.print(f"[bold red]Exit code: {result.exit_code}[/bold red]")
        sys.exit(result.exit_code)


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
