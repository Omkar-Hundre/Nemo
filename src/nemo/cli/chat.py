"""Interactive developer REPL with deterministic command routing and AI streaming."""

# 1. Standard library imports
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

# 2. Third-party imports
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

# 3. Local / internal imports
from nemo import __version__
from nemo.agent.orchestrator import AgentOrchestrator, extract_json_block
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.config.settings import get_settings
from nemo.database.connection import init_db
from nemo.database.models import Conversation
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.intelligence.indexer import ProjectIndexer
from nemo.memory.repository import ConversationRepository, MemoryRepository, ProjectRepository

# 4. Types, Protocols, Schemas
KNOWN_NATIVE_PREFIXES = (
    "git", "gh", "netlify", "ntl", "vercel", "dir", "ls", "cd", "python", "py", "node", "npm",
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


def format_relative_time(dt: datetime | None) -> str:
    """Format datetime into human-friendly relative duration (e.g. '5m ago', '2h ago')."""
    if not dt:
        return "recently"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    total_seconds = max(0, int(diff.total_seconds()))
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m ago"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h ago"
    return f"{total_seconds // 86400}d ago"


def interactive_session_picker(
    conversations: list[Conversation],
    active_id: str | None = None,
) -> str | None:
    """Interactive Up/Down arrow key menu to select, resume, or start a session.

    Returns:
        - conversation_id string if a session was picked
        - "NEW" if user selected fresh session
        - None if user cancelled (Esc or q)
    """
    if not conversations:
        return None

    if not sys.stdin.isatty():
        return None

    try:
        import msvcrt
    except ImportError:
        return None

    items = []
    for c in conversations:
        rel_time = format_relative_time(c.created_at)
        msg_count = len(c.messages) if c.messages else 0
        is_active = (c.id == active_id)
        items.append((c.id, c.title, rel_time, msg_count, is_active))

    items.append(("NEW", "+ Start a New Clean Session", "", 0, active_id is None))

    current_idx = 0
    for i, item in enumerate(items):
        if item[4]:
            current_idx = i
            break

    total = len(items)

    def render_menu(idx: int):
        tbl = Table(
            title="[bold cyan]NEMO Session Selector[/bold cyan] [dim](↑/↓ navigate, Enter select, 1-9 jump, Esc cancel)[/dim]",
            border_style="cyan",
            show_header=True,
            header_style="bold cyan",
        )
        tbl.add_column("#", width=5, justify="right")
        tbl.add_column("Status", width=10, justify="center")
        tbl.add_column("Session Title / Objective", style="white")
        tbl.add_column("Activity", style="dim", width=12)
        tbl.add_column("Messages", justify="right", width=10)

        for i, (cid, title, rel_time, msg_count, is_act) in enumerate(items):
            act_badge = "[green]● ACTIVE[/green]" if is_act else "[dim]○[/dim]"
            msg_str = f"{msg_count} msgs" if cid != "NEW" else "-"

            if i == idx:
                tbl.add_row(
                    f"[bold yellow]❯ {i+1}[/bold yellow]",
                    f"[bold yellow]{act_badge}[/bold yellow]",
                    f"[bold yellow]{title}[/bold yellow]",
                    f"[bold yellow]{rel_time}[/bold yellow]",
                    f"[bold yellow]{msg_str}[/bold yellow]",
                    style="on grey23",
                )
            else:
                tbl.add_row(
                    f"  {i+1}",
                    act_badge,
                    title,
                    rel_time,
                    msg_str,
                )
        return tbl

    try:
        with Live(render_menu(current_idx), console=console, auto_refresh=False, transient=True) as live:
            while True:
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    arrow = msvcrt.getch()
                    if arrow == b'H':  # Up arrow
                        current_idx = (current_idx - 1) % total
                        live.update(render_menu(current_idx), refresh=True)
                    elif arrow == b'P':  # Down arrow
                        current_idx = (current_idx + 1) % total
                        live.update(render_menu(current_idx), refresh=True)
                elif ch in (b'\r', b'\n'):  # Enter
                    return items[current_idx][0]
                elif ch in (b'\x1b', b'q', b'Q'):  # Esc or q
                    return None
                elif ch.isdigit():
                    d = int(ch.decode("ascii"))
                    if 1 <= d <= total:
                        current_idx = d - 1
                        live.update(render_menu(current_idx), refresh=True)
    except Exception:
        return None


async def run_interactive_chat(initial_conversation_id: str | None = None) -> None:
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

    conv_repo = ConversationRepository()
    active_conversation_id = initial_conversation_id

    # Render Welcome Banner
    banner = (
        f"[bold cyan]NEMO ASSISTANT[/bold cyan] [green]● Connected[/green]\n\n"
        f"[bold]Active Project:[/bold]  {project_name} [dim]({curr_dir})[/dim]\n"
        f"[bold]IDE Adapter:[/bold]     {settings.default_ide}\n"
        f"[bold]Memory System:[/bold]   Synchronized\n"
        f"[bold]Code Index:[/bold]      {indexed_files} files up to date\n\n"
        f"[dim]Usability: 'resume' (↑/↓ arrow menu or 'resume 2'), 'history', 'rename', 'fork', 'export', 'new'[/dim]"
    )
    console.print(Panel(banner, title=f"[bold]NEMO v{__version__} — Developer Runtime[/bold]", border_style="cyan"))

    if active_conversation_id:
        conv = await conv_repo.get_conversation(active_conversation_id)
        if conv:
            console.print(f"[bold green]Resumed Session:[/bold green] [cyan]{conv.title}[/cyan] [dim]({conv.id[:8]})[/dim]")
            recent_msgs = await conv_repo.get_messages(conv.id, limit=4)
            for m in recent_msgs:
                console.print(f" [dim]{m.role.capitalize()}: {m.content[:75]}...[/dim]")
            console.print()

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
            # Dynamic prompt showing active task title instead of cryptic UUID
            active_label = ""
            if active_conversation_id:
                all_convs = await conv_repo.list_conversations(limit=50)
                matched = [c for c in all_convs if c.id == active_conversation_id]
                if matched:
                    c_title = matched[0].title
                    snippet = (c_title[:16] + "..") if len(c_title) > 18 else c_title
                    active_label = f" [{snippet}]"
                else:
                    active_label = f" [{active_conversation_id[:6]}]"

            prompt_label = f"nemo{active_label}> "

            if prompt_session is not None and sys.stdin.isatty():
                user_input = (await prompt_session.prompt_async(prompt_label)).strip()
            else:
                user_input = console.input(f"[bold cyan]{prompt_label}[/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session closed.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        # 1. Resume command: interactive arrow-key selector or direct lookup (number, keyword, ID)
        if user_input.lower() == "resume" or user_input.lower().startswith("resume "):
            arg = user_input[6:].strip() if len(user_input) > 6 else ""
            all_convs = await conv_repo.list_conversations(limit=50)

            if not all_convs and not arg:
                console.print("[dim]No previous sessions found in database.[/dim]\n")
                continue

            selected_conv = None
            if not arg:
                # Up/Down Arrow Interactive Selector
                picked_id = interactive_session_picker(all_convs, active_conversation_id)
                if picked_id == "NEW":
                    active_conversation_id = None
                    console.print("[cyan]Started fresh conversation session with clean context.[/cyan]\n")
                    continue
                elif picked_id:
                    matched = [c for c in all_convs if c.id == picked_id]
                    if matched:
                        selected_conv = matched[0]
                else:
                    # User cancelled with Esc
                    continue
            else:
                # Human-friendly: 1-based number (e.g. 'resume 2')
                if arg.isdigit():
                    num = int(arg)
                    if 1 <= num <= len(all_convs):
                        selected_conv = all_convs[num - 1]
                    else:
                        console.print(f"[red]Invalid session number #{num}. Available: 1 to {len(all_convs)}[/red]\n")
                        continue
                else:
                    # Title keyword search (e.g. 'resume refactor')
                    title_matches = [c for c in all_convs if arg.lower() in c.title.lower()]
                    if title_matches:
                        selected_conv = title_matches[0]
                    else:
                        # UUID prefix match
                        id_matches = [c for c in all_convs if c.id.startswith(arg)]
                        if id_matches:
                            selected_conv = id_matches[0]

            if selected_conv:
                active_conversation_id = selected_conv.id
                console.print(f"[bold green]Resumed Session:[/bold green] [cyan]{selected_conv.title}[/cyan] [dim]({selected_conv.id[:8]})[/dim]")
                msgs = await conv_repo.get_messages(selected_conv.id, limit=3)
                if msgs:
                    console.print("[dim]Recent context:[/dim]")
                    for m in msgs:
                        console.print(f" [dim]{m.role.capitalize()}: {m.content[:75]}...[/dim]")
                console.print()
            else:
                console.print(f"[red]No conversation found matching '{arg}'[/red]\n")
            continue

        # 2. History & Sessions inspection: interactive arrow menu or styled table
        if user_input.lower() in ("history", "sessions", "tasks"):
            all_convs = await conv_repo.list_conversations(limit=25)
            if not all_convs:
                console.print("[dim]No previous sessions found in database.[/dim]\n")
                continue

            picked_id = interactive_session_picker(all_convs, active_conversation_id)
            if picked_id == "NEW":
                active_conversation_id = None
                console.print("[cyan]Started fresh conversation session with clean context.[/cyan]\n")
                continue
            elif picked_id:
                matched = [c for c in all_convs if c.id == picked_id]
                if matched:
                    active_conversation_id = matched[0].id
                    console.print(f"[bold green]Switched to Session:[/bold green] [cyan]{matched[0].title}[/cyan] [dim]({matched[0].id[:8]})[/dim]")
                    msgs = await conv_repo.get_messages(matched[0].id, limit=3)
                    if msgs:
                        console.print("[dim]Recent context:[/dim]")
                        for m in msgs:
                            console.print(f" [dim]{m.role.capitalize()}: {m.content[:75]}...[/dim]")
                    console.print()
                continue
            else:
                # If cancelled with Esc, render overview table
                tbl = Table(title="Conversation & Task History", border_style="cyan")
                tbl.add_column("#", width=4, justify="right")
                tbl.add_column("Status", width=10, justify="center")
                tbl.add_column("Title / Objective", style="white")
                tbl.add_column("Activity", style="dim", width=12)
                tbl.add_column("Messages", justify="right", width=10)
                for i, c in enumerate(all_convs):
                    is_active = "[green]● ACTIVE[/green]" if c.id == active_conversation_id else "[dim]○[/dim]"
                    rel_time = format_relative_time(c.created_at)
                    msg_count = str(len(c.messages)) if c.messages else "0"
                    tbl.add_row(str(i + 1), is_active, c.title, rel_time, msg_count)
                console.print(tbl)
                console.print("[dim]Use 'resume <# or title>' to switch, 'rename <title>' to rename, 'fork' to branch, 'export' to save transcript.[/dim]\n")
                continue

        # 3. Rename session
        if user_input.lower().startswith("rename "):
            raw_arg = user_input[7:].strip()
            parts = raw_arg.split(maxsplit=1)
            all_convs = await conv_repo.list_conversations(limit=50)
            target_id = active_conversation_id
            new_title = raw_arg

            if len(parts) == 2 and parts[0].isdigit():
                idx = int(parts[0]) - 1
                if 0 <= idx < len(all_convs):
                    target_id = all_convs[idx].id
                    new_title = parts[1]

            if target_id:
                await conv_repo.update_title(target_id, new_title)
                console.print(f"[green]Session title updated to:[/green] [bold cyan]{new_title}[/bold cyan]\n")
            else:
                console.print("[yellow]No active session to rename. Use 'rename <#> <new title>'[/yellow]\n")
            continue

        # 4. Fork / Branch session
        if user_input.lower() == "fork" or user_input.lower().startswith("fork "):
            arg = user_input[5:].strip() if len(user_input) > 5 else ""
            all_convs = await conv_repo.list_conversations(limit=50)
            target_id = active_conversation_id

            if arg.isdigit():
                idx = int(arg) - 1
                if 0 <= idx < len(all_convs):
                    target_id = all_convs[idx].id

            if target_id:
                forked = await conv_repo.fork_conversation(target_id)
                if forked:
                    active_conversation_id = forked.id
                    console.print(f"[bold green]Forked into new session:[/bold green] [cyan]{forked.title}[/cyan]")
                    console.print("[dim]All context and memory copied. You can now experiment independently without altering the original session.[/dim]\n")
            else:
                console.print("[yellow]No active session to fork. Use 'fork <#>'[/yellow]\n")
            continue

        # 5. Export session transcript
        if user_input.lower() == "export" or user_input.lower().startswith("export "):
            arg = user_input[7:].strip() if len(user_input) > 7 else ""
            all_convs = await conv_repo.list_conversations(limit=50)
            target_conv = None

            if arg.isdigit():
                idx = int(arg) - 1
                if 0 <= idx < len(all_convs):
                    target_conv = all_convs[idx]
            elif active_conversation_id:
                target_conv = await conv_repo.get_conversation(active_conversation_id)

            if target_conv:
                md_text = await conv_repo.export_transcript(target_conv.id)
                slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", target_conv.title)[:25].strip("_")
                out_file = curr_dir / f"session_{slug}_{target_conv.id[:6]}.md"
                out_file.write_text(md_text, encoding="utf-8")
                console.print(f"[bold green]Exported session transcript to:[/bold green] [cyan]{out_file.name}[/cyan]\n")
            else:
                console.print("[yellow]No active session to export. Use 'export <#>'[/yellow]\n")
            continue

        # 6. Start fresh clean session
        if user_input.lower() in ("new", "new session", "reset session"):
            active_conversation_id = None
            console.print("[cyan]Started fresh conversation session with clean context.[/cyan]\n")
            continue

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

        # Execute all natural language requests with full tool capabilities, context continuity & session history
        with console.status("[bold green]Deliberating, executing, and verifying..."):
            state = await orchestrator.run(
                objective=target_goal,
                working_directory=curr_dir,
                conversation_id=active_conversation_id,
            )

        # Maintain active conversation ID across subsequent turns
        if state.conversation_id:
            active_conversation_id = state.conversation_id

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

