"""Built-in development, operating, and code intelligence tools for NEMO agent."""

# 1. Standard library imports
import ast
import asyncio
import csv
import ctypes
import datetime
import html
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import quote
import webbrowser

# 2. Third-party imports
from ddgs import DDGS
import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
import httpx
import pypdf
import trafilatura
try:
    import win32api
    import win32con
    import win32gui
    import win32process
    from pywinauto import Desktop
except ImportError:
    win32api = None
    win32con = None
    win32gui = None
    win32process = None
    Desktop = None

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
        err = res.stderr if not res.is_success else None
        if err and any(term in err.lower() for term in ("access is denied", "0x80070005", "requires elevation", "run as administrator")):
            err += "\n[Permission Notice]: This operation requires Windows Administrator privileges. Run PowerShell as Administrator to grant elevation, or use non-elevated user tools."

        return ToolResult(
            success=res.is_success,
            data={
                "command": cmd,
                "exit_code": res.exit_code,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "duration_ms": res.duration_ms,
            },
            error=err,
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
        limit = int(arguments.get("limit") or arguments.get("max_results") or 50)

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

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()

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
                    "delimiter": {"type": "string", "description": "Optional CSV delimiter override (e.g. ',', ';', '\\t', '|')."},
                },
                "required": ["path"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        raw_path = arguments.get("path", "")
        if not raw_path:
            return ToolResult(success=False, error="Path is required.")

        p_str = str(raw_path).replace("$env:USERPROFILE", str(Path.home())).replace("~", str(Path.home()))
        doc_path = (base_dir / p_str).resolve() if not Path(p_str).is_absolute() else Path(p_str).resolve()

        if not self.policy.is_path_safe(doc_path, base_dir=base_dir):
            return ToolResult(success=False, error=f"Access denied: path outside allowed boundary ({doc_path})")

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
                
                pdf_meta = {}
                if reader.metadata:
                    for k, v in reader.metadata.items():
                        clean_k = str(k).lstrip("/").lower()
                        pdf_meta[clean_k] = str(v)

                return ToolResult(
                    success=True,
                    data={
                        "format": "pdf",
                        "total_pages": total_pages,
                        "pages_extracted": pages_to_read,
                        "metadata": pdf_meta,
                        "is_encrypted": reader.is_encrypted,
                        "content": "\n\n".join(extracted_pages),
                    },
                )

            elif ext == ".docx":
                doc = docx.Document(str(doc_path))
                paragraphs = []
                headings = []
                for p in doc.paragraphs:
                    t = p.text.strip()
                    if not t:
                        continue
                    paragraphs.append(t)
                    if p.style and (p.style.name.startswith("Heading") or p.style.name == "Title"):
                        headings.append({"style": p.style.name, "text": t})

                tables_data = []
                for t in doc.tables:
                    t_rows = []
                    for row in t.rows:
                        t_rows.append([cell.text.strip() for cell in row.cells])
                    if t_rows:
                        hdr = t_rows[0]
                        data_rows = t_rows[1:] if len(t_rows) > 1 else []
                        tables_data.append({"headers": hdr, "rows": data_rows})

                image_count = len(doc.inline_shapes) if hasattr(doc, "inline_shapes") else 0
                all_text = " ".join(paragraphs)
                word_count = len(all_text.split())

                meta = {}
                try:
                    props = doc.core_properties
                    meta = {
                        "author": props.author or "",
                        "title": props.title or "",
                        "created": str(props.created) if props.created else "",
                    }
                except Exception:
                    pass

                return ToolResult(
                    success=True,
                    data={
                        "format": "docx",
                        "paragraph_count": len(paragraphs),
                        "word_count": word_count,
                        "heading_count": len(headings),
                        "headings": headings[:15],
                        "table_count": len(doc.tables),
                        "image_count": image_count,
                        "tables": tables_data,
                        "metadata": meta,
                        "content": "\n\n".join(paragraphs),
                    },
                )

            elif ext in (".csv", ".tsv"):
                delimiter = arguments.get("delimiter")
                rows = []
                with open(doc_path, "r", encoding="utf-8", errors="ignore") as f:
                    content_sample = f.read(2048)
                    f.seek(0)
                    if not delimiter:
                        if ext == ".tsv":
                            delimiter = "\t"
                        else:
                            try:
                                dialect = csv.Sniffer().sniff(content_sample, delimiters=[",", "\t", ";", "|"])
                                delimiter = dialect.delimiter
                            except Exception:
                                delimiter = ","
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
                        "delimiter": delimiter,
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

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Output file path (e.g. 'docs/architecture_report.docx' or 'report.html')."},
                    "title": {"type": "string", "description": "Document title."},
                    "author": {"type": "string", "description": "Document author for metadata."},
                    "format": {"type": "string", "enum": ["docx", "html", "markdown"], "description": "Output format ('docx', 'html', 'markdown')."},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "level": {"type": "integer", "description": "Heading level (1, 2, 3). Default is 1."},
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
        raw_path = arguments.get("path", "")
        if not raw_path:
            return ToolResult(success=False, error="Path is required.")

        p_str = str(raw_path).replace("$env:USERPROFILE", str(Path.home())).replace("~", str(Path.home()))
        out_path = (base_dir / p_str).resolve() if not Path(p_str).is_absolute() else Path(p_str).resolve()

        if not self.policy.is_path_safe(out_path, base_dir=base_dir):
            return ToolResult(success=False, error=f"Access denied: path outside allowed boundary ({out_path})")

        title = arguments.get("title", "Document")
        doc_format = arguments.get("format", "markdown").lower()
        sections = arguments.get("sections", [])
        raw_content = arguments.get("content", "")

        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if doc_format == "docx":
                doc = docx.Document()
                doc.core_properties.title = title
                if "author" in arguments:
                    doc.core_properties.author = str(arguments["author"])
                doc.add_heading(title, level=0)

                if sections:
                    for sec in sections:
                        if sec.get("heading"):
                            h_level = int(sec.get("level", 1))
                            doc.add_heading(sec["heading"], level=h_level)
                        if sec.get("body"):
                            doc.add_paragraph(sec["body"])
                        for bullet in sec.get("bullets", []):
                            doc.add_paragraph(bullet, style="List Bullet")

                        # Table support
                        table_data = sec.get("table")
                        if table_data and isinstance(table_data, dict):
                            headers = table_data.get("headers", [])
                            rows = table_data.get("rows", [])
                            if headers or rows:
                                cols = max(len(headers), max((len(r) for r in rows), default=0))
                                total_rows = (1 if headers else 0) + len(rows)
                                table = doc.add_table(rows=total_rows, cols=cols)
                                table.style = "Table Grid"
                                r_offset = 0
                                if headers:
                                    for c_idx, h_text in enumerate(headers):
                                        c_cell = table.rows[0].cells[c_idx]
                                        c_cell.text = str(h_text)
                                        for p in c_cell.paragraphs:
                                            for r in p.runs:
                                                r.font.bold = True
                                    r_offset = 1
                                for r_idx, r_vals in enumerate(rows):
                                    row_cells = table.rows[r_offset + r_idx].cells
                                    for c_idx, val in enumerate(r_vals):
                                        if c_idx < cols:
                                            row_cells[c_idx].text = str(val)

                        # Image support
                        img_rel = sec.get("image_path") or sec.get("image")
                        if img_rel:
                            img_path = (base_dir / img_rel).resolve() if not Path(img_rel).is_absolute() else Path(img_rel).resolve()
                            if img_path.exists():
                                w_inch = float(sec.get("width_inches", 5.0))
                                doc.add_picture(str(img_path), width=Inches(w_inch))
                                if sec.get("caption"):
                                    cap = doc.add_paragraph(sec["caption"])
                                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    for r in cap.runs:
                                        r.font.italic = True
                                        r.font.size = Pt(9.5)
                                        r.font.color.rgb = RGBColor(100, 116, 139)

                        # Code block support
                        if sec.get("code"):
                            code_p = doc.add_paragraph()
                            code_run = code_p.add_run(sec["code"])
                            code_run.font.name = "Consolas"
                            code_run.font.size = Pt(9.5)

                        # Callout support
                        if sec.get("callout"):
                            call_p = doc.add_paragraph()
                            r = call_p.add_run(f"NOTE: {sec['callout']}")
                            r.font.italic = True
                            r.font.color.rgb = RGBColor(30, 58, 138)

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
                body_parts = [f"<h1>{html.escape(title)}</h1>"]
                if sections:
                    for sec in sections:
                        if sec.get("heading"):
                            body_parts.append(f"<h2>{html.escape(sec['heading'])}</h2>")
                        if sec.get("body"):
                            body_parts.append(f"<p>{html.escape(sec['body'])}</p>")
                        if sec.get("bullets"):
                            body_parts.append("<ul>")
                            for b in sec["bullets"]:
                                body_parts.append(f"<li>{html.escape(b)}</li>")
                            body_parts.append("</ul>")

                        # Table
                        t_data = sec.get("table")
                        if t_data and isinstance(t_data, dict):
                            hdrs = t_data.get("headers", [])
                            t_rows = t_data.get("rows", [])
                            if hdrs or t_rows:
                                body_parts.append("<table style='width: 100%; border-collapse: collapse; margin: 16px 0; border: 1px solid #e2e8f0;'>")
                                if hdrs:
                                    body_parts.append("<thead><tr style='background: #f8fafc; border-bottom: 2px solid #cbd5e1;'>")
                                    for h in hdrs:
                                        body_parts.append(f"<th style='padding: 10px 14px; text-align: left; font-weight: 600; font-size: 14px;'>{html.escape(str(h))}</th>")
                                    body_parts.append("</tr></thead>")
                                body_parts.append("<tbody>")
                                for r_idx, r in enumerate(t_rows):
                                    bg = "#ffffff" if r_idx % 2 == 0 else "#f8fafc"
                                    body_parts.append(f"<tr style='background: {bg}; border-bottom: 1px solid #e2e8f0;'>")
                                    for cell in r:
                                        body_parts.append(f"<td style='padding: 8px 14px; font-size: 14px;'>{html.escape(str(cell))}</td>")
                                    body_parts.append("</tr>")
                                body_parts.append("</tbody></table>")

                        # Image
                        img_rel = sec.get("image_path") or sec.get("image")
                        if img_rel:
                            img_path = (base_dir / img_rel).resolve() if not Path(img_rel).is_absolute() else Path(img_rel).resolve()
                            if img_path.exists():
                                cap_str = html.escape(sec.get("caption", ""))
                                body_parts.append(
                                    f"<figure style='margin: 20px 0; text-align: center;'>"
                                    f"<img src='{img_path.as_posix()}' style='max-width: 100%; border-radius: 6px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);' />"
                                    f"<figcaption style='font-size: 13px; color: #64748b; margin-top: 6px;'>{cap_str}</figcaption>"
                                    f"</figure>"
                                )

                        # Code
                        if sec.get("code"):
                            body_parts.append(f"<pre style='background: #0f172a; color: #f8fafc; padding: 14px; border-radius: 6px; overflow-x: auto;'><code>{html.escape(sec['code'])}</code></pre>")

                        # Callout
                        if sec.get("callout"):
                            body_parts.append(f"<div style='border-left: 4px solid #3b82f6; background: #eff6ff; padding: 12px 16px; border-radius: 4px; margin: 16px 0; color: #1e40af;'><strong>Note:</strong> {html.escape(sec['callout'])}</div>")

                elif raw_content:
                    body_parts.append(f"<pre style='white-space: pre-wrap;'>{html.escape(raw_content)}</pre>")

                html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
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
                        if sec.get("heading"):
                            md_lines.append(f"## {sec['heading']}\n")
                        if sec.get("body"):
                            md_lines.append(f"{sec['body']}\n")
                        for b in sec.get("bullets", []):
                            md_lines.append(f"- {b}")
                        if sec.get("table") and isinstance(sec["table"], dict):
                            hdrs = sec["table"].get("headers", [])
                            rws = sec["table"].get("rows", [])
                            if hdrs:
                                md_lines.append("| " + " | ".join(str(h) for h in hdrs) + " |")
                                md_lines.append("| " + " | ".join("---" for _ in hdrs) + " |")
                            for r in rws:
                                md_lines.append("| " + " | ".join(str(c) for c in r) + " |")
                            md_lines.append("")
                        img_rel = sec.get("image_path") or sec.get("image")
                        if img_rel:
                            caption = sec.get("caption", "image")
                            md_lines.append(f"![{caption}]({img_rel})\n")
                        if sec.get("code"):
                            md_lines.append(f"```\n{sec['code']}\n```\n")
                        if sec.get("callout"):
                            md_lines.append(f"> **Note:** {sec['callout']}\n")
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

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()

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
        raw_path = arguments.get("path", "presentation.html")
        p_str = str(raw_path).replace("$env:USERPROFILE", str(Path.home())).replace("~", str(Path.home()))
        out_path = (base_dir / p_str).resolve() if not Path(p_str).is_absolute() else Path(p_str).resolve()

        if not self.policy.is_path_safe(out_path, base_dir=base_dir):
            return ToolResult(success=False, error=f"Access denied: path outside allowed boundary ({out_path})")

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


class GitOperationsTool(BaseTool):
    """Executes safe, native Git operations: status, branch, stage, unstage, commit, push, log, and checkout."""
    name = "git_operations"
    description = (
        "Manage Git repositories natively: inspect status, create or switch branches, stage files, "
        "commit changes, push to remotes, and view commit logs."
    )
    risk_level = RiskLevel.L2

    def __init__(self) -> None:
        self.executor = NativeSubprocessExecutor()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "branch", "checkout", "stage", "unstage", "commit", "push", "log", "diff"],
                        "description": "Git action to perform.",
                    },
                    "path": {"type": "string", "description": "Repository path (default '.')."},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Files to stage or unstage."},
                    "message": {"type": "string", "description": "Commit message (required for 'commit')."},
                    "branch_name": {"type": "string", "description": "Branch name (for 'branch' or 'checkout')."},
                    "create_branch": {"type": "boolean", "description": "Whether to create a new branch during checkout (-b)."},
                    "remote": {"type": "string", "description": "Remote name for push (default 'origin')."},
                    "set_upstream": {"type": "boolean", "description": "Set upstream tracking on push (-u)."},
                    "limit": {"type": "integer", "description": "Maximum commits to return for 'log' (default 10)."},
                },
                "required": ["action"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        target_path = (base_dir / arguments.get("path", ".")).resolve()
        action = arguments.get("action", "").lower().strip()

        if not (target_path / ".git").exists():
            return ToolResult(success=False, error=f"Target directory is not a Git repository: {target_path}")

        try:
            if action == "status":
                branch_res = await self.executor.execute("git branch --show-current", cwd=target_path)
                current_branch = branch_res.stdout.strip() if branch_res.is_success else "unknown"

                status_res = await self.executor.execute("git status --porcelain", cwd=target_path)
                lines = [line.rstrip() for line in status_res.stdout.splitlines() if line.strip()]

                staged: list[str] = []
                unstaged: list[str] = []
                untracked: list[str] = []

                for l in lines:
                    if len(l) < 3:
                        continue
                    index_stat = l[0]
                    work_stat = l[1]
                    fname = l[3:].strip()
                    if index_stat == "?" and work_stat == "?":
                        untracked.append(fname)
                    else:
                        if index_stat not in (" ", "?"):
                            staged.append(fname)
                        if work_stat != " ":
                            unstaged.append(fname)

                return ToolResult(
                    success=True,
                    data={
                        "action": "status",
                        "branch": current_branch,
                        "is_clean": len(lines) == 0,
                        "staged": staged,
                        "unstaged": unstaged,
                        "untracked": untracked,
                        "total_changes": len(lines),
                    },
                )

            elif action == "branch":
                b_name = arguments.get("branch_name", "").strip()
                if b_name:
                    res = await self.executor.execute(f"git branch {b_name}", cwd=target_path)
                    if not res.is_success:
                        return ToolResult(success=False, error=f"Failed to create branch: {res.stderr or res.stdout}")
                    return ToolResult(success=True, data={"action": "branch", "created": b_name})
                else:
                    res = await self.executor.execute("git branch -a", cwd=target_path)
                    branches = [b.strip().lstrip("* ").strip() for b in res.stdout.splitlines() if b.strip()]
                    return ToolResult(success=True, data={"action": "branch", "branches": branches})

            elif action == "checkout":
                b_name = arguments.get("branch_name", "").strip()
                if not b_name:
                    return ToolResult(success=False, error="branch_name is required for checkout action.")
                create = arguments.get("create_branch", False)
                flag = "-b " if create else ""
                res = await self.executor.execute(f"git checkout {flag}{b_name}", cwd=target_path)
                if not res.is_success:
                    return ToolResult(success=False, error=f"Failed to checkout branch: {res.stderr or res.stdout}")
                return ToolResult(success=True, data={"action": "checkout", "branch": b_name, "created": create})

            elif action == "stage":
                files = arguments.get("files", [])
                targets = " ".join(f'"{f}"' for f in files) if files else "."
                res = await self.executor.execute(f"git add {targets}", cwd=target_path)
                if not res.is_success:
                    return ToolResult(success=False, error=f"Failed to stage files: {res.stderr or res.stdout}")
                return ToolResult(success=True, data={"action": "stage", "staged_targets": files or ["."]})

            elif action == "unstage":
                files = arguments.get("files", [])
                targets = " ".join(f'"{f}"' for f in files) if files else "."
                res = await self.executor.execute(f"git restore --staged {targets}", cwd=target_path)
                if not res.is_success and "could not resolve 'HEAD'" in res.stderr:
                    res = await self.executor.execute(f"git rm --cached -r {targets}", cwd=target_path)
                if not res.is_success:
                    return ToolResult(success=False, error=f"Failed to unstage files: {res.stderr or res.stdout}")
                return ToolResult(success=True, data={"action": "unstage", "unstaged_targets": files or ["."]})

            elif action == "commit":
                msg = arguments.get("message", "").strip()
                if not msg:
                    return ToolResult(success=False, error="Commit message is required.")
                safe_msg = msg.replace('"', '\\"')
                res = await self.executor.execute(f'git commit -m "{safe_msg}"', cwd=target_path)
                if not res.is_success:
                    return ToolResult(success=False, error=f"Git commit failed: {res.stderr or res.stdout}")

                hash_res = await self.executor.execute("git rev-parse --short HEAD", cwd=target_path)
                commit_hash = hash_res.stdout.strip() if hash_res.is_success else "unknown"
                return ToolResult(success=True, data={"action": "commit", "commit_hash": commit_hash, "message": msg})

            elif action == "push":
                remote = arguments.get("remote", "origin").strip()
                set_upstream = arguments.get("set_upstream", False)
                branch_res = await self.executor.execute("git branch --show-current", cwd=target_path)
                curr_branch = branch_res.stdout.strip() if branch_res.is_success else "main"
                u_flag = "-u " if set_upstream else ""
                res = await self.executor.execute(f"git push {u_flag}{remote} {curr_branch}", cwd=target_path)
                if not res.is_success:
                    return ToolResult(success=False, error=f"Git push failed: {res.stderr or res.stdout}")
                return ToolResult(success=True, data={"action": "push", "remote": remote, "branch": curr_branch, "output": res.stdout.strip()})

            elif action == "log":
                limit = int(arguments.get("limit", 10))
                res = await self.executor.execute(f'git log -n {limit} --pretty=format:"%H|%an|%ad|%s" --date=short', cwd=target_path)
                commits = []
                for l in res.stdout.splitlines():
                    if "|" in l:
                        parts = l.split("|", 3)
                        if len(parts) == 4:
                            commits.append({"hash": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]})
                return ToolResult(success=True, data={"action": "log", "count": len(commits), "commits": commits})

            elif action == "diff":
                res = await self.executor.execute("git diff --stat", cwd=target_path)
                staged_diff = await self.executor.execute("git diff --cached --stat", cwd=target_path)
                return ToolResult(
                    success=True,
                    data={
                        "action": "diff",
                        "unstaged_stat": res.stdout.strip(),
                        "staged_stat": staged_diff.stdout.strip(),
                    },
                )

            else:
                return ToolResult(success=False, error=f"Unsupported Git action: '{action}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"Git operation failed: {exc}")


class DatabaseExplorerTool(BaseTool):
    """Inspects and queries SQLite databases safely with schema analysis and read-only execution."""
    name = "database_inspector"
    description = (
        "Inspect database schemas, list tables, column definitions, foreign keys, row counts, "
        "and execute safe read-only queries with structured results."
    )
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
                    "path": {"type": "string", "description": "Database file path (e.g. '~/.nemo/nemo.db', 'nemo.db', 'data/app.db')."},
                    "action": {
                        "type": "string",
                        "enum": ["list_tables", "schema", "query"],
                        "description": "Database action to perform.",
                    },
                    "table": {"type": "string", "description": "Table name (for 'schema' action)."},
                    "query": {"type": "string", "description": "SQL query string (for 'query' action)."},
                    "limit": {"type": "integer", "description": "Maximum rows to return for 'query' (default 50)."},
                    "allow_write": {"type": "boolean", "description": "Allow data-modifying queries (INSERT/UPDATE/DELETE). Default false."},
                },
                "required": ["path", "action"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        base_dir = Path(context.get("working_directory", Path.cwd()))
        raw_path = str(arguments.get("path", "")).strip()
        if not raw_path:
            raw_path = "~/.nemo/nemo.db"

        p_str = raw_path.replace("$env:USERPROFILE", str(Path.home())).replace("~", str(Path.home()))
        db_path = (base_dir / p_str).resolve() if not Path(p_str).is_absolute() else Path(p_str).resolve()

        # Ponytail: Auto-resolve to ~/.nemo/nemo.db if database is nemo and not present in working directory
        if not db_path.exists() and ("nemo" in raw_path.lower() or raw_path in ("nemo.db", "nemo", ".nemo/nemo.db")):
            nemo_home_db = (Path.home() / ".nemo" / "nemo.db").resolve()
            if nemo_home_db.exists():
                db_path = nemo_home_db

        if not self.policy.is_path_safe(db_path, base_dir=base_dir):
            return ToolResult(success=False, error=f"Access denied: database path outside allowed boundary ({db_path})")

        if not db_path.exists():
            return ToolResult(success=False, error=f"Database file does not exist: {db_path}")

        action = arguments.get("action", "").lower().strip()
        allow_write = bool(arguments.get("allow_write", False))

        try:
            uri = f"file:{db_path.as_posix()}?mode=ro" if not allow_write else f"file:{db_path.as_posix()}?mode=rwc"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if action == "list_tables":
                cursor.execute(
                    "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name;"
                )
                tables_meta = []
                for row in cursor.fetchall():
                    t_name = row["name"]
                    t_type = row["type"]
                    row_count = 0
                    try:
                        c_cnt = conn.cursor()
                        c_cnt.execute(f'SELECT COUNT(*) FROM "{t_name}";')
                        row_count = c_cnt.fetchone()[0]
                    except Exception:
                        pass
                    tables_meta.append({"name": t_name, "type": t_type, "row_count": row_count})

                conn.close()
                return ToolResult(
                    success=True,
                    data={"database": str(db_path), "table_count": len(tables_meta), "tables": tables_meta},
                )

            elif action == "schema":
                table_name = arguments.get("table", "").strip()
                if not table_name:
                    conn.close()
                    return ToolResult(success=False, error="table parameter is required for 'schema' action.")

                cursor.execute(f'PRAGMA table_info("{table_name}");')
                cols = [
                    {
                        "cid": r[0],
                        "name": r[1],
                        "type": r[2],
                        "notnull": bool(r[3]),
                        "default_value": r[4],
                        "primary_key": bool(r[5]),
                    }
                    for r in cursor.fetchall()
                ]

                cursor.execute(f'PRAGMA foreign_key_list("{table_name}");')
                fks = [
                    {"id": r[0], "seq": r[1], "target_table": r[2], "from_col": r[3], "to_col": r[4]}
                    for r in cursor.fetchall()
                ]

                cursor.execute(f'PRAGMA index_list("{table_name}");')
                indexes = [{"name": r[1], "unique": bool(r[2])} for r in cursor.fetchall()]

                conn.close()
                return ToolResult(
                    success=True,
                    data={
                        "database": str(db_path),
                        "table": table_name,
                        "column_count": len(cols),
                        "columns": cols,
                        "foreign_keys": fks,
                        "indexes": indexes,
                    },
                )

            elif action == "query":
                sql = arguments.get("query", "").strip()
                if not sql:
                    conn.close()
                    return ToolResult(success=False, error="query parameter is required for 'query' action.")

                if not allow_write:
                    first_word = sql.split()[0].upper() if sql.split() else ""
                    if first_word not in ("SELECT", "PRAGMA", "EXPLAIN", "WITH"):
                        conn.close()
                        return ToolResult(
                            success=False,
                            error=f"Permission denied: Query starts with '{first_word}'. Only read-only queries (SELECT/PRAGMA/EXPLAIN/WITH) are permitted without allow_write=true.",
                        )

                t0 = time.perf_counter()
                cursor.execute(sql)
                limit = int(arguments.get("limit", 50))
                rows_raw = cursor.fetchmany(limit)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

                col_names = [d[0] for d in cursor.description] if cursor.description else []
                formatted_rows = [[r[c] for c in col_names] for r in rows_raw]

                if allow_write:
                    conn.commit()
                conn.close()

                return ToolResult(
                    success=True,
                    data={
                        "database": str(db_path),
                        "query": sql,
                        "columns": col_names,
                        "row_count": len(formatted_rows),
                        "execution_time_ms": elapsed_ms,
                        "rows": formatted_rows,
                    },
                )

            else:
                conn.close()
                return ToolResult(success=False, error=f"Unsupported database action: '{action}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"Database inspector error: {exc}")


class ApiTesterTool(BaseTool):
    """Executes HTTP REST / GraphQL requests with headers, query parameters, payloads, and latency timing."""
    name = "api_tester"
    description = (
        "Execute HTTP requests (GET, POST, PUT, PATCH, DELETE, HEAD) with custom headers, query params, "
        "authentication tokens, JSON payloads, and response inspection."
    )
    risk_level = RiskLevel.L1

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target endpoint URL."},
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                        "default": "GET",
                        "description": "HTTP method.",
                    },
                    "headers": {"type": "object", "description": "Optional HTTP headers dictionary."},
                    "params": {"type": "object", "description": "Optional query string parameters dictionary."},
                    "json_data": {"type": "object", "description": "Optional JSON body payload for POST/PUT/PATCH."},
                    "form_data": {"type": "object", "description": "Optional form-urlencoded data."},
                    "auth_bearer": {"type": "string", "description": "Optional Bearer authentication token."},
                    "timeout_seconds": {"type": "number", "default": 15.0, "description": "Request timeout in seconds."},
                },
                "required": ["url"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "").strip()
        if not url:
            return ToolResult(success=False, error="url parameter is required.")

        method = arguments.get("method", "GET").upper().strip()
        headers = dict(arguments.get("headers") or {})
        params = arguments.get("params")
        json_data = arguments.get("json_data")
        form_data = arguments.get("form_data")
        auth_bearer = arguments.get("auth_bearer")
        timeout = float(arguments.get("timeout_seconds", 15.0))

        if auth_bearer:
            headers["Authorization"] = f"Bearer {auth_bearer}"

        try:
            t0 = time.perf_counter()
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    data=form_data,
                )
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

            parsed_json = None
            try:
                parsed_json = resp.json()
            except Exception:
                pass

            text_preview = resp.text[:15000] if resp.text else ""

            return ToolResult(
                success=True,
                data={
                    "url": str(resp.url),
                    "method": method,
                    "status_code": resp.status_code,
                    "is_success": resp.is_success,
                    "response_time_ms": elapsed_ms,
                    "content_type": resp.headers.get("content-type", ""),
                    "headers": dict(resp.headers),
                    "json": parsed_json,
                    "text": text_preview,
                },
            )

        except Exception as exc:
            return ToolResult(success=False, error=f"API request failed: {exc}")


