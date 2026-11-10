"""Built-in development, operating, and code intelligence tools for NEMO agent."""

# 1. Standard library imports
import ast
import asyncio
import csv
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from typing import Any
import webbrowser

# 2. Third-party imports
import docx
import httpx
import pypdf

# 3. Local / internal imports
from nemo.ai.embeddings import NvidiaEmbeddingProvider, cosine_similarity
from nemo.common.types import RiskLevel, ToolResult
from nemo.execution.sessions.manager import SessionManager
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.integrations.ide.registry import IDERegistry
from nemo.intelligence.chunks import StructureAwareChunker
from nemo.intelligence.graph import ProjectGraphBuilder
from nemo.intelligence.indexer import ProjectIndexer
from nemo.intelligence.packages import PackageManagerDetector
from nemo.intelligence.parser import ASTCodeParser
from nemo.intelligence.scanner import ProjectScanner
from nemo.memory.repository import MemoryRepository
from nemo.security.policy import SecurityPolicy
from nemo.tools.base import BaseTool, ToolDefinition

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class CodebaseSummaryTool(BaseTool):
    """Provides instant architectural summary of all indexed modules, files, and symbols."""
    name = "get_codebase_summary"
    description = "Get high-level architecture overview of the current project, including all modules, files, and symbols in one step."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional workspace path (default '.')."},
                },
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / arguments.get("path", ".")).resolve()
        indexer = ProjectIndexer(target)
        summary = indexer.get_summary()
        return ToolResult(success=True, data=summary)


class CodeSearchTool(BaseTool):
    """Fast keyword search across file paths and code symbols."""
    name = "search_code"
    description = "Search codebase for matching filenames, modules, and symbol definitions (classes/functions)."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword or symbol name."},
                    "limit": {"type": "integer", "description": "Max results (default 15)."},
                },
                "required": ["query"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        limit = int(arguments.get("limit", 15))
        base_dir = Path(context.get("working_directory", Path.cwd()))
        indexer = ProjectIndexer(base_dir)
        matches = indexer.search_code(query, limit=limit)
        return ToolResult(success=True, data={"query": query, "matches": matches})


class SymbolLookupTool(BaseTool):
    """Deep AST lookup of a specific symbol, its methods, docstring, and call references."""
    name = "lookup_symbol"
    description = "Inspect exact AST definition, line numbers, docstrings, and callers of a function or class."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "Name of class, function, or method."},
                    "file_path": {"type": "string", "description": "Path to file containing symbol."},
                },
                "required": ["symbol_name", "file_path"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        sym_name = arguments.get("symbol_name", "")
        file_path = arguments.get("file_path", "")
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / file_path).resolve()

        if not target.exists() or not target.is_file():
            return ToolResult(success=False, error=f"File not found: {target}")

        parsed = ASTCodeParser.parse_python_file(target)
        for cls in parsed.classes:
            if cls["name"] == sym_name:
                return ToolResult(success=True, data={"symbol": cls, "kind": "class", "file": str(target)})
            for m in cls.get("methods", []):
                if m["name"] == sym_name or f"{cls['name']}.{m['name']}" == sym_name:
                    return ToolResult(success=True, data={"symbol": m, "kind": "method", "class": cls["name"], "file": str(target)})

        for fn in parsed.functions:
            if fn["name"] == sym_name:
                return ToolResult(success=True, data={"symbol": fn, "kind": "function", "file": str(target)})

        return ToolResult(success=False, error=f"Symbol '{sym_name}' not found in {file_path}")


class SemanticSearchTool(BaseTool):
    """Dense vector semantic search across structure-aware code chunks."""
    name = "semantic_search"
    description = "Search codebase semantically using dense vector similarity (NVIDIA Embeddings)."
    risk_level = RiskLevel.L0

    def __init__(self) -> None:
        self.embed_provider = NvidiaEmbeddingProvider()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query describing desired code or logic."},
                    "file_path": {"type": "string", "description": "Optional file path to constrain search."},
                    "top_k": {"type": "integer", "description": "Top matches to return (default 3)."},
                },
                "required": ["query"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        top_k = int(arguments.get("top_k", 3))
        base_dir = Path(context.get("working_directory", Path.cwd()))

        file_filter = arguments.get("file_path")
        if file_filter:
            target_files = [(base_dir / file_filter).resolve()]
        else:
            indexer = ProjectIndexer(base_dir)
            target_files = [Path(f.path) for f in indexer.get_indexed_files()[:20]]

        # Generate chunks
        all_chunks = []
        for tf in target_files:
            if tf.exists() and tf.is_file():
                all_chunks.extend(StructureAwareChunker.chunk_file(tf))

        if not all_chunks:
            return ToolResult(success=True, data={"results": []})

        query_vec = await self.embed_provider.embed_query(query)
        if not query_vec:
            # Fallback to keyword match if embedding unavailable
            matches = [c.model_dump() for c in all_chunks if any(w.lower() in c.content.lower() for w in query.split())]
            return ToolResult(success=True, data={"results": matches[:top_k], "mode": "keyword_fallback"})

        # Embed chunk texts
        chunk_texts = [c.content[:500] for c in all_chunks[:30]]
        doc_vecs = await self.embed_provider.embed_documents(chunk_texts)

        scored = []
        for chunk, dvec in zip(all_chunks[:30], doc_vecs):
            sim = cosine_similarity(query_vec, dvec)
            scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [
            {
                "similarity": round(score, 4),
                "file": item.file_path,
                "symbol": item.symbol_name,
                "lines": f"{item.start_line}-{item.end_line}",
                "snippet": item.content[:300],
            }
            for score, item in scored[:top_k]
        ]
        return ToolResult(success=True, data={"results": results, "mode": "dense_vector"})


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


class CreateFolderTool(BaseTool):
    """Creates a directory or folder tree safely within workspace or user boundaries."""
    name = "create_folder"
    description = "Create a directory or folder hierarchy (e.g. in workspace, Downloads, Desktop). Fast native directory creation."
    risk_level = RiskLevel.L1

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder path to create (relative or absolute)."},
                },
                "required": ["path"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("path", "")
        if not raw_path:
            return ToolResult(success=False, error="Path is required.")

        p_str = str(raw_path).replace("$env:USERPROFILE", str(Path.home())).replace("~", str(Path.home()))
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / p_str).resolve() if not Path(p_str).is_absolute() else Path(p_str).resolve()

        if not self.policy.is_path_safe(target, base_dir=base_dir):
            return ToolResult(success=False, error=f"Access denied: path outside allowed boundary ({target})")

        try:
            target.mkdir(parents=True, exist_ok=True)
            return ToolResult(success=True, data={"path": str(target), "created": True, "is_directory": target.is_dir()})
        except Exception as exc:
            return ToolResult(success=False, error=f"Folder creation error: {exc}")


