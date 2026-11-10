"""Project directory scanner with ignore rules and language detection."""

# 1. Standard library imports
import fnmatch
import hashlib
from pathlib import Path

# 2. Third-party imports
from pydantic import BaseModel

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


class ScannedFile(BaseModel):
    """Metadata for an indexed source file."""
    path: str
    relative_path: str
    content_hash: str
    language: str
    size_bytes: int

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
        """Scan workspace and return list of valid scanned files."""
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

            scanned.append(
                ScannedFile(
                    path=str(p.resolve()),
                    relative_path=rel_str,
                    content_hash=fhash,
                    language=lang,
                    size_bytes=size,
                )
            )

        return sorted(scanned, key=lambda x: x.relative_path)

# 6. Public exports
__all__ = ["ScannedFile", "ProjectScanner", "compute_sha256", "DEFAULT_IGNORES", "EXTENSION_LANGUAGE_MAP"]