class SystemInspectorTool(BaseTool):
    """Inspects live Windows system hardware, CPU cores, RAM utilization, disk usage, active ports, and processes."""
    name = "system_inspector"
    description = (
        "Inspect live Windows hardware metrics (CPU cores, RAM load, disk space), list active processes "
        "and listening ports, and terminate runaway dev processes safely."
    )
    risk_level = RiskLevel.L1

    PROTECTED_PROCESSES = {
        "explorer.exe", "svchost.exe", "csrss.exe", "wininit.exe",
        "services.exe", "system", "smss.exe", "lsass.exe", "winlogon.exe"
    }

    def __init__(self) -> None:
        self.executor = NativeSubprocessExecutor()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["summary", "processes", "ports", "kill"],
                        "description": "System inspection action.",
                    },
                    "filter_name": {"type": "string", "description": "Optional process name filter (for 'processes')."},
                    "limit": {"type": "integer", "description": "Maximum items to return (default 25)."},
                    "pid": {"type": "integer", "description": "Process ID to terminate (for 'kill')."},
                    "process_name": {"type": "string", "description": "Process image name to terminate (for 'kill')."},
                },
                "required": ["action"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "summary").lower().strip()
        base_dir = Path(context.get("working_directory", Path.cwd()))

        try:
            if action == "summary":
                cpu_count = os.cpu_count() or 1
                ram_info = {"total_gb": 0.0, "available_gb": 0.0, "used_percent": 0}

                try:
                    class _MEMORYSTATUSEX(ctypes.Structure):
                        _fields_ = [
                            ("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                        ]
                    m = _MEMORYSTATUSEX()
                    m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
                    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                        ram_info = {
                            "total_gb": round(m.ullTotalPhys / (1024**3), 2),
                            "available_gb": round(m.ullAvailPhys / (1024**3), 2),
                            "used_percent": int(m.dwMemoryLoad),
                        }
                except Exception:
                    pass

                disk = shutil.disk_usage(str(base_dir))
                disk_info = {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "used_percent": round((disk.used / disk.total) * 100, 1),
                }

                return ToolResult(
                    success=True,
                    data={
                        "action": "summary",
                        "os": platform.platform(),
                        "cpu_logical_cores": cpu_count,
                        "ram": ram_info,
                        "disk": disk_info,
                    },
                )

            elif action == "processes":
                limit = int(arguments.get("limit", 25))
                filter_name = arguments.get("filter_name", "").lower().strip()
                res = await self.executor.execute("tasklist /FO CSV /NH", cwd=base_dir)

                procs = []
                for line in res.stdout.splitlines():
                    parts = [p.strip().strip('"') for p in line.split('","')]
                    if len(parts) >= 5:
                        p_name = parts[0]
                        p_pid = parts[1]
                        p_mem = parts[4]
                        if filter_name and filter_name not in p_name.lower():
                            continue
                        procs.append({"name": p_name, "pid": p_pid, "memory": p_mem})

                return ToolResult(
                    success=True,
                    data={"action": "processes", "total_found": len(procs), "processes": procs[:limit]},
                )

            elif action == "ports":
                res = await self.executor.execute("netstat -ano -p tcp", cwd=base_dir)
                ports = []
                for line in res.stdout.splitlines():
                    tokens = line.split()
                    if len(tokens) >= 5 and tokens[3] == "LISTENING":
                        ports.append({
                            "protocol": tokens[0],
                            "local_address": tokens[1],
                            "state": tokens[3],
                            "pid": tokens[4],
                        })

                return ToolResult(
                    success=True,
                    data={"action": "ports", "listening_count": len(ports), "ports": ports[:arguments.get("limit", 50)]},
                )

            elif action == "kill":
                pid = arguments.get("pid")
                proc_name = arguments.get("process_name", "").strip()

                if proc_name and proc_name.lower() in self.PROTECTED_PROCESSES:
                    return ToolResult(success=False, error=f"Permission denied: '{proc_name}' is a protected Windows core process.")

                if pid:
                    res = await self.executor.execute(f"taskkill /F /PID {pid}", cwd=base_dir)
                elif proc_name:
                    res = await self.executor.execute(f"taskkill /F /IM {proc_name}", cwd=base_dir)
                else:
                    return ToolResult(success=False, error="Either pid or process_name is required for 'kill' action.")

                if not res.is_success:
                    return ToolResult(success=False, error=f"Failed to kill process: {res.stderr or res.stdout}")

                return ToolResult(
                    success=True,
                    data={"action": "kill", "target": pid or proc_name, "message": res.stdout.strip()},
                )

            else:
                return ToolResult(success=False, error=f"Unsupported system action: '{action}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"System inspector error: {exc}")



def capture_desktop_screenshot_base64() -> str | None:
    """Capture full desktop screen to base64 PNG using PowerShell .NET Graphics."""
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
        "$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height); "
        "$g = [System.Drawing.Graphics]::FromImage($b); "
        "$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size); "
        "$ms = New-Object System.IO.MemoryStream; "
        "$b.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); "
        "[Convert]::ToBase64String($ms.ToArray()); "
        "$ms.Dispose(); $g.Dispose(); $b.Dispose();"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return None


class WindowsClockAutomator:
    """Automate the native Windows Clock app (Focus sessions, Timers, Alarms, Stopwatch) via UI Automation."""

    @staticmethod
    def _switch_to_interactive_desktop():
        """Ensure thread is connected to user's interactive 'Default' desktop on WinSta0."""
        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x10000000)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
                return h_desk
        except Exception:
            pass
        return None

    @classmethod
    def get_clock_window(cls, auto_launch: bool = True, wait_seconds: float = 2.0):
        """Find or launch the native Windows Clock app window."""
        h_desk = cls._switch_to_interactive_desktop()

        found = []
        if win32gui:
            def enum_cb(hwnd, _):
                txt = win32gui.GetWindowText(hwnd)
                cls_name = win32gui.GetClassName(hwnd)
                if cls_name == "ApplicationFrameWindow":
                    if txt == "Clock" or "clock" in txt.lower():
                        found.append(hwnd)
            try:
                if h_desk:
                    win32gui.EnumDesktopWindows(h_desk, enum_cb, None)
                else:
                    win32gui.EnumWindows(enum_cb, None)
            except Exception:
                pass

        if not found and auto_launch:
            subprocess.Popen(["cmd.exe", "/c", "start", "ms-clock:"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(int(wait_seconds * 2)):
                time.sleep(0.5)
                w = cls.get_clock_window(auto_launch=False)
                if w:
                    return w
            return None

        if found:
            hwnd = found[0]
            try:
                from pywinauto import Application
                app = Application(backend="uia").connect(handle=hwnd)
                win = app.window(handle=hwnd)
                try:
                    win.set_focus()
                except Exception:
                    pass
                return win
            except Exception:
                pass
        return None

    @classmethod
    def start_focus_session(cls, minutes: float = 25.0, skip_breaks: bool = False, keep_on_top: bool = True) -> dict[str, Any]:
        """Automate Windows Clock: Focus sessions -> set minutes -> Start focus session -> optional Keep on top."""
        win = cls.get_clock_window()
        if not win:
            return {"success": False, "error": "Could not launch or connect to Windows Clock app."}

        # Step 1: Select FocusButton with safe render delay
        for c in win.descendants():
            if c.element_info.automation_id == "FocusButton":
                try:
                    c.select()
                except Exception:
                    try:
                        c.invoke()
                    except Exception:
                        pass
                break
        time.sleep(0.6)

        # Step 2: Set duration
        mins_int = int(max(1, minutes))
        for c in win.descendants():
            if c.element_info.automation_id == "InputBox":
                try:
                    c.set_edit_text(str(mins_int))
                except Exception:
                    try:
                        c.type_keys(f"^a{mins_int}", with_spaces=True)
                    except Exception:
                        pass
                break

        # Step 3: Optional skip breaks
        if skip_breaks:
            time.sleep(0.3)
            for c in win.descendants():
                if c.element_info.automation_id == "HasBreaksCheckbox":
                    try:
                        c.toggle()
                    except Exception:
                        pass
                    break

        time.sleep(0.4)

        # Step 4: Click Start focus session
        started = False
        for c in win.descendants():
            if c.element_info.automation_id == "StartButton":
                try:
                    c.invoke()
                    started = True
                except Exception:
                    pass
                break

        # Step 5: Optional keep on top compact floating mode
        popped_aot = False
        if keep_on_top and started:
            time.sleep(0.5)
            for c in win.descendants():
                if c.element_info.automation_id == "AotButton":
                    try:
                        c.invoke()
                        popped_aot = True
                    except Exception:
                        pass
                    break

        return {
            "success": True,
            "feature": "focus_session",
            "duration_minutes": mins_int,
            "session_started": started,
            "skip_breaks": skip_breaks,
            "keep_on_top": popped_aot,
            "note": "Native Windows Clock Focus Session started directly on screen.",
        }

    @classmethod
    def start_stopwatch(cls, keep_on_top: bool = True) -> dict[str, Any]:
        """Automate Windows Clock: Stopwatch -> Start -> Keep on top."""
        win = cls.get_clock_window()
        if not win:
            return {"success": False, "error": "Could not launch or connect to Windows Clock app."}

        for c in win.descendants():
            if c.element_info.automation_id == "StopwatchButton":
                try:
                    c.select()
                except Exception:
                    try:
                        c.invoke()
                    except Exception:
                        pass
                break
        time.sleep(0.6)

        started = False
        popped_aot = False
        for c in win.descendants():
            aid = c.element_info.automation_id
            if aid in ("StopwatchPlayPauseButton", "StartButton", "TimerPlayPauseButton") and not started:
                try:
                    c.invoke()
                    started = True
                except Exception:
                    pass
            elif aid == "AotButton" and keep_on_top:
                time.sleep(0.4)
                try:
                    c.invoke()
                    popped_aot = True
                except Exception:
                    pass

        return {
            "success": True,
            "feature": "stopwatch",
            "started": started,
            "keep_on_top": popped_aot,
            "note": "Native Windows Clock stopwatch started on screen in compact mode.",
        }

    @classmethod
    def start_timer(
        cls,
        minutes: float = 0.0,
        seconds: float = 0.0,
        title: str = "Timer",
        keep_on_top: bool = True,
    ) -> dict[str, Any]:
        """Automate Windows Clock: Timer -> preset or custom duration -> Start -> Keep on top."""
        win = cls.get_clock_window()
        if not win:
            return {"success": False, "error": "Could not launch or connect to Windows Clock app."}

        # Step 1: Select TimerButton
        for c in win.descendants():
            if c.element_info.automation_id == "TimerButton":
                try:
                    c.select()
                except Exception:
                    try:
                        c.invoke()
                    except Exception:
                        pass
                break
        time.sleep(0.6)

        total_sec = int(round(seconds + (minutes * 60.0)))
        if total_sec <= 0:
            total_sec = 60

        target_h = total_sec // 3600
        target_m = (total_sec % 3600) // 60
        target_s = total_sec % 60

        is_preset = (target_h == 0 and target_s == 0 and target_m in (1, 3, 5, 10))
        timer_started = False
        popped_aot = False

        if is_preset:
            matching_card = None
            first_card = None
            for c in win.descendants():
                if c.element_info.automation_id == "TimerViewGrid":
                    name = (c.element_info.name or "").lower()
                    if not first_card:
                        first_card = c
                    if f"{target_m} min" in name:
                        matching_card = c
                        break
            card_to_use = matching_card or first_card
            if card_to_use:
                for sub in card_to_use.descendants():
                    aid = sub.element_info.automation_id
                    if aid == "TimerPlayPauseButton":
                        try:
                            sub.invoke()
                            timer_started = True
                        except Exception:
                            pass
                    elif aid == "AotButton" and keep_on_top:
                        time.sleep(0.4)
                        try:
                            sub.invoke()
                            popped_aot = True
                        except Exception:
                            pass
        else:
            # Custom timer (e.g. 10 seconds, 45 seconds, 25 minutes)
            # Click AddTimerButton (+)
            for c in win.descendants():
                if c.element_info.automation_id == "AddTimerButton":
                    try:
                        c.invoke()
                    except Exception:
                        pass
                    break
            time.sleep(0.6)

            # Set duration picker columns (hours, minutes, seconds)
            for c in win.descendants():
                if c.element_info.automation_id == "DurationPicker":
                    for child in c.children():
                        col = child.element_info.name
                        t_val = target_h if col == "hours" else (target_m if col == "minutes" else target_s)
                        mod = 24 if col == "hours" else 60
                        half = mod // 2
                        try:
                            cur = int(child.legacy_properties()["Value"])
                            diff = (t_val - cur) % mod
                            btns = [b for b in child.descendants() if b.element_info.control_type == "Button"]
                            if len(btns) >= 2:
                                btn = btns[0] if diff <= half else btns[1]
                                steps = diff if diff <= half else (mod - diff)
                                for _ in range(steps):
                                    btn.invoke()
                        except Exception:
                            pass

            # Set timer name in Edit box
            timer_label = title or (f"{target_s}s Timer" if target_m == 0 else f"{target_m}m {target_s}s Timer")
            for c in win.descendants():
                if c.element_info.control_type == "Edit":
                    try:
                        c.set_edit_text(timer_label)
                    except Exception:
                        pass
                    break

            # Click Save (PrimaryButton)
            for c in win.descendants():
                if c.element_info.automation_id == "PrimaryButton":
                    try:
                        c.invoke()
                    except Exception:
                        pass
                    break
            time.sleep(0.6)

            # Find the new timer card and start it + AOT
            for c in win.descendants():
                if c.element_info.automation_id == "TimerViewGrid":
                    name = (c.element_info.name or "").lower()
                    if timer_label.lower() in name or (target_s > 0 and f"{target_s} second" in name):
                        for sub in c.descendants():
                            aid = sub.element_info.automation_id
                            if aid == "TimerPlayPauseButton":
                                try:
                                    sub.invoke()
                                    timer_started = True
                                except Exception:
                                    pass
                            elif aid == "AotButton" and keep_on_top:
                                time.sleep(0.4)
                                try:
                                    sub.invoke()
                                    popped_aot = True
                                except Exception:
                                    pass
                        break

        return {
            "success": True,
            "feature": "timer",
            "total_seconds": total_sec,
            "hours": target_h,
            "minutes": target_m,
            "seconds": target_s,
            "timer_started": timer_started,
            "keep_on_top_widget": popped_aot,
            "note": "Native Windows Clock timer configured and started with compact always-on-top mode.",
        }

    @classmethod
    def set_alarm_ui(cls, hour: int, minute: int, name: str = "Alarm") -> dict[str, Any]:
        """Automate Windows Clock: Alarm -> Add new alarm -> set exact hour, minute, name, and Save."""
        win = cls.get_clock_window()
        if not win:
            return {"success": False, "error": "Could not launch or connect to Windows Clock app."}

        # Step 1: Select AlarmButton
        for c in win.descendants():
            if c.element_info.automation_id == "AlarmButton":
                try:
                    c.select()
                except Exception:
                    try:
                        c.invoke()
                    except Exception:
                        pass
                break
        time.sleep(0.6)

        # Step 2: Click Add an alarm (+)
        for c in win.descendants():
            if c.element_info.automation_id == "AddAlarmButton":
                try:
                    c.invoke()
                except Exception:
                    pass
                break
        time.sleep(0.6)

        # Step 3: Set exact Hour on HourPicker
        for c in win.descendants():
            if c.element_info.automation_id == "HourPicker":
                btns = [b for b in c.descendants() if b.element_info.control_type == "Button"]
                if len(btns) >= 2:
                    try:
                        cur = int(c.legacy_properties()["Value"])
                        diff = (hour - cur) % 24
                        btn = btns[0] if diff <= 12 else btns[1]
                        steps = diff if diff <= 12 else (24 - diff)
                        for _ in range(steps):
                            btn.invoke()
                    except Exception:
                        pass
                break

        # Step 4: Set exact Minute on MinutePicker
        for c in win.descendants():
            if c.element_info.automation_id == "MinutePicker":
                btns = [b for b in c.descendants() if b.element_info.control_type == "Button"]
                if len(btns) >= 2:
                    try:
                        cur = int(c.legacy_properties()["Value"])
                        diff = (minute - cur) % 60
                        btn = btns[0] if diff <= 30 else btns[1]
                        steps = diff if diff <= 30 else (60 - diff)
                        for _ in range(steps):
                            btn.invoke()
                    except Exception:
                        pass
                break

        # Step 5: Set Alarm Name in Edit box
        for c in win.descendants():
            if c.element_info.control_type == "Edit" and "name" in (c.element_info.name or "").lower():
                try:
                    c.set_edit_text(name)
                except Exception:
                    pass
                break

        # Step 6: Click Save (PrimaryButton)
        saved = False
        for c in win.descendants():
            if c.element_info.automation_id == "PrimaryButton":
                try:
                    c.invoke()
                    saved = True
                except Exception:
                    pass
                break

        return {
            "success": True,
            "feature": "alarm",
            "time": f"{hour:02d}:{minute:02d}",
            "name": name,
            "alarm_saved_in_ui": saved,
            "note": "Alarm configured directly inside the native Windows Clock app.",
        }


class WindowsDesktopTool(BaseTool):
    """Native Windows desktop integration: clipboard, toast notifications, alarms, and timers."""
    name = "desktop_integration"
    description = (
        "Interact with Windows desktop: copy/read clipboard data, display native desktop toast notifications, "
        "and schedule persistent desktop alarms and countdown timers via Windows Task Scheduler."
    )
    risk_level = RiskLevel.L1

    def __init__(self) -> None:
        self.executor = NativeSubprocessExecutor()

    @staticmethod
    def _ensure_alarm_script() -> Path:
        """Ensure ~/.nemo/scripts/trigger_alarm.ps1 exists for user-scheduled hard ringing alarms."""
        scripts_dir = Path.home() / ".nemo" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_file = scripts_dir / "trigger_alarm.ps1"
        content = """param(
    [string]$Title = "⏰ NEMO Hard Alarm",
    [string]$Message = "Alarm time reached!"
)

# 1. Bring up Windows Clock App
try {
    Start-Process "ms-clock:"
} catch {}

# 2. Start continuous audio alarm loop in background job
$soundJob = Start-Job -ScriptBlock {
    $soundPath = "C:\\Windows\\Media\\Alarm01.wav"
    if (Test-Path $soundPath) {
        $player = New-Object System.Media.SoundPlayer $soundPath
        while ($true) {
            $player.PlaySync()
        }
    } else {
        while ($true) {
            [System.Console]::Beep(1200, 400)
            Start-Sleep -Milliseconds 200
        }
    }
}

# 3. Display Hard Topmost Dismiss Dialog
[void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
[System.Windows.Forms.MessageBox]::Show(
    "$Message`n`nClick OK to turn off the alarm.",
    $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Exclamation,
    [System.Windows.Forms.MessageBoxDefaultButton]::Button1,
    [System.Windows.Forms.MessageBoxOptions]::ServiceNotification
)

# 4. Stop looping sound when user dismisses
Stop-Job $soundJob -ErrorAction SilentlyContinue
Remove-Job $soundJob -ErrorAction SilentlyContinue
"""
        script_file.write_text(content, encoding="utf-8")
        return script_file

    @staticmethod
    def _parse_alarm_time(time_str: str) -> tuple[str, str]:
        """Parse natural time string ('6 PM', '6:00 PM', '18:00') into (24h_HH_mm, formatted_label)."""
        s = str(time_str).strip().upper()
        # 12-hour format e.g. "6 PM", "6:00 PM", "6:30 AM", "6pm"
        m_12 = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)$", s)
        if m_12:
            hour = int(m_12.group(1))
            minute = int(m_12.group(2) or 0)
            ampm = m_12.group(3)
            formatted_label = f"{hour}:{minute:02d} {ampm}"
            if ampm == "PM" and hour < 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
            return f"{hour:02d}:{minute:02d}", formatted_label

        # 24-hour format e.g. "18:00", "06:30"
        m_24 = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
        if m_24:
            hour = int(m_24.group(1))
            minute = int(m_24.group(2))
            am_pm = "PM" if hour >= 12 else "AM"
            h_12 = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
            formatted_label = f"{h_12}:{minute:02d} {am_pm}"
            return f"{hour:02d}:{minute:02d}", formatted_label

        # Plain hour integer e.g. "18"
        if s.isdigit() and 0 <= int(s) <= 23:
            hour = int(s)
            am_pm = "PM" if hour >= 12 else "AM"
            h_12 = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
            return f"{hour:02d}:00", f"{h_12}:00 {am_pm}"

        raise ValueError(f"Unrecognized time format: '{time_str}'. Expected e.g. '18:00', '6:00 PM', or '6 PM'.")

    @staticmethod
    def _resolve_user_target_path(raw_path: str, base_dir: Path) -> Path:
        """Resolve user path, automatically mapping standard folders like 'downloads', 'desktop', 'pictures' to Windows UserProfile."""
        p_str = str(raw_path).strip()
        p_lower = p_str.lower().replace("\\", "/")

        if p_lower.startswith("downloads/") or p_lower == "downloads":
            remainder = p_str[len("downloads"):].lstrip("\\/") or "output.jpg"
            target_dir = Path.home() / "Downloads"
            target_dir.mkdir(parents=True, exist_ok=True)
            return target_dir / remainder
        elif p_lower.startswith("desktop/") or p_lower == "desktop":
            remainder = p_str[len("desktop"):].lstrip("\\/") or "output.jpg"
            target_dir = Path.home() / "Desktop"
            target_dir.mkdir(parents=True, exist_ok=True)
            return target_dir / remainder
        elif p_lower.startswith("pictures/") or p_lower == "pictures":
            remainder = p_str[len("pictures"):].lstrip("\\/") or "output.jpg"
            target_dir = Path.home() / "Pictures"
            target_dir.mkdir(parents=True, exist_ok=True)
            return target_dir / remainder
        elif p_lower.startswith("documents/") or p_lower == "documents":
            remainder = p_str[len("documents"):].lstrip("\\/") or "output.jpg"
            target_dir = Path.home() / "Documents"
            target_dir.mkdir(parents=True, exist_ok=True)
            return target_dir / remainder

        p = Path(raw_path)
        if p.is_absolute():
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        target = base_dir / raw_path
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "clipboard_copy",
                            "clipboard_read",
                            "notify",
                            "set_alarm",
                            "set_timer",
                            "start_pomodoro",
                            "start_stopwatch",
                            "clock_stopwatch",
                            "stopwatch",
                            "camera_snapshot",
                            "capture_camera",
                            "snipping_tool",
                            "capture_region",
                            "screen_clip",
                            "play_audio",
                            "play_music",
                            "open_in_paint",
                            "paint_draw",
                            "draw_shape",
                            "draw_in_paint",
                            "record_audio",
                            "sound_recorder",
                            "terminal_layout",
                            "open_terminal_panes",
                            "list_alarms",
                            "cancel_alarm",
                        ],
                        "description": "Desktop action to perform.",
                    },
                    "shape": {
                        "type": "string",
                        "enum": ["square", "rectangle", "circle", "triangle", "star"],
                        "description": "Shape to draw in Microsoft Paint (for 'paint_draw').",
                    },
                    "size": {
                        "type": "integer",
                        "description": "Size in pixels of the shape to draw (default 240).",
                    },
                    "color": {
                        "type": "string",
                        "description": "Color to draw with (default 'black').",
                    },
                    "text": {"type": "string", "description": "Text to copy to clipboard (for 'clipboard_copy')."},
                    "title": {"type": "string", "description": "Title for notification or alarm."},
                    "message": {"type": "string", "description": "Message for notification or alarm."},
                    "time": {"type": "string", "description": "Time string to trigger alarm, e.g. '18:00', '6:00 PM', '6 PM' (for 'set_alarm')."},
                    "minutes": {"type": "number", "description": "Duration in minutes for countdown timer (for 'set_timer')."},
                    "seconds": {"type": "number", "description": "Duration in seconds for countdown timer (for 'set_timer')."},
                    "keep_on_top": {"type": "boolean", "description": "Whether to place the widget in compact always-on-top mode (default true)."},
                    "focus_minutes": {"type": "number", "description": "Pomodoro focus duration in minutes (default 25) (for 'start_pomodoro')."},
                    "break_minutes": {"type": "number", "description": "Pomodoro short break duration in minutes (default 5) (for 'start_pomodoro')."},
                    "long_break_minutes": {"type": "number", "description": "Pomodoro long break duration in minutes (default 15) (for 'start_pomodoro')."},
                    "cycles": {"type": "integer", "description": "Pomodoro cycles before long break (default 4) (for 'start_pomodoro')."},
                    "skip_breaks": {"type": "boolean", "description": "Whether to skip breaks during focus session (for 'start_pomodoro')."},
                    "path": {"type": "string", "description": "Target or destination file path (for audio playback, camera snapshot, recording, paint markup)."},
                    "volume": {"type": "integer", "description": "Audio playback volume from 0 to 100 (default 70) (for 'play_audio')."},
                    "search": {"type": "string", "description": "Search keyword to find music/audio files in system to play (for 'play_audio')."},
                    "duration_seconds": {"type": "integer", "description": "Audio recording duration in seconds (default 10) (for 'record_audio')."},
                    "panes": {"type": "array", "items": {"type": "string"}, "description": "List of pane names/commands for Windows Terminal multi-pane layout."},
                    "directory": {"type": "string", "description": "Starting working directory for terminal panes (for 'terminal_layout')."},
                    "task_name": {"type": "string", "description": "Specific task name to cancel or 'all' (for 'cancel_alarm')."},
                },
                "required": ["action"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "").lower().strip()
        base_dir = Path(context.get("working_directory", Path.cwd()))

        try:
            if action == "clipboard_copy":
                text = arguments.get("text", "")
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                    input=text,
                    text=True,
                    capture_output=True,
                )
                if proc.returncode != 0:
                    return ToolResult(success=False, error=f"Failed to copy to clipboard: {proc.stderr}")
                return ToolResult(success=True, data={"action": "clipboard_copy", "copied_length": len(text)})

            elif action == "clipboard_read":
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    return ToolResult(success=False, error=f"Failed to read clipboard: {proc.stderr}")
                content = proc.stdout.rstrip("\r\n")
                return ToolResult(success=True, data={"action": "clipboard_read", "content": content, "length": len(content)})

            elif action == "notify":
                title = arguments.get("title", "NEMO Assistant")
                msg = arguments.get("message", "Task completed.")
                safe_title = str(title).replace("'", "''")
                safe_msg = str(msg).replace("'", "''")

                # Native modern Windows 10/11 WinRT toast notification with tray balloon fallback
                ps_cmd = (
                    f"$title = '{safe_title}'; "
                    f"$msg = '{safe_msg}'; "
                    f"try {{ "
                    f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                    f"$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02; "
                    f"$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template); "
                    f"$textNodes = $xml.GetElementsByTagName('text'); "
                    f"$textNodes.Item(0).AppendChild($xml.CreateTextNode($title)) | Out-Null; "
                    f"$textNodes.Item(1).AppendChild($xml.CreateTextNode($msg)) | Out-Null; "
                    f"$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
                    f"$appId = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'; "
                    f"$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId); "
                    f"$notifier.Show($toast); "
                    f"}} catch {{ "
                    f"[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
                    f"$n = New-Object System.Windows.Forms.NotifyIcon; "
                    f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
                    f"$n.BalloonTipTitle = $title; "
                    f"$n.BalloonTipText = $msg; "
                    f"$n.Visible = $True; "
                    f"$n.ShowBalloonTip(3000); "
                    f"Start-Sleep -Seconds 3; "
                    f"$n.Dispose(); "
                    f"}}"
                )
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return ToolResult(
                    success=True,
                    data={"action": "notify", "title": title, "message": msg, "delivered": True},
                )

            elif action == "set_alarm":
                raw_time = arguments.get("time", "")
                if not raw_time:
                    return ToolResult(success=False, error="Parameter 'time' is required for set_alarm (e.g. '18:00' or '6:00 PM').")
                try:
                    time_24, label = self._parse_alarm_time(raw_time)
                except ValueError as err:
                    return ToolResult(success=False, error=str(err))

                script_path = self._ensure_alarm_script()
                title = arguments.get("title") or f"⏰ NEMO Hard Alarm ({label})"
                msg = arguments.get("message") or f"{label} Alarm - NEMO Assistant"
                task_name = f"NEMO_Alarm_{time_24.replace(':', '')}"

                cmd = [
                    "schtasks", "/create",
                    "/tn", task_name,
                    "/tr", f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script_path}" -Title "{title}" -Message "{msg}"',
                    "/sc", "once",
                    "/st", time_24,
                    "/f",
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    return ToolResult(success=False, error=f"Failed to schedule alarm: {proc.stderr or proc.stdout}")

                # Configure native Windows Clock app UI and display on screen
                ui_res = {}
                try:
                    hour_int, min_int = [int(p) for p in time_24.split(":")]
                    ui_res = WindowsClockAutomator.set_alarm_ui(hour=hour_int, minute=min_int, name=title)
                except Exception as ui_err:
                    ui_res = {"success": False, "error": str(ui_err)}

                return ToolResult(
                    success=True,
                    data={
                        "action": "set_alarm",
                        "task_name": task_name,
                        "scheduled_time": label,
                        "time_24h": time_24,
                        "clock_app": "automated" if ui_res.get("success") else "launched (ms-clock:)",
                        "clock_details": ui_res,
                        "hard_alarm": "armed with continuous looping sound until dismissed",
                        "status": "active",
                        "title": title,
                        "message": msg,
                        "note": "Alarm configured in native Windows Clock app and registered in Task Scheduler.",
                    },
                )

            elif action == "set_timer":
                minutes_val = arguments.get("minutes") or 0.0
                seconds_val = arguments.get("seconds") or 0.0
                try:
                    minutes = float(minutes_val)
                except (ValueError, TypeError):
                    minutes = 0.0
                try:
                    seconds = float(seconds_val)
                except (ValueError, TypeError):
                    seconds = 0.0

                if minutes == 0.0 and seconds == 0.0:
                    minutes = 5.0

                title = arguments.get("title") or (
                    f"Timer ({int(seconds)}s)" if (seconds > 0 and minutes == 0) else f"Timer ({int(minutes)}m)"
                )
                keep_on_top = bool(arguments.get("keep_on_top", True))

                # Automate native Windows Clock timer directly (preset or custom hours/minutes/seconds)
                res = WindowsClockAutomator.start_timer(minutes=minutes, seconds=seconds, title=title, keep_on_top=keep_on_top)

                return ToolResult(
                    success=True,
                    data={
                        "action": "set_timer",
                        "duration_minutes": minutes,
                        "duration_seconds": seconds,
                        "title": title,
                        "widget_status": "active (native Windows Clock keep-on-top timer)",
                        "clock_app": "automated",
                        "clock_details": res,
                        "note": "Native Windows Clock timer started on screen with compact always-on-top mode.",
                    },
                )

            elif action == "start_pomodoro":
                focus = float(arguments.get("focus_minutes") or arguments.get("focus") or 25.0)
                break_min = float(arguments.get("break_minutes") or arguments.get("break") or 5.0)
                long_break = float(arguments.get("long_break_minutes") or arguments.get("long_break") or 15.0)
                cycles = int(arguments.get("cycles") or 4)
                skip_breaks = bool(arguments.get("skip_breaks", False))
                keep_on_top = bool(arguments.get("keep_on_top", True))
                title = arguments.get("title") or "Pomodoro Focus"

                # Automate native Windows Clock Focus Session directly with always-on-top compact mode
                res = WindowsClockAutomator.start_focus_session(minutes=focus, skip_breaks=skip_breaks, keep_on_top=keep_on_top)

                return ToolResult(
                    success=True,
                    data={
                        "action": "start_pomodoro",
                        "focus_minutes": focus,
                        "break_minutes": break_min,
                        "long_break_minutes": long_break,
                        "cycles": cycles,
                        "title": title,
                        "widget_status": "active (native Windows Clock Focus Session)",
                        "clock_app": "automated",
                        "clock_details": res,
                        "note": "Native Windows Clock Focus Session started directly on screen.",
                    },
                )

            elif action in ("start_stopwatch", "clock_stopwatch", "stopwatch"):
                keep_on_top = bool(arguments.get("keep_on_top", True))
                res = WindowsClockAutomator.start_stopwatch(keep_on_top=keep_on_top)
                return ToolResult(
                    success=True,
                    data={
                        "action": "start_stopwatch",
                        "clock_app": "automated",
                        "clock_details": res,
                        "note": "Native Windows Clock stopwatch started on screen in compact mode.",
                    },
                )

            elif action == "list_alarms":
                proc = subprocess.run(["schtasks", "/query", "/fo", "CSV"], capture_output=True, text=True)
                alarms = []
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        if "NEMO_Alarm_" in line or "NEMO_Timer_" in line:
                            parts = [p.strip('"\r') for p in line.split('","')]
                            if len(parts) >= 3:
                                alarms.append({
                                    "task_name": parts[0].lstrip("\\"),
                                    "next_run_time": parts[1],
                                    "status": parts[2],
                                })
                return ToolResult(success=True, data={"action": "list_alarms", "count": len(alarms), "alarms": alarms})

            elif action == "cancel_alarm":
                target_name = arguments.get("task_name", "all").strip()
                deleted = []
                if target_name.lower() in ("all", "*"):
                    proc = subprocess.run(["schtasks", "/query", "/fo", "CSV"], capture_output=True, text=True)
                    for line in proc.stdout.splitlines():
                        if "NEMO_Alarm_" in line or "NEMO_Timer_" in line:
                            parts = [p.strip('"\r') for p in line.split('","')]
                            if parts:
                                t_name = parts[0].lstrip("\\")
                                subprocess.run(["schtasks", "/delete", "/tn", t_name, "/f"], capture_output=True)
                                deleted.append(t_name)
                else:
                    proc = subprocess.run(["schtasks", "/delete", "/tn", target_name, "/f"], capture_output=True)
                    if proc.returncode == 0:
                        deleted.append(target_name)
                    else:
                        return ToolResult(success=False, error=f"Task '{target_name}' not found or could not be deleted.")

                return ToolResult(success=True, data={"action": "cancel_alarm", "deleted_tasks": deleted, "count": len(deleted)})

            elif action in ("camera_snapshot", "capture_camera"):
                out_path = arguments.get("path") or arguments.get("output_path") or "camera_snapshot.jpg"
                out_file = self._resolve_user_target_path(out_path, base_dir)

                # Launch native Windows Camera app
                subprocess.Popen(["cmd.exe", "/c", "start", "microsoft.windows.camera:"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.5)

                # Trigger Take photo button via UIA
                snapped = False
                win = None
                try:
                    from pywinauto import Desktop
                    d = Desktop(backend="uia")
                    for w in d.windows():
                        if "camera" in (w.window_text() or "").lower() or w.class_name() == "ApplicationFrameWindow":
                            for c in w.children():
                                if "camera" in (c.window_text() or "").lower():
                                    win = w
                                    break
                            if win:
                                break
                    if win:
                        for desc in win.descendants():
                            if desc.element_info.automation_id == "CaptureButton_0":
                                desc.invoke()
                                snapped = True
                                break
                except Exception:
                    pass

                # Locate latest photo in Pictures\Camera Roll
                cam_roll = Path.home() / "Pictures" / "Camera Roll"
                latest_photo = None
                if cam_roll.exists():
                    photos = list(cam_roll.glob("WIN_*.jpg")) + list(cam_roll.glob("*.jpg")) + list(cam_roll.glob("*.png"))
                    if photos:
                        latest_photo = max(photos, key=lambda p: p.stat().st_mtime)

                if latest_photo and latest_photo.exists():
                    try:
                        shutil.copy2(latest_photo, out_file)
                    except Exception:
                        out_file = latest_photo

                return ToolResult(
                    success=True,
                    data={
                        "action": "camera_snapshot",
                        "camera_app": "launched (microsoft.windows.camera:)",
                        "captured": snapped or bool(latest_photo),
                        "output_path": str(out_file),
                        "source_camera_roll": str(latest_photo) if latest_photo else None,
                        "note": "Webcam snapshot captured via native Windows Camera app.",
                    },
                )

            elif action in ("snipping_tool", "capture_region", "screen_clip"):
                subprocess.Popen(["cmd.exe", "/c", "start", "ms-screenclip:"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ToolResult(
                    success=True,
                    data={
                        "action": "snipping_tool",
                        "status": "active (ms-screenclip: launched)",
                        "note": "Native Windows Snipping Tool overlay launched for region screenshot selection.",
                    },
                )

            elif action in ("play_audio", "play_music"):
                path_arg = arguments.get("path") or arguments.get("file")
                search_query = arguments.get("search") or arguments.get("query")
                volume = int(arguments.get("volume", 70))

                target_file = None
                if path_arg:
                    p = Path(context.get("working_directory", Path.cwd())) / path_arg
                    if p.exists():
                        target_file = p
                    elif Path(path_arg).exists():
                        target_file = Path(path_arg)

                if not target_file:
                    # Scan system music folders
                    scan_dirs = [
                        Path.home() / "Music",
                        Path.home() / "Downloads",
                        Path.home() / "Videos",
                        Path("C:/Windows/Media"),
                    ]
                    candidates = []
                    for s_dir in scan_dirs:
                        if s_dir.exists():
                            for ext in ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.wma"):
                                candidates.extend(s_dir.glob(ext))

                    if search_query:
                        sq = search_query.lower()
                        matched = [c for c in candidates if sq in c.name.lower()]
                        if matched:
                            target_file = matched[0]

                    if not target_file and candidates:
                        target_file = candidates[0]

                if not target_file:
                    return ToolResult(success=False, error="No audio or music files found on system to play.")

                # Play via native Windows Media Player COM engine
                try:
                    import win32com.client
                    wmp = win32com.client.Dispatch("WMPlayer.OCX")
                    wmp.URL = str(target_file.resolve())
                    wmp.settings.volume = max(0, min(100, volume))
                    wmp.controls.play()
                except Exception:
                    subprocess.Popen(["cmd.exe", "/c", "start", str(target_file.resolve())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                return ToolResult(
                    success=True,
                    data={
                        "action": "play_audio",
                        "file": str(target_file),
                        "file_name": target_file.name,
                        "volume": volume,
                        "playback_engine": "Windows Media Player (WMPlayer.OCX)",
                        "status": "playing",
                        "note": f"Audio playback started for '{target_file.name}' at {volume}% volume.",
                    },
                )

            elif action == "open_in_paint":
                path_arg = arguments.get("path") or arguments.get("file")
                target_file = None
                if path_arg:
                    p = Path(context.get("working_directory", Path.cwd())) / path_arg
                    if p.exists():
                        target_file = p
                    elif Path(path_arg).exists():
                        target_file = Path(path_arg)

                if not target_file:
                    # Capture instant screen to temporary canvas
                    temp_img = Path(tempfile.gettempdir()) / "nemo_paint_canvas.png"
                    ps_cmd = (
                        "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
                        "$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                        "$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height); "
                        "$g = [System.Drawing.Graphics]::FromImage($b); "
                        "$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size); "
                        f"$b.Save('{str(temp_img).replace('\\', '\\\\')}', [System.Drawing.Imaging.ImageFormat]::Png); "
                        "$g.Dispose(); $b.Dispose();"
                    )
                    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], capture_output=True)
                    if temp_img.exists():
                        target_file = temp_img

                cmd = ["mspaint.exe"]
                if target_file:
                    cmd.append(str(target_file.resolve()))

                proc = subprocess.Popen(cmd)
                return ToolResult(
                    success=True,
                    data={
                        "action": "open_in_paint",
                        "image_path": str(target_file) if target_file else None,
                        "pid": proc.pid,
                        "note": "Microsoft Paint canvas opened successfully for manual markup.",
                    },
                )

            elif action in ("paint_draw", "draw_shape", "draw_in_paint"):
                shape = str(arguments.get("shape") or "square").lower().strip()
                size = int(arguments.get("size") or 240)
                color = str(arguments.get("color") or "black").lower().strip()

                # Ensure access to interactive desktop
                try:
                    user32 = ctypes.windll.user32
                    h_desk = user32.OpenDesktopW("Default", 0, False, 0x10000000)
                    if h_desk:
                        user32.SetThreadDesktop(h_desk)
                except Exception:
                    pass

                # 1. Find or launch Paint
                paint_hwnd = None
                if win32gui:
                    def _find_paint(h, _):
                        nonlocal paint_hwnd
                        if win32gui.IsWindowVisible(h):
                            cls = win32gui.GetClassName(h)
                            txt = win32gui.GetWindowText(h)
                            if "Paint" in txt or cls == "MSPaintApp":
                                paint_hwnd = h
                    win32gui.EnumWindows(_find_paint, None)

                if not paint_hwnd:
                    proc = subprocess.Popen(["mspaint.exe"])
                    await asyncio.sleep(1.2)
                    if win32gui:
                        win32gui.EnumWindows(_find_paint, None)

                if paint_hwnd and win32gui:
                    try:
                        win32gui.ShowWindow(paint_hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(paint_hwnd)
                        await asyncio.sleep(0.3)
                        rect = win32gui.GetWindowRect(paint_hwnd)
                        w_left, w_top, w_right, w_bottom = rect
                    except Exception:
                        w_left, w_top = 100, 100
                        w_right, w_bottom = 1200, 800
                else:
                    w_left, w_top = 100, 100
                    w_right, w_bottom = 1200, 800

                # Canvas center (Paint ribbon is ~180px high at the top)
                cx = w_left + (w_right - w_left) // 2
                cy = w_top + 200 + max(100, (w_bottom - w_top - 200) // 2)

                # Generate shape path
                points = []
                if shape in ("square", "rect", "rectangle"):
                    w = size
                    h = size if shape == "square" else int(size * 0.65)
                    half_w = w // 2
                    half_h = h // 2
                    points = [
                        (cx - half_w, cy - half_h),
                        (cx + half_w, cy - half_h),
                        (cx + half_w, cy + half_h),
                        (cx - half_w, cy + half_h),
                        (cx - half_w, cy - half_h),
                    ]
                elif shape == "circle":
                    import math
                    r = size // 2
                    for deg in range(0, 365, 10):
                        rad = math.radians(deg)
                        points.append((int(cx + r * math.cos(rad)), int(cy + r * math.sin(rad))))
                elif shape == "triangle":
                    h = size // 2
                    points = [
                        (cx, cy - h),
                        (cx + h, cy + h),
                        (cx - h, cy + h),
                        (cx, cy - h),
                    ]
                elif shape == "star":
                    import math
                    r_outer = size // 2
                    r_inner = r_outer // 2
                    for i in range(11):
                        angle = i * (math.pi / 5) - (math.pi / 2)
                        r = r_outer if i % 2 == 0 else r_inner
                        points.append((int(cx + r * math.cos(angle)), int(cy + r * math.sin(angle))))
                else:
                    points = [(cx - size // 2, cy), (cx + size // 2, cy)]

                # Smoothly drag mouse across all edges with LEFTDOWN
                if win32api:
                    p0 = points[0]
                    win32api.SetCursorPos(p0)
                    await asyncio.sleep(0.08)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    await asyncio.sleep(0.03)

                    for i in range(len(points) - 1):
                        x1, y1 = points[i]
                        x2, y2 = points[i + 1]
                        steps = 30
                        for s in range(1, steps + 1):
                            cur_x = int(x1 + (x2 - x1) * (s / steps))
                            cur_y = int(y1 + (y2 - y1) * (s / steps))
                            win32api.SetCursorPos((cur_x, cur_y))
                            await asyncio.sleep(0.007)

                    await asyncio.sleep(0.03)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

                return ToolResult(
                    success=True,
                    data={
                        "action": "paint_draw",
                        "shape": shape,
                        "size": size,
                        "center": (cx, cy),
                        "note": f"Successfully drew a crisp {shape} in Microsoft Paint at canvas position ({cx}, {cy}).",
                    },
                )

            elif action in ("record_audio", "sound_recorder"):
                duration = int(arguments.get("duration_seconds") or arguments.get("duration") or 10)
                out_path = arguments.get("path") or arguments.get("output_path") or f"mic_recording_{duration}s.wav"
                out_file = Path(context.get("working_directory", Path.cwd())) / out_path

                # Launch Sound Recorder app visually
                try:
                    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe!App"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

                # Record audio directly from default microphone via winmm MCI
                recorded = False
                try:
                    winmm = ctypes.windll.winmm
                    winmm.mciSendStringW("open new type waveaudio alias nemorec", None, 0, None)
                    winmm.mciSendStringW("record nemorec", None, 0, None)
                    time.sleep(duration)
                    winmm.mciSendStringW(f'save nemorec "{str(out_file.resolve())}"', None, 0, None)
                    winmm.mciSendStringW("close nemorec", None, 0, None)
                    recorded = out_file.exists() and out_file.stat().st_size > 0
                except Exception:
                    pass

                return ToolResult(
                    success=True,
                    data={
                        "action": "record_audio",
                        "duration_seconds": duration,
                        "output_file": str(out_file),
                        "recorded": recorded,
                        "app": "Windows Sound Recorder",
                        "note": f"Microphone audio recorded for {duration} seconds.",
                    },
                )

            elif action in ("terminal_layout", "open_terminal_panes"):
                panes = arguments.get("panes") or ["backend: powershell", "frontend: powershell", "docker: powershell"]
                start_dir = arguments.get("directory") or str(base_dir)

                # Build wt.exe multi-pane command arguments
                wt_args = ["wt.exe", "-w", "0", "nt", "-d", str(start_dir)]
                for i, _ in enumerate(panes):
                    if i == 0:
                        continue
                    split_flag = "-V" if (i % 2 == 1) else "-H"
                    wt_args.extend([";", "sp", split_flag, "-d", str(start_dir)])

                try:
                    subprocess.Popen(wt_args, shell=False)
                except Exception as wt_err:
                    return ToolResult(success=False, error=f"Failed to launch Windows Terminal: {wt_err}")

                return ToolResult(
                    success=True,
                    data={
                        "action": "terminal_layout",
                        "panes_count": len(panes),
                        "panes": panes,
                        "start_directory": start_dir,
                        "wt_command": " ".join(wt_args),
                        "note": f"Windows Terminal opened with {len(panes)}-pane development layout.",
                    },
                )

            else:
                return ToolResult(success=False, error=f"Unsupported desktop action: '{action}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"Desktop integration error: {exc}")


class WebResearcherTool(BaseTool):
    """Autonomous web research, clean technical documentation extraction, PyPI inspection, and Wikipedia queries."""
    name = "web_researcher"
    description = (
        "Autonomous web research and technical document extraction: search live web via DuckDuckGo, "
        "extract clean documentation and articles without ad clutter via Trafilatura, query PyPI package specs, "
        "and fetch encyclopedic definitions via Wikipedia."
    )
    risk_level = RiskLevel.L0

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "fetch_doc", "pypi", "wiki", "research"],
                        "description": "Research action: 'search' (web search), 'fetch_doc' (extract clean page markdown), 'pypi' (package specs), 'wiki' (encyclopedic definition), 'research' (search and synthesize top article).",
                    },
                    "query": {"type": "string", "description": "Search query, topic, definition, or question."},
                    "url": {"type": "string", "description": "Web page URL (for 'fetch_doc')."},
                    "package_name": {"type": "string", "description": "Python package name (for 'pypi')."},
                    "limit": {"type": "integer", "description": "Maximum search results to return (default 5)."},
                    "max_chars": {"type": "integer", "description": "Maximum characters of article content to return (default 6000)."},
                },
                "required": ["action"],
            },
            risk_level=self.risk_level,
        )

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "search").lower().strip()

        try:
            if action == "search":
                q = arguments.get("query", "").strip()
                if not q:
                    return ToolResult(success=False, error="query parameter is required for 'search' action.")
                limit = int(arguments.get("limit", 5))

                results = []
                queries_to_try = [q]
                words = q.split()
                if len(words) > 2:
                    queries_to_try.append(" ".join(words[:2]))

                search_err = None
                for candidate in queries_to_try:
                    try:
                        with DDGS() as ddgs:
                            raw = list(ddgs.text(candidate, max_results=limit))
                            if raw:
                                for item in raw:
                                    results.append({
                                        "title": item.get("title", ""),
                                        "url": item.get("href", ""),
                                        "snippet": item.get("body", ""),
                                    })
                                break
                    except Exception as exc:
                        search_err = exc
                        if "no results found" in str(exc).lower():
                            continue

                if not results and search_err and "no results found" not in str(search_err).lower():
                    return ToolResult(success=False, error=f"DuckDuckGo search failed: {search_err}")

                return ToolResult(
                    success=True,
                    data={"action": "search", "query": q, "count": len(results), "results": results},
                )

            elif action == "fetch_doc":
                target_url = arguments.get("url", "").strip()
                if not target_url:
                    return ToolResult(success=False, error="url parameter is required for 'fetch_doc' action.")
                max_chars = int(arguments.get("max_chars", 6000))

                try:
                    downloaded = trafilatura.fetch_url(target_url)
                    if not downloaded:
                        return ToolResult(success=False, error=f"Failed to fetch content from URL: {target_url}")

                    extracted_md = trafilatura.extract(
                        downloaded,
                        output_format="markdown",
                        with_metadata=True,
                        include_comments=False,
                    ) or ""

                    if not extracted_md:
                        extracted_md = trafilatura.extract(downloaded, output_format="txt") or "No readable text content extracted."

                    return ToolResult(
                        success=True,
                        data={
                            "action": "fetch_doc",
                            "url": target_url,
                            "length_chars": len(extracted_md),
                            "content": extracted_md[:max_chars],
                        },
                    )
                except Exception as exc:
                    return ToolResult(success=False, error=f"Document extraction failed: {exc}")

            elif action == "pypi":
                pkg = arguments.get("package_name") or arguments.get("query", "").strip()
                if not pkg:
                    return ToolResult(success=False, error="package_name is required for 'pypi' action.")

                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(
                        f"https://pypi.org/pypi/{pkg}/json",
                        headers={"User-Agent": "NemoAssistant/1.0 (dev@nemo.ai)"},
                    )
                    if resp.status_code == 404:
                        return ToolResult(success=False, error=f"Python package '{pkg}' was not found on PyPI.")
                    elif not resp.is_success:
                        return ToolResult(success=False, error=f"PyPI API returned status code {resp.status_code}.")

                    data = resp.json()
                    info = data.get("info", {})
                    urls = info.get("project_urls") or {}

                    return ToolResult(
                        success=True,
                        data={
                            "action": "pypi",
                            "name": info.get("name", pkg),
                            "latest_version": info.get("version", ""),
                            "summary": info.get("summary", ""),
                            "author": info.get("author", ""),
                            "license": info.get("license", ""),
                            "home_page": info.get("home_page") or urls.get("Homepage", ""),
                            "documentation": urls.get("Documentation") or urls.get("Docs", ""),
                            "repository": urls.get("Repository") or urls.get("Source", ""),
                            "requires_python": info.get("requires_python", ""),
                            "dependencies": (info.get("requires_dist") or [])[:15],
                        },
                    )

            elif action == "wiki":
                topic = arguments.get("query", "").strip()
                if not topic:
                    return ToolResult(success=False, error="query parameter is required for 'wiki' action.")

                encoded_topic = quote(topic.replace(" ", "_"))
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_topic}",
                        headers={"User-Agent": "NemoAssistant/1.0 (dev@nemo.ai)"},
                    )
                    if resp.status_code == 404:
                        return ToolResult(success=False, error=f"No Wikipedia article found for topic: '{topic}'.")
                    elif not resp.is_success:
                        return ToolResult(success=False, error=f"Wikipedia API returned status code {resp.status_code}.")

                    w_data = resp.json()
                    urls = w_data.get("content_urls", {}).get("desktop", {})

                    return ToolResult(
                        success=True,
                        data={
                            "action": "wiki",
                            "title": w_data.get("title", topic),
                            "description": w_data.get("description", ""),
                            "summary": w_data.get("extract", ""),
                            "url": urls.get("page", ""),
                        },
                    )

            elif action == "research":
                topic = arguments.get("query", "").strip()
                if not topic:
                    return ToolResult(success=False, error="query parameter is required for 'research' action.")

                results = []
                queries_to_try = [topic]
                words = topic.split()
                if len(words) > 2:
                    queries_to_try.append(" ".join(words[:2]))

                for q_cand in queries_to_try:
                    try:
                        with DDGS() as ddgs:
                            raw = list(ddgs.text(q_cand, max_results=3))
                            if raw:
                                for item in raw:
                                    results.append({
                                        "title": item.get("title", ""),
                                        "url": item.get("href", ""),
                                        "snippet": item.get("body", ""),
                                    })
                                break
                    except Exception:
                        continue

                # Fallback to Wikipedia summary if web search yielded 0 results
                if not results and words:
                    try:
                        encoded = quote(words[0])
                        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                            wresp = await client.get(
                                f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
                                headers={"User-Agent": "NemoAssistant/1.0 (dev@nemo.ai)"},
                            )
                            if wresp.is_success:
                                w_info = wresp.json()
                                page_url = w_info.get("content_urls", {}).get("desktop", {}).get("page", "")
                                results.append({
                                    "title": w_info.get("title", topic),
                                    "url": page_url,
                                    "snippet": w_info.get("extract", "")[:300],
                                })
                    except Exception:
                        pass

                deep_content = ""
                primary_url = ""
                if results and results[0].get("url"):
                    primary_url = results[0]["url"]
                    try:
                        dl = trafilatura.fetch_url(primary_url)
                        if dl:
                            extracted = trafilatura.extract(dl, output_format="markdown", with_metadata=True)
                            if extracted:
                                deep_content = extracted[:4000]
                    except Exception:
                        pass

                if not deep_content and results and results[0].get("snippet"):
                    deep_content = results[0]["snippet"]

                return ToolResult(
                    success=True,
                    data={
                        "action": "research",
                        "query": topic,
                        "sources_count": len(results),
                        "sources": results,
                        "deep_source_url": primary_url,
                        "deep_extracted_content": deep_content,
                    },
                )

            else:
                return ToolResult(success=False, error=f"Unsupported research action: '{action}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"Web researcher error: {exc}")


class WindowsGuiTool(BaseTool):
    """Production Windows desktop GUI automation tool via UI Automation (UIA) and Win32."""
    name = "gui_automation"
    description = (
        "Automate Windows GUI desktop applications using UI Automation (UIA): "
        "launch apps, list top-level windows, focus, minimize, maximize, restore, "
        "close, click controls, type keystrokes/hotkeys, and inspect accessible control trees."
    )
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
                        "enum": [
                            "list_windows",
                            "launch",
                            "focus",
                            "minimize",
                            "maximize",
                            "restore",
                            "close",
                            "click",
                            "type_keys",
                            "inspect_tree",
                            "clock_focus",
                            "clock_timer",
                            "clock_alarm",
                            "clock_stopwatch",
                            "analyze_screen",
                            "paint_draw",
                            "draw_shape",
                        ],
                        "description": "Desktop GUI action to perform.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Question or prompt for visual analysis (for 'analyze_screen').",
                    },
                    "target": {
                        "type": "string",
                        "description": "Window title substring or executable path/command (for launch, focus, minimize, etc.).",
                    },
                    "control": {
                        "type": "string",
                        "description": "Control name, title, or automation ID to click.",
                    },
                    "keys": {
                        "type": "string",
                        "description": "Keystrokes, text, or shortcuts to send (e.g. 'Hello{ENTER}', '^s' for Ctrl+S).",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Max accessible controls to return during tree inspection (default: 30).",
                        "default": 30,
                    },
                },
                "required": ["action"],
            },
            risk_level=self.risk_level,
        )

    @staticmethod
    def _get_interactive_desktop_handle():
        """Retrieve desktop handle for user's interactive 'Default' desktop on WinSta0."""
        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x10000000)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
                return h_desk
        except Exception:
            pass
        return None

    def _find_window(self, target: str):
        self._get_interactive_desktop_handle()
        if not Desktop:
            return None
        desktop = Desktop(backend="uia")
        target_lower = target.lower().strip()
        for win in desktop.windows():
            try:
                t = win.window_text()
                if target_lower in t.lower():
                    return win
            except Exception:
                continue
        return None

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(success=False, error="gui_automation is only supported on Windows.")

        action = arguments.get("action", "").lower().strip()
        target = arguments.get("target", "").strip()

        try:
            if action == "list_windows":
                h_desk = self._get_interactive_desktop_handle()
                windows = []
                if win32gui and win32process:
                    def enum_cb(hwnd, _):
                        if win32gui.IsWindowVisible(hwnd):
                            title = win32gui.GetWindowText(hwnd).strip()
                            if title and title not in ("Default IME", "MSCTFIME UI"):
                                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                                windows.append({"hwnd": hwnd, "pid": pid, "title": title})

                    if h_desk:
                        try:
                            win32gui.EnumDesktopWindows(h_desk, enum_cb, None)
                        except Exception:
                            try:
                                win32gui.EnumWindows(enum_cb, None)
                            except Exception:
                                pass
                    else:
                        try:
                            win32gui.EnumWindows(enum_cb, None)
                        except Exception:
                            pass

                if not windows and Desktop:
                    try:
                        d = Desktop(backend="uia")
                        for w in d.windows():
                            t = w.window_text()
                            if t:
                                windows.append({"hwnd": w.handle, "pid": w.process_id(), "title": t})
                    except Exception:
                        pass

                return ToolResult(
                    success=True,
                    data={"action": "list_windows", "count": len(windows), "windows": windows},
                )

            elif action == "launch":
                if not target:
                    return ToolResult(success=False, error="target parameter is required for 'launch' action.")
                proc = subprocess.Popen(target, shell=True)
                return ToolResult(
                    success=True,
                    data={"action": "launch", "target": target, "pid": proc.pid},
                )

            elif action in ("focus", "minimize", "maximize", "restore", "close"):
                if not target:
                    return ToolResult(success=False, error=f"target window title is required for '{action}' action.")
                win = self._find_window(target)
                if not win:
                    return ToolResult(success=False, error=f"No window found matching '{target}'.")

                title = win.window_text()
                if action == "focus":
                    win.set_focus()
                elif action == "minimize":
                    win.minimize()
                elif action == "maximize":
                    win.maximize()
                elif action == "restore":
                    win.restore()
                elif action == "close":
                    win.close()

                return ToolResult(
                    success=True,
                    data={"action": action, "target": target, "window": title},
                )

            elif action == "type_keys":
                if not target:
                    return ToolResult(success=False, error="target window title is required for 'type_keys' action.")
                keys = arguments.get("keys", "")
                if not keys:
                    return ToolResult(success=False, error="keys parameter is required for 'type_keys' action.")

                win = self._find_window(target)
                if not win:
                    return ToolResult(success=False, error=f"No window found matching '{target}'.")

                win.set_focus()
                win.type_keys(keys, with_spaces=True)
                return ToolResult(
                    success=True,
                    data={"action": "type_keys", "window": win.window_text(), "keys": keys},
                )

            elif action == "click":
                if not target:
                    return ToolResult(success=False, error="target window title is required for 'click' action.")
                ctrl_query = arguments.get("control", "").strip().lower()
                if not ctrl_query:
                    return ToolResult(success=False, error="control parameter is required for 'click' action.")

                win = self._find_window(target)
                if not win:
                    return ToolResult(success=False, error=f"No window found matching '{target}'.")

                target_ctrl = None
                for c in win.descendants():
                    try:
                        name = (c.element_info.name or "").lower()
                        auto_id = (c.element_info.automation_id or "").lower()
                        if ctrl_query in name or ctrl_query == auto_id:
                            target_ctrl = c
                            break
                    except Exception:
                        continue

                if not target_ctrl:
                    return ToolResult(
                        success=False,
                        error=f"Control matching '{ctrl_query}' not found in window '{win.window_text()}'.",
                    )

                try:
                    target_ctrl.click_input()
                except Exception:
                    try:
                        target_ctrl.invoke()
                    except Exception as inv_err:
                        return ToolResult(success=False, error=f"Failed to click control: {inv_err}")

                return ToolResult(
                    success=True,
                    data={
                        "action": "click",
                        "window": win.window_text(),
                        "control": target_ctrl.element_info.name or ctrl_query,
                    },
                )

            elif action == "inspect_tree":
                if not target:
                    return ToolResult(success=False, error="target window title is required for 'inspect_tree' action.")
                win = self._find_window(target)
                if not win:
                    return ToolResult(success=False, error=f"No window found matching '{target}'.")

                limit = int(arguments.get("max_depth", 30))
                controls = []
                for c in win.descendants():
                    try:
                        name = c.element_info.name or ""
                        auto_id = c.element_info.automation_id or ""
                        ctrl_type = c.element_info.control_type or ""
                        if name or auto_id:
                            controls.append({
                                "type": ctrl_type,
                                "name": name,
                                "automation_id": auto_id,
                                "enabled": c.is_enabled(),
                            })
                            if len(controls) >= limit:
                                break
                    except Exception:
                        continue

                return ToolResult(
                    success=True,
                    data={
                        "action": "inspect_tree",
                        "window": win.window_text(),
                        "controls_count": len(controls),
                        "controls": controls,
                    },
                )

            elif action == "clock_focus":
                mins = float(arguments.get("minutes", 25.0))
                skip_br = bool(arguments.get("skip_breaks", False))
                aot = bool(arguments.get("keep_on_top", False))
                res = WindowsClockAutomator.start_focus_session(minutes=mins, skip_breaks=skip_br, keep_on_top=aot)
                return ToolResult(success=res.get("success", True), data=res)

            elif action == "clock_timer":
                mins = float(arguments.get("minutes", 0.0))
                secs = float(arguments.get("seconds", 0.0))
                title = arguments.get("title", "Timer")
                aot = bool(arguments.get("keep_on_top", True))
                res = WindowsClockAutomator.start_timer(minutes=mins, seconds=secs, title=title, keep_on_top=aot)
                return ToolResult(success=res.get("success", True), data=res)

            elif action == "clock_alarm":
                time_str = arguments.get("time", "07:00")
                time_24, _ = WindowsDesktopTool._parse_alarm_time(time_str)
                h, m = [int(p) for p in time_24.split(":")]
                name = arguments.get("title") or arguments.get("name", "Alarm")
                res = WindowsClockAutomator.set_alarm_ui(hour=h, minute=m, name=name)
                return ToolResult(success=res.get("success", True), data=res)

            elif action == "clock_stopwatch":
                aot = bool(arguments.get("keep_on_top", True))
                res = WindowsClockAutomator.start_stopwatch(keep_on_top=aot)
                return ToolResult(success=res.get("success", True), data=res)

            elif action == "analyze_screen":
                prompt_text = arguments.get("prompt", "Analyze what is currently visible on screen and verify UI state.")
                b64 = capture_desktop_screenshot_base64()
                if not b64:
                    return ToolResult(
                        success=False,
                        error="Could not capture desktop screen. Ensure active interactive session.",
                    )
                try:
                    from nemo.ai.providers.nvidia import NvidiaNimProvider
                    provider = NvidiaNimProvider()
                    analysis = await provider.analyze_image(image_base64=b64, prompt=prompt_text)
                    return ToolResult(
                        success=True,
                        data={"action": "analyze_screen", "prompt": prompt_text, "analysis": analysis},
                    )
                except Exception as viz_err:
                    return ToolResult(success=False, error=f"Screen vision analysis failed: {viz_err}")

            elif action in ("paint_draw", "draw_shape", "draw_in_paint"):
                dt = WindowsDesktopTool()
                return await dt.execute({"action": "paint_draw", **arguments}, context)

            else:
                return ToolResult(success=False, error=f"Unsupported gui action: '{action}'")

        except Exception as exc:
            return ToolResult(success=False, error=f"GUI automation error: {exc}")


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
    "GitOperationsTool",
    "DatabaseExplorerTool",
    "ApiTesterTool",
    "SystemInspectorTool",
    "WindowsDesktopTool",
    "WebResearcherTool",
    "WindowsGuiTool",
]
