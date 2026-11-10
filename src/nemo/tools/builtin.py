"""Built-in development, operating, and code intelligence tools for NEMO agent."""

# 1. Standard library imports
import asyncio
from pathlib import Path
from typing import Any
import webbrowser

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.ai.embeddings import NvidiaEmbeddingProvider, cosine_similarity
from nemo.common.types import RiskLevel, ToolResult
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.integrations.ide.registry import IDERegistry
from nemo.intelligence.chunks import StructureAwareChunker
from nemo.intelligence.indexer import ProjectIndexer
from nemo.intelligence.packages import PackageManagerDetector
from nemo.intelligence.parser import ASTCodeParser
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
        if not self.policy.is_path_safe(target, base_dir=base_dir):
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

# 6. Public exports
__all__ = [
    "CodebaseSummaryTool",
    "CodeSearchTool",
    "SymbolLookupTool",
    "SemanticSearchTool",
    "TerminalTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirectoryTool",
    "MemoryRecallTool",
    "IDEOpenTool",
    "OpenBrowserTool",
    "ProjectEnvironmentTool",
    "GitDiffTool",
]