class WriteFileTool(BaseTool):
    """Writes text content to a file safely within workspace boundaries."""
    name = "write_file"
    description = "Write or overwrite file content in the workspace. Native Python file write without PowerShell escaping."
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
                    "content": {"type": "string", "description": "Full file content to write. Clean raw code or text without PowerShell escaping."},
                },
                "required": ["path", "content"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rel_path = arguments.get("path", "")
        content = arguments.get("content", "")
        if not rel_path:
            return ToolResult(success=False, error="Path is required.")

        p_str = str(rel_path).replace("$env:USERPROFILE", str(Path.home())).replace("~", str(Path.home()))
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / p_str).resolve() if not Path(p_str).is_absolute() else Path(p_str).resolve()

        # Enforce workspace security boundary
        if not self.policy.is_path_safe(target, base_dir=base_dir):
            return ToolResult(success=False, error=f"Access denied: path outside workspace ({target})")

        # Sanitize accidental PowerShell backtick escapes (`n -> \n, `" -> ", `t -> \t, `r -> '')
        if "`n" in content or '`"' in content:
            content = content.replace("`r`n", "\n").replace("`n", "\n").replace('`"', '"').replace("`t", "\t").replace("`r", "")

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


class OpenBrowserTool(BaseTool):
    """Opens a URL or local dev server address in default system browser."""
    name = "open_browser"
    description = "Open a local URL (e.g. http://localhost:5173 or http://localhost:3000) in default web browser."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open in web browser (default 'http://localhost:3000')."},
                },
                "required": ["url"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "http://localhost:3000")
        try:
            opened = webbrowser.open(url)
            return ToolResult(success=True, data={"url": url, "opened": opened})
        except Exception as exc:
            return ToolResult(success=False, error=f"Browser open error: {exc}")


class ProjectEnvironmentTool(BaseTool):
    """Inspects workspace manifests, installed packages status, dev commands, and default ports."""
    name = "inspect_project_environment"
    description = "Inspect detected project ecosystems, manifests, whether dependencies are installed, dev commands, and default URLs."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace directory path (default '.')."},
                },
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / arguments.get("path", ".")).resolve()
        ecosystems = PackageManagerDetector.detect(target)
        eco_dicts = [e.model_dump() for e in ecosystems]
        return ToolResult(success=True, data={"workspace": str(target), "ecosystems": eco_dicts})


class GitDiffTool(BaseTool):
    """Inspects uncommitted changes and modified files relative to git HEAD."""
    name = "git_diff"
    description = "Inspect uncommitted code changes and modified files relative to HEAD or Git status."
    risk_level = RiskLevel.L0

    def __init__(self, executor: NativeSubprocessExecutor | None = None) -> None:
        self.executor = executor or NativeSubprocessExecutor()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "Whether to inspect staged changes only (default false)."},
                },
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        staged_flag = "--staged" if arguments.get("staged") else ""
        res_diff = await self.executor.execute(f"git diff {staged_flag}", cwd=base_dir)
        res_status = await self.executor.execute("git status -s", cwd=base_dir)
        return ToolResult(
            success=True,
            data={
                "diff": res_diff.stdout[:4000],
                "status": res_status.stdout[:1000],
            },
        )


