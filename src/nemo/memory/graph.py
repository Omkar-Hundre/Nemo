"""Knowledge graph and entity-relationship memory visualization for Nemo."""

# 1. Standard library imports
from collections import defaultdict
from typing import Any

# 2. Third-party imports
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

# 3. Local / internal imports
from nemo.memory.repository import MemoryRepository, TaskRepository, UserProfileRepository

# 4. Types, Protocols, Schemas
# (None)


# 5. Core logic / classes / functions
class MemoryGraph:
    """Directed Knowledge Graph of Developer profile, system tools, and project facts."""

    def __init__(
        self,
        mem_repo: MemoryRepository | None = None,
        user_repo: UserProfileRepository | None = None,
        task_repo: TaskRepository | None = None,
    ) -> None:
        self.mem_repo = mem_repo or MemoryRepository()
        self.user_repo = user_repo or UserProfileRepository()
        self.task_repo = task_repo or TaskRepository()

    async def get_graph_data(self, project_id: str | None = None) -> dict[str, Any]:
        """Aggregate user profile, entities, relations, and recent tasks."""
        profile = await self.user_repo.get_or_create_profile()
        triplets = await self.mem_repo.list_triplets(project_id=project_id)
        if not triplets:
            from nemo.memory.backfill import KnowledgeGraphBootstrapper
            await KnowledgeGraphBootstrapper(
                mem_repo=self.mem_repo,
                user_repo=self.user_repo,
                task_repo=self.task_repo,
            ).run()
            triplets = await self.mem_repo.list_triplets(project_id=project_id)

        all_memories = await self.mem_repo.list_memories(project_id=project_id, limit=30)
        recent_tasks = await self.task_repo.list_tasks(limit=10)

        # Group triplets by subject entity
        entity_graph: dict[str, list[dict[str, str]]] = defaultdict(list)
        for t in triplets:
            subj = str(t.get("subject") or "General")
            entity_graph[subj].append({
                "predicate": str(t.get("predicate") or "relates_to"),
                "object": str(t.get("object") or ""),
                "content": str(t.get("content") or ""),
                "type": str(t.get("type") or "fact"),
            })

        return {
            "profile": {
                "name": profile.name,
                "timezone": profile.timezone,
                "preferences": profile.preferences,
            },
            "entities": entity_graph,
            "triplets_count": len(triplets),
            "memories_count": len(all_memories),
            "tasks_count": len(recent_tasks),
            "recent_tasks": [
                {
                    "objective": t.objective,
                    "status": t.status,
                    "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
                }
                for t in recent_tasks
            ],
            "memories": [
                {"content": m.content, "type": m.type, "importance": m.importance}
                for m in all_memories[:10]
            ],
        }

    async def to_ascii_tree(self, project_id: str | None = None) -> str:
        """Render a clean textual ASCII knowledge graph."""
        data = await self.get_graph_data(project_id=project_id)
        p = data["profile"]
        prefs = p.get("preferences", {})

        lines = [
            "🧠 NEMO KNOWLEDGE GRAPH & DEVELOPER MEMORY",
            "═══════════════════════════════════════════════════════════════════",
            f"👤 Developer: {p.get('name', 'Developer')} ({prefs.get('os', 'Windows')})",
            f"   • IDE: {prefs.get('ide', 'Antigravity IDE')} | Browser: {prefs.get('browser', 'Brave')}",
            f"   • Stack: {', '.join(prefs.get('python_stack', ['Python 3.12', 'UV']))}",
            f"   • Tone: {prefs.get('design_style', 'Minimal, Developer-First')}",
            "",
            f"🌐 Knowledge Graph Relations ({data['triplets_count']} explicit links):",
        ]

        if not data["entities"]:
            lines.append("   (No explicit knowledge triplets found. Run backfill to bootstrap graph.)")
        else:
            for entity, relations in sorted(data["entities"].items()):
                lines.append(f"   [{entity}]")
                for r in relations:
                    lines.append(f"     └─── {r['predicate']} ──► {r['object']}")

        lines.extend([
            "",
            f"📜 Core Architectural Decisions ({data['memories_count']} total):",
        ])
        for m in data["memories"][:6]:
            lines.append(f"   • {m['content']}")

        lines.extend([
            "",
            f"⚡ Recent Historical Tasks ({len(data['recent_tasks'])} tracked):",
        ])
        for t in data["recent_tasks"][:5]:
            lines.append(f"   • [{t['created_at']}] {t['objective']} ({t['status']})")

        return "\n".join(lines)

    async def render_rich_panel(self, console: Console | None = None, project_id: str | None = None) -> Panel:
        """Render an attractive Rich panel Knowledge Graph."""
        data = await self.get_graph_data(project_id=project_id)
        p = data["profile"]
        prefs = p.get("preferences", {})

        tree = Tree(f"[bold cyan]🧠 Nemo Knowledge Graph[/bold cyan] [dim](Developer: {p.get('name')})[/dim]")

        # 1. Profile Node
        prof_node = tree.add("[bold green]👤 Developer Identity[/bold green]")
        prof_node.add(f"[bold]Name:[/bold] {p.get('name')} | [bold]OS:[/bold] {prefs.get('os', 'Windows')}")
        prof_node.add(f"[bold]Preferred IDE:[/bold] [cyan]{prefs.get('ide', 'Antigravity IDE')}[/cyan]")
        prof_node.add(f"[bold]Preferred Browser:[/bold] [cyan]{prefs.get('browser', 'Brave')}[/cyan]")
        stack_str = ", ".join(prefs.get("python_stack", ["Python 3.12", "UV"]))
        prof_node.add(f"[bold]Core Stack:[/bold] [dim]{stack_str}[/dim]")

        # 2. Entity Relations Node
        rel_node = tree.add(f"[bold yellow]🌐 Entities & Semantic Relations[/bold yellow] [dim]({data['triplets_count']} triplets)[/dim]")
        if not data["entities"]:
            rel_node.add("[dim]No entity relations found.[/dim]")
        else:
            for entity, relations in sorted(data["entities"].items()):
                sub_tree = rel_node.add(f"[bold magenta][{entity}][/bold magenta]")
                for r in relations:
                    sub_tree.add(f"[cyan]── {r['predicate']} ──►[/cyan] [white]{r['object']}[/white]")

        # 3. Architectural Memories
        mem_node = tree.add(f"[bold blue]📜 Architectural Decisions & Conventions[/bold blue] [dim]({data['memories_count']} items)[/dim]")
        for m in data["memories"][:5]:
            mem_node.add(f"• {m['content']}")

        # 4. Historical Tasks
        task_node = tree.add(f"[bold cyan]⚡ Historical Agent Milestones[/bold cyan] [dim]({len(data['recent_tasks'])} recent)[/dim]")
        for t in data["recent_tasks"][:5]:
            task_node.add(f"[dim]{t['created_at']}[/dim] [green]✓[/green] {t['objective']}")

        return Panel(
            tree,
            title="[bold cyan]Nemo Unified Knowledge Graph[/bold cyan]",
            border_style="cyan",
            expand=False,
        )


# 6. Public exports
__all__ = ["MemoryGraph"]
