"""System health and diagnostic checks."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import shutil
import sys

# 2. Third-party imports
from rich.console import Console
from rich.table import Table

# 3. Local / internal imports
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.config.settings import get_settings

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
console = Console()


def check_python() -> tuple[bool, str]:
    """Verify running Python version."""
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if v.major >= 3 and v.minor >= 11:
        return True, f"Python {ver_str}"
    return False, f"Python {ver_str} (requires >= 3.11)"


def check_shell() -> tuple[bool, str]:
    """Check availability of PowerShell."""
    pwsh = shutil.which("pwsh.exe")
    powershell = shutil.which("powershell.exe")
    if pwsh:
        return True, f"PowerShell 7 ({pwsh})"
    if powershell:
        return True, f"Windows PowerShell ({powershell})"
    return False, "PowerShell not found in PATH"


def check_ide() -> tuple[bool, str]:
    """Detect Antigravity or VS Code installations."""
    detected = []
    # Check VS Code
    if shutil.which("code.cmd") or shutil.which("code"):
        detected.append("VS Code")
    # Check Antigravity in standard Windows local/app data paths
    local_app_data = Path.home() / "AppData" / "Local" / "Programs" / "Antigravity"
    if local_app_data.exists() or shutil.which("antigravity"):
        detected.append("Antigravity")

    if detected:
        return True, ", ".join(detected)
    return False, "No recognized IDE found in standard locations"


def check_nvidia_key() -> tuple[bool, str]:
    """Verify NVIDIA API key is loaded."""
    settings = get_settings()
    if settings.nvidia_api_key and settings.nvidia_api_key.startswith("nvapi-"):
        # Redact for terminal display
        redacted = f"{settings.nvidia_api_key[:10]}...{settings.nvidia_api_key[-4:]}"
        return True, f"Configured ({redacted})"
    return False, "Missing or invalid NVIDIA_API_KEY in .env"


async def check_nvidia_connectivity() -> tuple[bool, str]:
    """Send minimal test prompt to NVIDIA NIM endpoint."""
    settings = get_settings()
    if not settings.nvidia_api_key:
        return False, "Skipped (no API key)"

    try:
        provider = NvidiaNimProvider()
        test_msg = [ChatMessage(role="user", content="Ping. Reply with 'pong'.")]
        resp = await provider.generate(test_msg, max_tokens=10, enable_thinking=False)
        return True, f"Connected to {resp.model} (Tokens: {resp.usage.get('total_tokens', 0)})"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def run_doctor(test_api: bool = False) -> None:
    """Run all diagnostic checks and render status table."""
    table = Table(title="NEMO System Diagnostics", border_style="bright_blue")
    table.add_column("Component", style="bold white", width=22)
    table.add_column("Status", width=10)
    table.add_column("Details", style="dim white")

    # 1. Python check
    ok, details = check_python()
    table.add_row("Python Runtime", "[green]PASS[/green]" if ok else "[red]FAIL[/red]", details)

    # 2. Shell check
    ok, details = check_shell()
    table.add_row("Default Shell", "[green]PASS[/green]" if ok else "[yellow]WARN[/yellow]", details)

    # 3. IDE check
    ok, details = check_ide()
    table.add_row("IDE Environment", "[green]PASS[/green]" if ok else "[yellow]WARN[/yellow]", details)

    # 4. Key check
    ok, details = check_nvidia_key()
    table.add_row("NVIDIA NIM Key", "[green]PASS[/green]" if ok else "[red]FAIL[/red]", details)

    # 5. Live API test (if requested)
    if test_api and ok:
        with console.status("[bold cyan]Testing NVIDIA NIM connection..."):
            api_ok, api_details = asyncio.run(check_nvidia_connectivity())
        table.add_row(
            "NVIDIA API Ping",
            "[green]PASS[/green]" if api_ok else "[red]FAIL[/red]",
            api_details
        )

    console.print(table)

# 6. Public exports
__all__ = ["run_doctor", "check_python", "check_shell", "check_ide", "check_nvidia_key", "check_nvidia_connectivity"]