class LaunchBackgroundProcessTool(BaseTool):
    """Launch long-running dev servers or watchers in background session without blocking."""
    name = "launch_background_process"
    description = "Launch long-running background command (e.g. 'npm run dev', 'python main.py'). Verifies process started, checks port readiness, captures initial log lines, and returns immediately."
    risk_level = RiskLevel.L1

    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self.session_mgr = session_manager or SessionManager()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run in background (e.g. 'npm run dev')."},
                    "port": {"type": "integer", "description": "Optional port number to poll for readiness (e.g. 5173, 3000)."},
                    "wait_seconds": {"type": "number", "description": "Seconds to wait for port or initial logs (default 2.0)."},
                    "log_file": {"type": "string", "description": "Optional relative log filename (default 'nemo_dev_server.log')."},
                },
                "required": ["command"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        command = arguments.get("command", "")
        port = arguments.get("port")
        wait_seconds = float(arguments.get("wait_seconds", 2.0))
        log_name = arguments.get("log_file", "nemo_dev_server.log")

        base_dir = Path(context.get("working_directory", Path.cwd()))
        log_path = base_dir / log_name

        session = self.session_mgr.create_session(cwd=base_dir)
        try:
            self.session_mgr.launch_background(session.session_id, command, log_path=log_path)
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to launch background process: {exc}")

        # Poll port or wait brief interval
        port_ready = False
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < wait_seconds:
            if port:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        port_ready = True
                        break
                except Exception:
                    pass
            await asyncio.sleep(0.3)

        # Check PID is alive
        alive = self.session_mgr._is_pid_alive(session.pid) if session.pid else False

        # Read initial log tail
        recent_logs = []
        if log_path.exists():
            try:
                recent_logs = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            except Exception:
                pass

        return ToolResult(
            success=alive,
            data={
                "session_id": session.session_id,
                "pid": session.pid,
                "running": alive,
                "port_ready": port_ready,
                "log_file": str(log_path),
                "recent_logs": recent_logs,
            },
            error=None if alive else "Process terminated immediately after start. Inspect recent_logs for errors.",
        )


class ManageBackgroundProcessTool(BaseTool):
    """Check status, inspect logs, or terminate active background sessions."""
    name = "manage_background_process"
    description = "Manage active background processes: inspect logs, check if PID is alive, or terminate process tree."
    risk_level = RiskLevel.L1

    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self.session_mgr = session_manager or SessionManager()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID of the background process."},
                    "action": {
                        "type": "string",
                        "enum": ["status", "logs", "stop"],
                        "description": "Action to perform: 'status', 'logs', or 'stop'.",
                    },
                },
                "required": ["session_id", "action"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        session_id = arguments.get("session_id", "")
        action = arguments.get("action", "status")

        session = self.session_mgr.get_session(session_id)
        if not session:
            return ToolResult(success=False, error=f"Session '{session_id}' not found.")

        if action == "stop":
            terminated = await self.session_mgr.terminate(session_id)
            return ToolResult(success=terminated, data={"session_id": session_id, "stopped": terminated})

        # status or logs
        alive = self.session_mgr._is_pid_alive(session.pid) if session.pid else False
        return ToolResult(
            success=True,
            data={
                "session_id": session_id,
                "pid": session.pid,
                "status": "running" if alive else "terminated",
                "output_tail": session.recent_output[-30:],
            },
        )


class ASTStructuralSearchTool(BaseTool):
    """Structural AST pattern search across codebase for functions, classes, decorators, and calls."""
    name = "ast_grep"
    description = "Search codebase using standard library Python AST analysis. Locate functions, classes, decorators, call sites, and signatures across files without fragile text regex."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "AST node type: 'FunctionDef', 'AsyncFunctionDef', 'ClassDef', 'Call', or 'any' (default 'any').",
                    },
                    "name_pattern": {"type": "string", "description": "Name or substring of function, class, or call target to locate."},
                    "decorator": {"type": "string", "description": "Optional decorator name (e.g. 'pytest.mark.asyncio', 'app.get')."},
                    "path": {"type": "string", "description": "Relative directory or file to search (default '.')."},
                    "limit": {"type": "integer", "description": "Max results to return (default 25)."},
                },
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        node_type = arguments.get("node_type", "any")
        name_pattern = arguments.get("name_pattern", "").lower()
        decorator_filter = arguments.get("decorator", "").lower()
        path_arg = arguments.get("path", ".")
        limit = int(arguments.get("limit", 25))

        base_dir = Path(context.get("working_directory", Path.cwd()))
        target = (base_dir / path_arg).resolve()

        files: list[Path] = []
        if target.is_file() and target.suffix.lower() == ".py":
            files = [target]
        elif target.is_dir():
            files = [
                p for p in target.rglob("*.py")
                if not any(ign in p.parts for ign in (".venv", "venv", "node_modules", ".git", "__pycache__", "dist", "build"))
            ]

        matches = []
        for file_path in files:
            if len(matches) >= limit:
                break
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(file_path))
            except Exception:
                continue

            rel_file = str(file_path.relative_to(base_dir)).replace("\\", "/")

            for node in ast.walk(tree):
                if len(matches) >= limit:
                    break

                curr_type = type(node).__name__
                if node_type != "any":
                    if node_type in ("FunctionDef", "function") and curr_type in ("FunctionDef", "AsyncFunctionDef"):
                        pass
                    elif curr_type != node_type:
                        continue

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = node.name
                    if name_pattern and name_pattern not in name.lower():
                        continue
                    decorators = []
                    for d in node.decorator_list:
                        try:
                            decorators.append(ast.unparse(d))
                        except Exception:
                            if isinstance(d, ast.Name):
                                decorators.append(d.id)
                    if decorator_filter and not any(decorator_filter in dec.lower() for dec in decorators):
                        continue
                    doc = ast.get_docstring(node) or ""
                    matches.append({
                        "file": rel_file,
                        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        "name": name,
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "decorators": decorators,
                        "docstring": doc[:120],
                    })

                elif isinstance(node, ast.ClassDef):
                    name = node.name
                    if name_pattern and name_pattern not in name.lower():
                        continue
                    doc = ast.get_docstring(node) or ""
                    matches.append({
                        "file": rel_file,
                        "kind": "class",
                        "name": name,
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "docstring": doc[:120],
                    })

                elif isinstance(node, ast.Call) and (node_type == "Call" or (not node_type and name_pattern)):
                    target_name = ""
                    if isinstance(node.func, ast.Name):
                        target_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        target_name = node.func.attr
                    if name_pattern and name_pattern not in target_name.lower():
                        continue
                    if target_name:
                        matches.append({
                            "file": rel_file,
                            "kind": "call",
                            "name": target_name,
                            "line": getattr(node, "lineno", 1),
                        })

        return ToolResult(success=True, data={"count": len(matches), "matches": matches})


class CodeGraphQueryTool(BaseTool):
    """Query architectural graph relationships (who calls a function, what files import a module)."""
    name = "query_code_graph"
    description = "Query architectural code relationships: inspect every caller of a function, what files import a module, or what symbols are declared across modules."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["callers", "callees", "imports", "declarations"],
                        "description": "Relationship query type: 'callers' (who calls this), 'callees' (who does this call), 'imports', or 'declarations'.",
                    },
                    "target": {"type": "string", "description": "Target symbol, function, or module name."},
                    "path": {"type": "string", "description": "Workspace path (default '.')."},
                },
                "required": ["query_type"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        query_type = arguments.get("query_type", "callers")
        target = arguments.get("target", "")
        path_arg = arguments.get("path", ".")

        base_dir = Path(context.get("working_directory", Path.cwd()))
        root = (base_dir / path_arg).resolve()

        scanner = ProjectScanner(root)
        scanned = scanner.scan()
        py_files = [Path(f.path) for f in scanned if f.language == "python"]

        graph = ProjectGraphBuilder.build_graph(project_name=root.name, root_path=root, python_files=py_files)

        if query_type == "callers":
            matches = graph.find_callers(target)
        elif query_type == "callees":
            matches = graph.find_callees(target)
        elif query_type == "imports":
            matches = graph.find_imports(target)
        elif query_type == "declarations":
            matches = graph.find_declarations(name_filter=target)
        else:
            return ToolResult(success=False, error=f"Unknown query_type: '{query_type}'")

        return ToolResult(
            success=True,
            data={
                "query_type": query_type,
                "target": target,
                "count": len(matches),
                "results": matches,
            },
        )


class HttpProbeTool(BaseTool):
    """Probe an HTTP/HTTPS endpoint to verify service health, response code, and latency."""
    name = "http_probe"
    description = "Send an HTTP request to local or remote endpoint to verify server readiness, response code, latency, and body snippet."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target endpoint URL (e.g. 'http://localhost:5173')."},
                    "method": {"type": "string", "enum": ["GET", "POST", "HEAD"], "description": "HTTP method (default 'GET')."},
                    "timeout_seconds": {"type": "number", "description": "Request timeout in seconds (default 5.0)."},
                    "expected_status": {"type": "integer", "description": "Optional expected status code (e.g. 200)."},
                },
                "required": ["url"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "").strip()
        method = arguments.get("method", "GET").upper()
        timeout = float(arguments.get("timeout_seconds", 5.0))
        expected_status = arguments.get("expected_status")

        if not url:
            return ToolResult(success=False, error="URL argument is required")

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.request(method=method, url=url)
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                is_expected = (response.status_code == expected_status) if expected_status else response.is_success
                preview = response.text[:1200]

                return ToolResult(
                    success=is_expected,
                    data={
                        "url": str(response.url),
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                        "is_success": response.is_success,
                        "content_type": response.headers.get("content-type", ""),
                        "preview": preview,
                    },
                    error=None if is_expected else f"Expected status {expected_status}, got {response.status_code}",
                )
        except httpx.ConnectError:
            return ToolResult(
                success=False,
                error=f"Connection refused at {url}. The server may not be listening on this port yet or has exited.",
            )
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error=f"Request to {url} timed out after {timeout} seconds.",
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"HTTP probe failed: {exc}")


