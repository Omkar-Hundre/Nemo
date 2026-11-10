"""Project directory scanner with ignore rules, language detection, and AST symbol extraction."""

# 1. Standard library imports
import ast
import fnmatch
import hashlib
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
DEFAULT_IGNORES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    ".idea",
    ".vscode",
    ".coverage",
    ".env",
    ".env.*",
    "*.pyc",
    "*.pyo",
    "*.lock",
    "*.db",
    "*.sqlite3",
}

EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c-header",
    ".cs": "csharp",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
}


class CodeSymbol(BaseModel):
    """Extracted function, class, or method declaration."""
    name: str
    kind: str  # "class" | "function" | "method"
    start_line: int
    end_line: int
    docstring: str | None = None


class ScannedFile(BaseModel):
    """Metadata for an indexed source file."""
    path: str
    relative_path: str
    content_hash: str
    language: str
    size_bytes: int
    symbols: list[CodeSymbol] = Field(default_factory=list)

# 5. Core logic / classes / functions
def compute_sha256(file_path: Path) -> str:
    """Calculate SHA-256 hash of file contents."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def extract_symbols(file_path: Path, language: str) -> list[CodeSymbol]:
    """Extract code symbols (classes, functions, methods) from source file."""
    symbols: list[CodeSymbol] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return symbols

    if language == "python":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols.append(CodeSymbol(
                        name=node.name,
                        kind="class",
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        docstring=ast.get_docstring(node),
                    ))
                    # Extract class methods
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols.append(CodeSymbol(
                                name=f"{node.name}.{item.name}",
                                kind="method",
                                start_line=item.lineno,
                                end_line=getattr(item, "end_lineno", item.lineno),
                                docstring=ast.get_docstring(item),
                            ))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Top-level functions
                    symbols.append(CodeSymbol(
                        name=node.name,
                        kind="function",
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        docstring=ast.get_docstring(node),
                    ))
            # Sort symbols by line number
            return sorted(symbols, key=lambda s: s.start_line)
        except Exception:
            return symbols

    # Generic regex symbol extraction for JS/TS/Go/Rust
    if language in ("typescript", "javascript", "typescript-react", "javascript-react", "rust", "go"):
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            line_str = line.strip()
            # Functions
            m_fn = re.match(r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)", line_str)
            if m_fn:
                symbols.append(CodeSymbol(name=m_fn.group(1), kind="function", start_line=idx, end_line=idx))
                continue
            # Classes
            m_cls = re.match(r"(?:export\s+)?class\s+([a-zA-Z0-9_]+)", line_str)
            if m_cls:
                symbols.append(CodeSymbol(name=m_cls.group(1), kind="class", start_line=idx, end_line=idx))
                continue
            # Rust fn / struct
            m_rs = re.match(r"(?:pub\s+)?(?:fn|struct)\s+([a-zA-Z0-9_]+)", line_str)
            if m_rs:
                symbols.append(CodeSymbol(name=m_rs.group(1), kind="function", start_line=idx, end_line=idx))

    return symbols


class ProjectScanner:
    """Scans local directories while respecting standard ignore patterns and .gitignore."""

    def __init__(self, root_path: Path | str, custom_ignores: set[str] | None = None) -> None:
        self.root_path = Path(root_path).resolve()
        self.ignore_patterns = set(DEFAULT_IGNORES)
        if custom_ignores:
            self.ignore_patterns.update(custom_ignores)
        self._load_gitignore()

    def _load_gitignore(self) -> None:
        """Parse .gitignore if present in workspace root."""
        gitignore_path = self.root_path / ".gitignore"
        if not gitignore_path.exists():
            return
        try:
            lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    self.ignore_patterns.add(stripped.rstrip("/"))
        except Exception:
            pass

    def is_ignored(self, path: Path) -> bool:
        """Check if path matches any ignore pattern."""
        try:
            rel = path.relative_to(self.root_path)
            parts = rel.parts
        except ValueError:
            parts = path.parts

        for part in parts:
            for pattern in self.ignore_patterns:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def scan(self) -> list[ScannedFile]:
        """Scan workspace and return list of valid scanned files with symbols."""
        scanned: list[ScannedFile] = []
        if not self.root_path.exists():
            return scanned

        for p in self.root_path.rglob("*"):
            if not p.is_file():
                continue
            if self.is_ignored(p):
                continue

            rel_str = str(p.relative_to(self.root_path)).replace("\\", "/")
            ext = p.suffix.lower()
            lang = EXTENSION_LANGUAGE_MAP.get(ext, "text")
            fhash = compute_sha256(p)
            size = p.stat().st_size
            symbols = extract_symbols(p, lang)

            scanned.append(
                ScannedFile(
                    path=str(p.resolve()),
                    relative_path=rel_str,
                    content_hash=fhash,
                    language=lang,
                    size_bytes=size,
                    symbols=symbols,
                )
            )

        return sorted(scanned, key=lambda x: x.relative_path)

# 6. Public exports
__all__ = [
    "CodeSymbol",
    "ScannedFile",
    "ProjectScanner",
    "compute_sha256",
    "extract_symbols",
    "DEFAULT_IGNORES",
    "EXTENSION_LANGUAGE_MAP",
]
