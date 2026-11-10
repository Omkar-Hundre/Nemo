"""Built-in development and operating tools for NEMO agent."""

# 1. Standard library imports
import asyncio
from pathlib import Path
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.common.types import RiskLevel, ToolResult
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.integrations.ide.registry import IDERegistry
from nemo.memory.repository import MemoryRepository
from nemo.security.policy import SecurityPolicy
from nemo.tools.base import BaseTool, ToolDefinition

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class TerminalTool(BaseTool):
    """Executes terminal commands and captures verified exit codes."""
    name = "terminal_execute"
    description = "Execute a command in PowerShell or standard shell. Captures stdout, stderr, and exit code."
    risk_level = RiskLevel.L1

    def __init__(self, default_shell: str = "powershell") -> None:
        self.executor = NativeSubprocessExecutor(default_shell=default_shell)

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run."},
                    "timeout": {"type": "number", "description": "Timeout in seconds (default 300)."},
                },
                "required": ["command"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        cmd = arguments.get("command", "")
        timeout = float(arguments.get("timeout", 300.0))
        cwd = Path(context.get("working_directory", Path.cwd()))

        res = await self.executor.execute(cmd, cwd=cwd, timeout_seconds=timeout)
        return ToolResult(
            success=res.is_success,
            data={
                "command": cmd,
                "exit_code": res.exit_code,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "duration_ms": res.duration_ms,
            },
            error=res.stderr if not res.is_success else None,
        )


class ReadFileTool(BaseTool):
    """Reads text content of a file within workspace boundaries."""
    name = "read_file"
    description = "Read file content from the workspace."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute file path."},
                },
                "required": ["path"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rel_path = arguments.get("path", "")
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / rel_path).resolve() if not Path(rel_path).is_absolute() else Path(rel_path).resolve()

        if not target.exists() or not target.is_file():
            return ToolResult(success=False, error=f"File not found: {target}")

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            return ToolResult(success=True, data={"path": str(target), "content": content})
        except Exception as exc:
            return ToolResult(success=False, error=f"Read error: {exc}")


class WriteFileTool(BaseTool):
    """Writes text content to a file safely within workspace boundaries."""
    name = "write_file"
    description = "Write or overwrite file content in the workspace."
    risk_level = RiskLevel.L2

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file path."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rel_path = arguments.get("path", "")
        content = arguments.get("content", "")
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / rel_path).resolve() if not Path(rel_path).is_absolute() else Path(rel_path).resolve()

        # Enforce workspace security boundary
        if not self.policy.is_path_safe(target):
            return ToolResult(success=False, error=f"Access denied: path outside workspace ({target})")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, data={"path": str(target), "bytes_written": len(content.encode("utf-8"))})
        except Exception as exc:
            return ToolResult(success=False, error=f"Write error: {exc}")


class ListDirectoryTool(BaseTool):
    """Lists files and folders inside workspace directory."""
    name = "list_directory"
    description = "List entries in a workspace directory."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')."},
                },
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rel_path = arguments.get("path", ".")
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / rel_path).resolve() if not Path(rel_path).is_absolute() else Path(rel_path).resolve()

        if not target.exists() or not target.is_dir():
            return ToolResult(success=False, error=f"Directory not found: {target}")

        try:
            items = []
            for child in target.iterdir():
                items.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size_bytes": child.stat().st_size if child.is_file() else 0,
                })
            return ToolResult(success=True, data={"path": str(target), "entries": sorted(items, key=lambda x: (not x["is_dir"], x["name"]))})
        except Exception as exc:
            return ToolResult(success=False, error=f"Directory listing error: {exc}")


class MemoryRecallTool(BaseTool):
    """Recalls stored developer facts and architectural decisions."""
    name = "memory_recall"
    description = "Recall project facts, decisions, and preferences from long-term memory."
    risk_level = RiskLevel.L0

    def __init__(self, repository: MemoryRepository | None = None) -> None:
        self.repo = repository or MemoryRepository()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query terms."},
                },
                "required": ["query"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        project_id = context.get("project_id")
        items = await self.repo.search_memories(query, project_id=project_id, limit=5)
        formatted = [{"id": m.id[:8], "type": m.type, "content": m.content} for m in items]
        return ToolResult(success=True, data={"query": query, "memories": formatted})


class IDEOpenTool(BaseTool):
    """Opens workspace or specific file in Antigravity or VS Code."""
    name = "ide_open"
    description = "Open workspace or file in supported editor (Antigravity, VS Code)."
    risk_level = RiskLevel.L0

    def __init__(self, registry: IDERegistry | None = None) -> None:
        self.registry = registry or IDERegistry()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to workspace or file."},
                    "line": {"type": "integer", "description": "Optional line number."},
                    "editor": {"type": "string", "description": "Optional editor name (antigravity, vscode)."},
                },
                "required": ["path"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        target = Path(arguments.get("path", ".")).resolve()
        line = arguments.get("line")
        editor = arguments.get("editor")

        if target.is_file():
            ok = await self.registry.open_file(target, line=line, preferred_ide=editor)
        else:
            ok = await self.registry.open_project(target, preferred_ide=editor)

        return ToolResult(success=ok, data={"path": str(target), "opened": ok})

# 6. Public exports
__all__ = [
    "TerminalTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirectoryTool",
    "MemoryRecallTool",
    "IDEOpenTool",
]