class PortManagerTool(BaseTool):
    """Inspect listening network ports on Windows or terminate occupant processes."""
    name = "port_manager"
    description = "Inspect listening TCP ports on Windows to locate process ownership (PID, image name), or terminate occupant processes holding a port."
    risk_level = RiskLevel.L2

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inspect", "kill_occupant"],
                        "description": "'inspect' identifies process holding the port; 'kill_occupant' forcefully terminates the process tree.",
                    },
                    "port": {"type": "integer", "description": "Target TCP port number (e.g. 3000, 5173, 8000)."},
                },
                "required": ["action", "port"],
            },
            risk_level=self.risk_level,
        )

    def _get_process_name(self, pid: int) -> str:
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            line = res.stdout.strip()
            if line and not line.startswith("INFO:"):
                return line.split(",")[0].strip('"')
        except Exception:
            pass
        return "unknown"

    def _find_port_owner(self, port: int) -> dict[str, Any] | None:
        try:
            res = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].upper() == "TCP":
                    local_addr = parts[1]
                    state = parts[3]
                    pid_str = parts[4]
                    if local_addr.endswith(f":{port}") and pid_str.isdigit():
                        pid = int(pid_str)
                        if pid == 0:
                            continue
                        proc_name = self._get_process_name(pid)
                        return {
                            "port": port,
                            "pid": pid,
                            "state": state,
                            "process_name": proc_name,
                            "local_address": local_addr,
                        }
        except Exception:
            pass
        return None

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "inspect")
        port = int(arguments.get("port", 0))

        if port <= 0 or port > 65535:
            return ToolResult(success=False, error=f"Invalid port: {port}")

        owner = self._find_port_owner(port)

        if action == "inspect":
            if owner:
                return ToolResult(
                    success=True,
                    data={"in_use": True, **owner},
                )
            return ToolResult(
                success=True,
                data={"in_use": False, "port": port, "message": f"Port {port} is free and not in use."},
            )

        if action == "kill_occupant":
            if not owner:
                return ToolResult(
                    success=True,
                    data={"port": port, "killed": False, "message": f"No active process found holding port {port}."},
                )
            pid = owner["pid"]
            try:
                res = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                )
                killed = (res.returncode == 0)
                return ToolResult(
                    success=killed,
                    data={
                        "port": port,
                        "killed": killed,
                        "pid": pid,
                        "process_name": owner["process_name"],
                        "output": res.stdout.strip() or res.stderr.strip(),
                    },
                    error=None if killed else f"Failed to terminate PID {pid}: {res.stderr.strip()}",
                )
            except Exception as exc:
                return ToolResult(success=False, error=f"taskkill failed: {exc}")

        return ToolResult(success=False, error=f"Unknown action: '{action}'")


