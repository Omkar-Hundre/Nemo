"""Incremental code indexer tracking file hashes, AST symbols, and architecture summaries."""

# 1. Standard library imports
import hashlib
import json
from pathlib import Path
import time
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.intelligence.scanner import ProjectScanner, ScannedFile

# 4. Types, Protocols, Schemas
class IndexReport(BaseModel):
    """Summary metrics of an indexing operation."""
    root_path: str
    total_files: int = 0
    total_symbols: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    duration_ms: float = 0.0
    languages: dict[str, int] = Field(default_factory=dict)


class ProjectIndexer:
    """Performs incremental workspace indexing by hashing files and caching states."""

    def __init__(self, root_path: Path | str, cache_dir: Path | None = None) -> None:
        self.root_path = Path(root_path).resolve()
        self.cache_dir = cache_dir or (Path.home() / ".nemo" / "index")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Deterministic cache filename based on path hash
        path_digest = hashlib.md5(str(self.root_path).encode("utf-8")).hexdigest()[:8]
        slug = f"{self.root_path.name}_{path_digest}"
        self.index_file = self.cache_dir / f"{slug}.json"

    def _load_snapshot(self) -> dict[str, str]:
        """Load mapping of relative_path -> content_hash from previous run."""
        if not self.index_file.exists():
            return {}
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
            return raw.get("hashes", {})
        except Exception:
            return {}

    def _save_snapshot(self, files: list[ScannedFile]) -> None:
        """Save current indexed state to disk."""
        total_syms = sum(len(f.symbols) for f in files)
        data = {
            "root_path": str(self.root_path),
            "updated_at": time.time(),
            "total_files": len(files),
            "total_symbols": total_syms,
            "hashes": {f.relative_path: f.content_hash for f in files},
            "files": [f.model_dump() for f in files],
        }
        self.index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def run_index(self, force: bool = False) -> IndexReport:
        """Scan workspace and perform incremental indexing with AST symbol extraction."""
        start_time = time.perf_counter()
        scanner = ProjectScanner(self.root_path)
        files = scanner.scan()

        prev_hashes = {} if force else self._load_snapshot()
        indexed_count = 0
        skipped_count = 0
        lang_counts: dict[str, int] = {}
        total_syms = 0

        for f in files:
            lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
            total_syms += len(f.symbols)
            if not force and f.relative_path in prev_hashes and prev_hashes[f.relative_path] == f.content_hash:
                skipped_count += 1
            else:
                indexed_count += 1

        self._save_snapshot(files)
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return IndexReport(
            root_path=str(self.root_path),
            total_files=len(files),
            total_symbols=total_syms,
            indexed_files=indexed_count,
            skipped_files=skipped_count,
            duration_ms=duration_ms,
            languages=lang_counts,
        )

    def get_indexed_files(self) -> list[ScannedFile]:
        """Retrieve list of currently indexed files."""
        if not self.index_file.exists():
            return []
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
            return [ScannedFile.model_validate(f) for f in raw.get("files", [])]
        except Exception:
            return []

    def get_summary(self) -> dict[str, Any]:
        """Return high-level architecture overview of indexed codebase."""
        files = self.get_indexed_files()
        if not files:
            self.run_index()
            files = self.get_indexed_files()

        lang_counts: dict[str, int] = {}
        modules = []
        all_symbols = []

        for f in files:
            lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
            modules.append(f.relative_path)
            for sym in f.symbols:
                all_symbols.append({
                    "name": sym.name,
                    "kind": sym.kind,
                    "file": f.relative_path,
                    "line": sym.start_line,
                })

        return {
            "root_path": str(self.root_path),
            "total_files": len(files),
            "total_symbols": len(all_symbols),
            "languages": lang_counts,
            "modules": modules[:30],
            "key_symbols": all_symbols[:40],
        }

    def search_code(self, query: str, limit: int = 15) -> list[dict[str, Any]]:
        """Fast keyword search across file names, symbols, and contents."""
        files = self.get_indexed_files()
        tokens = query.lower().split()
        if not tokens:
            return []

        results: list[dict[str, Any]] = []

        for f in files:
            # Check symbol matches
            matched_syms = [
                s.name for s in f.symbols
                if any(t in s.name.lower() for t in tokens)
            ]
            # Check filename match
            file_match = any(t in f.relative_path.lower() for t in tokens)

            if matched_syms or file_match:
                results.append({
                    "file": f.relative_path,
                    "language": f.language,
                    "matched_symbols": matched_syms,
                    "file_match": file_match,
                })
                if len(results) >= limit:
                    break

        return results

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["IndexReport", "ProjectIndexer"]