class FindFilesTool(BaseTool):
    """Recursively search workspace directory for files matching glob patterns."""
    name = "find_files"
    description = "Search workspace recursively for files matching glob pattern (e.g. '**/*.config.*', '**/package.json', '**/*.py') with automatic exclusion of build/venv directories."
    risk_level = RiskLevel.L0

    EXCLUDED_DIRS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".next", ".turbo"}

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.config.*', '**/package.json', '**/*.env*')."},
                    "path": {"type": "string", "description": "Root path to search from (default '.')."},
                    "limit": {"type": "integer", "description": "Maximum matches to return (default 50)."},
                },
                "required": ["pattern"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        pattern = arguments.get("pattern", "*").strip()
        path_arg = arguments.get("path", ".")
        limit = int(arguments.get("limit", 50))

        base_dir = Path(context.get("working_directory", Path.cwd()))
        root = (base_dir / path_arg).resolve()

        if not root.exists():
            return ToolResult(success=False, error=f"Directory does not exist: {root}")

        matches = []
        try:
            for item in root.glob(pattern):
                if any(part in self.EXCLUDED_DIRS for part in item.parts):
                    continue
                matches.append({
                    "path": str(item.relative_to(root)).replace("\\", "/"),
                    "size_bytes": item.stat().st_size if item.is_file() else 0,
                    "is_directory": item.is_dir(),
                })
                if len(matches) >= limit:
                    break

            return ToolResult(
                success=True,
                data={
                    "pattern": pattern,
                    "search_root": str(root),
                    "count": len(matches),
                    "matches": matches,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"File search failed: {exc}")


class ScaffoldProjectTool(BaseTool):
    """Scaffold a new project tech stack non-interactively without prompt hanging."""
    name = "scaffold_project"
    description = "Scaffold a new project (e.g. 'react-ts', 'react', 'vue-ts', 'vue', 'nextjs', 'fastapi', 'node') non-interactively with guaranteed non-hanging parameters."
    risk_level = RiskLevel.L2

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "enum": ["react-ts", "react", "vue-ts", "vue", "nextjs", "fastapi", "node"],
                        "description": "Tech stack template identifier.",
                    },
                    "project_name": {"type": "string", "description": "Target project / folder name (e.g. 'frontend', 'my-app')."},
                    "path": {"type": "string", "description": "Parent directory where project will be created (default '.')."},
                    "install_dependencies": {"type": "boolean", "description": "Whether to automatically install dependencies after scaffolding (default true)."},
                },
                "required": ["template", "project_name"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        template = arguments.get("template", "react-ts")
        project_name = arguments.get("project_name", "app").strip()
        path_arg = arguments.get("path", ".")
        install_deps = arguments.get("install_dependencies", True)

        base_dir = Path(context.get("working_directory", Path.cwd()))
        parent_dir = (base_dir / path_arg).resolve()
        target_dir = parent_dir / project_name

        if target_dir.exists() and any(target_dir.iterdir()):
            return ToolResult(success=False, error=f"Target directory '{target_dir}' already exists and is not empty.")

        executor = NativeSubprocessExecutor()

        try:
            if template in ("react-ts", "react", "vue-ts", "vue"):
                cmd = f"npm create vite@latest {project_name} -- --template {template}"
                scaffold_res = await executor.execute(cmd, cwd=str(parent_dir), timeout_seconds=60.0)
                if not scaffold_res.is_success:
                    return ToolResult(success=False, error=f"Vite scaffolding failed: {scaffold_res.stderr or scaffold_res.stdout}")

                if install_deps:
                    install_res = await executor.execute("npm install", cwd=str(target_dir), timeout_seconds=180.0)
                    if not install_res.is_success:
                        return ToolResult(success=False, error=f"npm install failed: {install_res.stderr or install_res.stdout}")

                return ToolResult(
                    success=True,
                    data={
                        "template": template,
                        "project_name": project_name,
                        "path": str(target_dir),
                        "dev_command": "npm run dev",
                        "default_url": "http://localhost:5173",
                        "dependencies_installed": install_deps,
                    },
                )

            elif template == "nextjs":
                cmd = f"npx -y create-next-app@latest {project_name} --typescript --tailwind --eslint --app --src-dir --import-alias \"@/*\" --use-npm --no-turbopack --yes"
                scaffold_res = await executor.execute(cmd, cwd=str(parent_dir), timeout_seconds=180.0)
                if not scaffold_res.is_success:
                    return ToolResult(success=False, error=f"Next.js scaffolding failed: {scaffold_res.stderr or scaffold_res.stdout}")

                return ToolResult(
                    success=True,
                    data={
                        "template": template,
                        "project_name": project_name,
                        "path": str(target_dir),
                        "dev_command": "npm run dev",
                        "default_url": "http://localhost:3000",
                        "dependencies_installed": True,
                    },
                )

            elif template == "fastapi":
                target_dir.mkdir(parents=True, exist_ok=True)
                pyproject = target_dir / "pyproject.toml"
                pyproject.write_text(
                    f'[project]\nname = "{project_name}"\nversion = "0.1.0"\ndependencies = [\n    "fastapi>=0.115.0",\n    "uvicorn[standard]>=0.30.0",\n]\n',
                    encoding="utf-8",
                )
                main_py = target_dir / "main.py"
                main_py.write_text(
                    'from fastapi import FastAPI\n\napp = FastAPI(title="' + project_name + '")\n\n@app.get("/")\ndef read_root():\n    return {"status": "ok", "project": "' + project_name + '"}\n',
                    encoding="utf-8",
                )
                gitignore = target_dir / ".gitignore"
                gitignore.write_text(".venv/\n__pycache__/\n*.pyc\n.env\n", encoding="utf-8")

                if install_deps:
                    await executor.execute("python -m venv .venv", cwd=str(target_dir), timeout_seconds=30.0)
                    venv_pip = target_dir / ".venv" / "Scripts" / "pip.exe"
                    if venv_pip.exists():
                        await executor.execute(f'"{venv_pip}" install fastapi "uvicorn[standard]"', cwd=str(target_dir), timeout_seconds=120.0)

                return ToolResult(
                    success=True,
                    data={
                        "template": template,
                        "project_name": project_name,
                        "path": str(target_dir),
                        "dev_command": "uvicorn main:app --reload --port 8000",
                        "default_url": "http://localhost:8000",
                        "dependencies_installed": install_deps,
                    },
                )

            elif template == "node":
                target_dir.mkdir(parents=True, exist_ok=True)
                init_res = await executor.execute("npm init -y", cwd=str(target_dir), timeout_seconds=30.0)
                if not init_res.is_success:
                    return ToolResult(success=False, error=f"npm init failed: {init_res.stderr or init_res.stdout}")
                index_js = target_dir / "index.js"
                index_js.write_text('console.log("Hello from ' + project_name + '");\n', encoding="utf-8")
                return ToolResult(
                    success=True,
                    data={
                        "template": template,
                        "project_name": project_name,
                        "path": str(target_dir),
                        "dev_command": "node index.js",
                        "dependencies_installed": False,
                    },
                )

            else:
                return ToolResult(success=False, error=f"Unsupported template: '{template}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"Scaffolding failed: {exc}")


class EnvConfigInspectorTool(BaseTool):
    """Inspect and validate environment variables and secrets configuration."""
    name = "inspect_env_config"
    description = "Compare .env against .env.example/template to detect missing variables, unpopulated placeholder defaults, and format issues without exposing secrets."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project directory (default '.')."},
                    "example_file": {"type": "string", "description": "Template filename (default '.env.example')."},
                    "target_file": {"type": "string", "description": "Target environment filename (default '.env')."},
                },
            },
            risk_level=self.risk_level,
        )

    def _parse_env_keys(self, file_path: Path) -> dict[str, str]:
        keys = {}
        if not file_path.exists():
            return keys
        for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                keys[key.strip()] = val.strip()
        return keys

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        root = (base_dir / arguments.get("path", ".")).resolve()
        example_name = arguments.get("example_file", ".env.example")
        target_name = arguments.get("target_file", ".env")

        example_file = root / example_name
        if not example_file.exists():
            for alt in [".env.template", ".env.sample", "example.env"]:
                if (root / alt).exists():
                    example_file = root / alt
                    break

        target_file = root / target_name

        if not example_file.exists() and not target_file.exists():
            return ToolResult(
                success=True,
                data={"has_env": False, "message": "No .env or .env.example files detected."},
            )

        example_keys = self._parse_env_keys(example_file)
        target_keys = self._parse_env_keys(target_file)

        missing_keys = [k for k in example_keys if k not in target_keys]
        placeholders = {"change_me", "your_key", "your_api_key", "todo", "replace_me", ""}
        unpopulated = [k for k, v in target_keys.items() if v.lower().strip("\"'") in placeholders]

        return ToolResult(
            success=True,
            data={
                "target_file_exists": target_file.exists(),
                "example_file_exists": example_file.exists(),
                "configured_keys_count": len(target_keys),
                "required_keys_count": len(example_keys),
                "missing_keys": missing_keys,
                "unpopulated_keys": unpopulated,
                "is_healthy": (len(missing_keys) == 0 and len(unpopulated) == 0 and target_file.exists()),
            },
        )


class DocumentReaderTool(BaseTool):
    """Extract and read structured text from PDF, DOCX, CSV, Markdown, and text files."""
    name = "read_document"
    description = "Read and extract text, tables, and metadata from documents (.pdf, .docx, .csv, .tsv, .md, .txt, .json)."
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to document file."},
                    "max_pages": {"type": "integer", "description": "Maximum pages to extract from PDF (default 25)."},
                    "max_rows": {"type": "integer", "description": "Maximum rows to preview from CSV (default 50)."},
                },
                "required": ["path"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        doc_path = (base_dir / arguments.get("path", "")).resolve()
        max_pages = int(arguments.get("max_pages", 25))
        max_rows = int(arguments.get("max_rows", 50))

        if not doc_path.exists():
            return ToolResult(success=False, error=f"Document file does not exist: {doc_path}")

        ext = doc_path.suffix.lower()

        try:
            if ext == ".pdf":
                reader = pypdf.PdfReader(str(doc_path))
                total_pages = len(reader.pages)
                pages_to_read = min(total_pages, max_pages)
                extracted_pages = []
                for idx in range(pages_to_read):
                    text = reader.pages[idx].extract_text() or ""
                    extracted_pages.append(f"--- Page {idx + 1} ---\n{text}")
                return ToolResult(
                    success=True,
                    data={
                        "format": "pdf",
                        "total_pages": total_pages,
                        "pages_extracted": pages_to_read,
                        "content": "\n\n".join(extracted_pages),
                    },
                )

            elif ext == ".docx":
                doc = docx.Document(str(doc_path))
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables_data = []
                for t in doc.tables[:5]:
                    table_rows = []
                    for row in t.rows[:10]:
                        table_rows.append([cell.text.strip() for cell in row.cells])
                    tables_data.append(table_rows)

                return ToolResult(
                    success=True,
                    data={
                        "format": "docx",
                        "paragraph_count": len(paragraphs),
                        "table_count": len(doc.tables),
                        "content": "\n\n".join(paragraphs),
                        "tables_preview": tables_data,
                    },
                )

            elif ext in (".csv", ".tsv"):
                delimiter = "\t" if ext == ".tsv" else ","
                rows = []
                with open(doc_path, "r", encoding="utf-8", errors="ignore") as f:
                    csv_reader = csv.reader(f, delimiter=delimiter)
                    for idx, row in enumerate(csv_reader):
                        if idx >= max_rows:
                            break
                        rows.append(row)
                header = rows[0] if rows else []
                return ToolResult(
                    success=True,
                    data={
                        "format": "csv",
                        "headers": header,
                        "preview_row_count": len(rows),
                        "rows": rows,
                    },
                )

            elif ext in (".md", ".txt", ".json", ".yaml", ".yml", ".html", ".rst"):
                text = doc_path.read_text(encoding="utf-8", errors="ignore")
                return ToolResult(
                    success=True,
                    data={
                        "format": ext.lstrip("."),
                        "size_bytes": len(text),
                        "content": text[:15000],
                    },
                )

            else:
                return ToolResult(success=False, error=f"Unsupported document format: '{ext}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to read document: {exc}")


class DocumentGeneratorTool(BaseTool):
    """Generate structured documents in DOCX, Markdown, or styled HTML report formats."""
    name = "generate_document"
    description = "Generate a formatted document (.docx, .html, or .md) with title, structured sections, bullet points, and clean styling."
    risk_level = RiskLevel.L1

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Output file path (e.g. 'docs/architecture_report.docx' or 'report.html')."},
                    "title": {"type": "string", "description": "Document title."},
                    "format": {"type": "string", "enum": ["docx", "html", "markdown"], "description": "Output format ('docx', 'html', 'markdown')."},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["heading"],
                        },
                        "description": "Structured sections of the document.",
                    },
                    "content": {"type": "string", "description": "Optional raw markdown content if sections are not provided."},
                },
                "required": ["path", "title", "format"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        out_path = (base_dir / arguments.get("path", "")).resolve()
        title = arguments.get("title", "Document")
        doc_format = arguments.get("format", "markdown").lower()
        sections = arguments.get("sections", [])
        raw_content = arguments.get("content", "")

        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if doc_format == "docx":
                doc = docx.Document()
                doc.add_heading(title, level=0)

                if sections:
                    for sec in sections:
                        doc.add_heading(sec.get("heading", ""), level=1)
                        if sec.get("body"):
                            doc.add_paragraph(sec["body"])
                        for bullet in sec.get("bullets", []):
                            doc.add_paragraph(bullet, style="List Bullet")
                elif raw_content:
                    for line in raw_content.splitlines():
                        if line.startswith("# "):
                            doc.add_heading(line[2:], level=1)
                        elif line.startswith("## "):
                            doc.add_heading(line[3:], level=2)
                        elif line.startswith("- "):
                            doc.add_paragraph(line[2:], style="List Bullet")
                        elif line.strip():
                            doc.add_paragraph(line)

                doc.save(str(out_path))

            elif doc_format == "html":
                body_parts = [f"<h1>{title}</h1>"]
                if sections:
                    for sec in sections:
                        body_parts.append(f"<h2>{sec.get('heading', '')}</h2>")
                        if sec.get("body"):
                            body_parts.append(f"<p>{sec['body']}</p>")
                        if sec.get("bullets"):
                            body_parts.append("<ul>")
                            for b in sec["bullets"]:
                                body_parts.append(f"<li>{b}</li>")
                            body_parts.append("</ul>")
                elif raw_content:
                    body_parts.append(f"<pre style='white-space: pre-wrap;'>{raw_content}</pre>")

                html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 860px; margin: 40px auto; padding: 0 20px; color: #1e293b; background: #ffffff; }}
h1 {{ color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 24px; }}
h2 {{ color: #1e293b; margin-top: 32px; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; }}
p {{ margin-bottom: 16px; color: #334155; }}
ul {{ margin-bottom: 16px; padding-left: 24px; }}
li {{ margin-bottom: 6px; color: #334155; }}
pre {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 16px; font-size: 14px; overflow-x: auto; }}
</style>
</head>
<body>
{''.join(body_parts)}
</body>
</html>"""
                out_path.write_text(html_doc, encoding="utf-8")

            elif doc_format == "markdown":
                md_lines = [f"# {title}\n"]
                if sections:
                    for sec in sections:
                        md_lines.append(f"## {sec.get('heading', '')}\n")
                        if sec.get("body"):
                            md_lines.append(f"{sec['body']}\n")
                        for b in sec.get("bullets", []):
                            md_lines.append(f"- {b}")
                        md_lines.append("")
                elif raw_content:
                    md_lines.append(raw_content)

                out_path.write_text("\n".join(md_lines), encoding="utf-8")

            return ToolResult(
                success=True,
                data={
                    "path": str(out_path),
                    "format": doc_format,
                    "title": title,
                    "size_bytes": out_path.stat().st_size,
                },
            )

        except Exception as exc:
            return ToolResult(success=False, error=f"Document generation failed: {exc}")


class PresentationGeneratorTool(BaseTool):
    """Generate standalone responsive HTML slide presentations with keyboard navigation."""
    name = "generate_presentation"
    description = "Generate an interactive, standalone HTML presentation with keyboard arrow navigation, fullscreen support, and professional dark/light styling."
    risk_level = RiskLevel.L1

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Output HTML filepath (e.g. 'presentation.html')."},
                    "title": {"type": "string", "description": "Presentation title."},
                    "subtitle": {"type": "string", "description": "Optional presentation subtitle."},
                    "theme": {"type": "string", "enum": ["dark", "light"], "description": "Color theme (default 'dark')."},
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                                "content": {"type": "string"},
                                "code": {"type": "string"},
                            },
                            "required": ["title"],
                        },
                        "description": "List of slide objects.",
                    },
                },
                "required": ["path", "title", "slides"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        out_path = (base_dir / arguments.get("path", "presentation.html")).resolve()
        title = arguments.get("title", "Presentation")
        subtitle = arguments.get("subtitle", "")
        theme = arguments.get("theme", "dark")
        slides = arguments.get("slides", [])

        if not slides:
            return ToolResult(success=False, error="At least one slide is required")

        out_path.parent.mkdir(parents=True, exist_ok=True)

        is_dark = (theme == "dark")
        bg_color = "#0b0f19" if is_dark else "#f8fafc"
        card_bg = "#111827" if is_dark else "#ffffff"
        text_color = "#f9fafb" if is_dark else "#0f172a"
        sub_color = "#94a3b8" if is_dark else "#475569"
        accent_color = "#38bdf8" if is_dark else "#0284c7"
        border_color = "#1e293b" if is_dark else "#e2e8f0"

        slides_html = []
        # Title slide
        slides_html.append(f"""
        <div class="slide active">
            <h1 class="main-title">{title}</h1>
            {f'<p class="subtitle">{subtitle}</p>' if subtitle else ''}
            <div class="nav-hint">Press → or Space to navigate</div>
        </div>
        """)

        for s in slides:
            s_title = s.get("title", "")
            bullets_html = ""
            if s.get("bullets"):
                bullets_html = "<ul>" + "".join(f"<li>{b}</li>" for b in s["bullets"]) + "</ul>"
            content_html = f"<p class='slide-text'>{s['content']}</p>" if s.get("content") else ""
            code_html = f"<pre><code>{s['code']}</code></pre>" if s.get("code") else ""

            slides_html.append(f"""
            <div class="slide">
                <h2 class="slide-heading">{s_title}</h2>
                <div class="slide-body">
                    {content_html}
                    {bullets_html}
                    {code_html}
                </div>
            </div>
            """)

        full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: {bg_color}; color: {text_color}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; overflow: hidden; height: 100vh; display: flex; flex-direction: column; }}
.progress-bar {{ height: 4px; background: {accent_color}; width: 0%; transition: width 0.3s ease; }}
.deck-container {{ flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px; position: relative; }}
.slide {{ display: none; width: 100%; max-width: 960px; min-height: 520px; background: {card_bg}; border: 1px solid {border_color}; border-radius: 16px; padding: 60px; box-shadow: 0 20px 40px rgba(0,0,0,0.3); flex-direction: column; justify-content: center; animation: fadeIn 0.3s ease; }}
.slide.active {{ display: flex; }}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.main-title {{ font-size: 52px; font-weight: 800; color: {accent_color}; margin-bottom: 16px; letter-spacing: -1px; }}
.subtitle {{ font-size: 24px; color: {sub_color}; margin-bottom: 32px; }}
.slide-heading {{ font-size: 38px; font-weight: 700; color: {accent_color}; margin-bottom: 24px; border-bottom: 2px solid {border_color}; padding-bottom: 12px; }}
.slide-body {{ font-size: 20px; line-height: 1.6; color: {text_color}; }}
.slide-text {{ margin-bottom: 20px; color: {sub_color}; }}
ul {{ list-style: square; padding-left: 32px; margin-bottom: 24px; }}
li {{ margin-bottom: 12px; }}
pre {{ background: #000; border: 1px solid {border_color}; border-radius: 8px; padding: 20px; font-family: monospace; font-size: 16px; color: #38bdf8; overflow-x: auto; margin-top: 20px; }}
.footer-bar {{ height: 50px; display: flex; align-items: center; justify-content: space-between; padding: 0 40px; border-top: 1px solid {border_color}; font-size: 14px; color: {sub_color}; }}
.nav-hint {{ font-size: 14px; color: {sub_color}; margin-top: 20px; }}
</style>
</head>
<body>
<div class="progress-bar" id="progress"></div>
<div class="deck-container">
{''.join(slides_html)}
</div>
<div class="footer-bar">
    <span id="title-footer">{title}</span>
    <span id="counter">1 / {len(slides_html)}</span>
    <span>Use ← / → or Space | 'F' for Fullscreen</span>
</div>
<script>
let current = 0;
const slides = document.querySelectorAll('.slide');
const total = slides.length;
const counter = document.getElementById('counter');
const progress = document.getElementById('progress');

function showSlide(idx) {{
    if (idx < 0 || idx >= total) return;
    slides[current].classList.remove('active');
    current = idx;
    slides[current].classList.add('active');
    counter.textContent = (current + 1) + ' / ' + total;
    progress.style.width = (((current + 1) / total) * 100) + '%';
}}

window.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {{
        showSlide(current + 1);
    }} else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {{
        showSlide(current - 1);
    }} else if (e.key === 'f' || e.key === 'F') {{
        if (!document.fullscreenElement) document.documentElement.requestFullscreen();
        else document.exitFullscreen();
    }}
}});
showSlide(0);
</script>
</body>
</html>"""
        out_path.write_text(full_html, encoding="utf-8")

        return ToolResult(
            success=True,
            data={
                "path": str(out_path),
                "slide_count": len(slides_html),
                "open_command": f"open_browser(url='file:///{out_path.as_posix()}')",
            },
        )


class DeployAnalysisTool(BaseTool):
    """Analyzes codebase, git status, secrets, CI/CD, and deployment readiness for GitHub, Netlify, or Vercel."""
    name = "analyze_deployment"
    description = (
        "Inspect repository safety before git push, CI/CD run, or Netlify/Vercel deployment. "
        "Audits git branch/remotes, checks for secret leaks (.env not ignored), validates build scripts, "
        "and detects publish directory readiness."
    )
    risk_level = RiskLevel.L0

    def __init__(self) -> None:
        self.executor = NativeSubprocessExecutor()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project workspace path (default '.')."},
                    "target_platform": {
                        "type": "string",
                        "description": "Optional deployment platform filter: 'all', 'netlify', 'vercel', or 'github'.",
                        "default": "all",
                    },
                },
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target_path = (base_dir / arguments.get("path", ".")).resolve()
        platform = arguments.get("target_platform", "all").lower()

        if not target_path.exists():
            return ToolResult(success=False, error=f"Target path does not exist: {target_path}")

        blockers: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []
        info: dict[str, Any] = {}

        # 1. Git Repository and Branch Inspection
        is_git_repo = (target_path / ".git").exists()
        info["is_git_repo"] = is_git_repo

        if is_git_repo:
            branch_res = await self.executor.execute("git branch --show-current", cwd=target_path)
            current_branch = branch_res.stdout.strip() if branch_res.is_success else "unknown"
            info["current_branch"] = current_branch

            remote_res = await self.executor.execute("git remote -v", cwd=target_path)
            info["remotes"] = remote_res.stdout.strip().splitlines() if remote_res.is_success else []

            status_res = await self.executor.execute("git status --porcelain", cwd=target_path)
            dirty_files = [line.strip() for line in status_res.stdout.splitlines() if line.strip()]
            info["uncommitted_changes_count"] = len(dirty_files)
            info["uncommitted_files"] = dirty_files[:20]

            if not info["remotes"]:
                warnings.append("No Git remotes configured. To push to GitHub, add a remote: git remote add origin <url>")
            if len(dirty_files) > 0:
                warnings.append(f"There are {len(dirty_files)} uncommitted or untracked changes in the working tree.")
        else:
            warnings.append("Directory is not a Git repository. Run 'git init' before uploading to GitHub.")

        # 2. Secret Leak & .gitignore Safety Audit
        gitignore_path = target_path / ".gitignore"
        has_gitignore = gitignore_path.exists()
        info["has_gitignore"] = has_gitignore
        gitignore_content = gitignore_path.read_text(encoding="utf-8", errors="replace") if has_gitignore else ""

        # Check if .env or secret files exist in workspace
        env_files = list(target_path.glob(".env*"))
        for ef in env_files:
            ef_name = ef.name
            if not has_gitignore or (ef_name not in gitignore_content and ".env*" not in gitignore_content):
                blockers.append(f"CRITICAL: Secret file '{ef_name}' exists but is NOT covered in .gitignore! Add '{ef_name}' to .gitignore before pushing.")

        # Check if .env is already tracked in git
        if is_git_repo:
            tracked_check = await self.executor.execute("git ls-files .env .env.local", cwd=target_path)
            if tracked_check.stdout.strip():
                blockers.append(f"CRITICAL: Secret file(s) are actively tracked in Git: {tracked_check.stdout.strip()}. Run 'git rm --cached <file>' immediately!")

        # Scan staged/modified files for obvious token patterns
        token_regex = re.compile(r"\b(ghp_[A-Za-z0-9]{36}|nvapi-[A-Za-z0-9_-]{40,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16})\b")
        if is_git_repo:
            diff_res = await self.executor.execute("git diff HEAD", cwd=target_path)
            if diff_res.is_success and diff_res.stdout:
                matches = token_regex.findall(diff_res.stdout)
                if matches:
                    blockers.append(f"CRITICAL: Hardcoded API secret/token detected in pending git diff! Found {len(matches)} token pattern(s).")

        # 3. Build & CI/CD Readiness Inspection
        pkg_json_path = target_path / "package.json"
        pyproject_path = target_path / "pyproject.toml"
        workflows_dir = target_path / ".github" / "workflows"

        info["has_package_json"] = pkg_json_path.exists()
        info["has_pyproject"] = pyproject_path.exists()
        info["github_workflows"] = [f.name for f in workflows_dir.glob("*.y*ml")] if workflows_dir.exists() else []

        build_script_found = False
        if pkg_json_path.exists():
            try:
                pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
                scripts = pkg_data.get("scripts", {})
                info["npm_scripts"] = list(scripts.keys())
                if "build" in scripts:
                    build_script_found = True
                    info["build_command"] = "npm run build"
            except Exception:
                pass

        # Detect Publish Directory (dist, build, out, public)
        publish_dirs = [d.name for d in (target_path / "dist", target_path / "build", target_path / "out", target_path / "public") if d.is_dir()]
        info["detected_publish_dirs"] = publish_dirs

        # 4. Netlify Platform Analysis
        netlify_toml = target_path / "netlify.toml"
        info["has_netlify_toml"] = netlify_toml.exists()
        netlify_cli_installed = shutil.which("netlify") is not None
        info["netlify_cli_installed"] = netlify_cli_installed

        if platform in ("all", "netlify"):
            if not netlify_toml.exists():
                warnings.append("No netlify.toml found. Recommended config: [build] publish = 'dist' command = 'npm run build'")
            if not publish_dirs and build_script_found:
                warnings.append("Build publish directory (dist/build) has not been generated yet. Run 'npm run build' before deploying.")
            if netlify_cli_installed:
                recommendations.append("Netlify CLI ready: deploy preview with 'netlify deploy', or production with 'netlify deploy --prod --dir=dist'")
            else:
                recommendations.append("Deploy using npx: 'npx netlify deploy --prod' or install CLI with 'npm install -g netlify-cli'")

        # 5. Vercel Platform Analysis
        vercel_json = target_path / "vercel.json"
        info["has_vercel_json"] = vercel_json.exists()
        vercel_cli_installed = shutil.which("vercel") is not None
        info["vercel_cli_installed"] = vercel_cli_installed

        if platform in ("all", "vercel"):
            if vercel_cli_installed:
                recommendations.append("Vercel CLI ready: deploy preview with 'vercel', or production with 'vercel --prod'")
            else:
                recommendations.append("Deploy using npx: 'npx vercel --prod'")

        # 6. GitHub CI/CD Analysis
        if platform in ("all", "github"):
            if info["github_workflows"]:
                recommendations.append(f"GitHub Actions CI/CD workflows detected: {', '.join(info['github_workflows'])}")
            else:
                warnings.append("No GitHub Actions workflows found in .github/workflows. Push will upload code without automated remote CI.")

        safe_to_push = len(blockers) == 0 and is_git_repo
        safe_to_deploy = len(blockers) == 0

        return ToolResult(
            success=True,
            data={
                "safe_to_push": safe_to_push,
                "safe_to_deploy": safe_to_deploy,
                "blockers": blockers,
                "warnings": warnings,
                "recommendations": recommendations,
                "details": info,
            },
        )

# 6. Public exports
__all__ = [
    "CodebaseSummaryTool",
    "CodeSearchTool",
    "SymbolLookupTool",
    "SemanticSearchTool",
    "TerminalTool",
    "ReadFileTool",
    "CreateFolderTool",
    "WriteFileTool",
    "ListDirectoryTool",
    "MemoryRecallTool",
    "IDEOpenTool",
    "OpenBrowserTool",
    "ProjectEnvironmentTool",
    "GitDiffTool",
    "LaunchBackgroundProcessTool",
    "ManageBackgroundProcessTool",
    "ASTStructuralSearchTool",
    "CodeGraphQueryTool",
    "HttpProbeTool",
    "PortManagerTool",
    "FindFilesTool",
    "ScaffoldProjectTool",
    "EnvConfigInspectorTool",
    "DocumentReaderTool",
    "DocumentGeneratorTool",
    "PresentationGeneratorTool",
    "DeployAnalysisTool",
]
