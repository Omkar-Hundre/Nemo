"""Structure-aware code chunking for precise semantic retrieval and indexing."""

# 1. Standard library imports
import hashlib
from pathlib import Path
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.intelligence.parser import ASTCodeParser, ParsedModule

# 4. Types, Protocols, Schemas
class CodeChunk(BaseModel):
    """Structure-aware chunk representing a cohesive code unit."""
    chunk_id: str
    file_path: str
    symbol_name: str | None = None
    kind: str  # "class" | "function" | "method" | "module" | "block"
    start_line: int
    end_line: int
    content: str
    content_hash: str

# 5. Core logic / classes / functions
class StructureAwareChunker:
    """Splits source code into natural AST-aligned boundaries rather than arbitrary tokens."""

    @staticmethod
    def chunk_file(file_path: Path | str) -> list[CodeChunk]:
        path = Path(file_path)
        rel_str = str(path).replace("\\", "/")
        try:
            raw_content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        lines = raw_content.splitlines(keepends=True)
        if not lines:
            return []

        # If Python, chunk by AST symbols
        if path.suffix.lower() == ".py":
            return StructureAwareChunker._chunk_python(path, rel_str, lines, raw_content)

        # Non-python fallback: chunk by paragraph/logical blocks (max 60 lines)
        return StructureAwareChunker._chunk_lines(rel_str, lines)

    @staticmethod
    def _chunk_python(path: Path, rel_str: str, lines: list[str], raw_content: str) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        parsed: ParsedModule = ASTCodeParser.parse_python_file(path)

        # 1. Class chunks
        for cls in parsed.classes:
            s_line = cls["start_line"]
            e_line = cls["end_line"]
            chunk_text = "".join(lines[s_line - 1 : e_line])
            c_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:12]
            chunks.append(CodeChunk(
                chunk_id=f"{rel_str}:{cls['name']}:{s_line}",
                file_path=rel_str,
                symbol_name=cls["name"],
                kind="class",
                start_line=s_line,
                end_line=e_line,
                content=chunk_text,
                content_hash=c_hash,
            ))

        # 2. Standalone function chunks
        for fn in parsed.functions:
            s_line = fn["start_line"]
            e_line = fn["end_line"]
            chunk_text = "".join(lines[s_line - 1 : e_line])
            c_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:12]
            chunks.append(CodeChunk(
                chunk_id=f"{rel_str}:{fn['name']}:{s_line}",
                file_path=rel_str,
                symbol_name=fn["name"],
                kind="function",
                start_line=s_line,
                end_line=e_line,
                content=chunk_text,
                content_hash=c_hash,
            ))

        # 3. If file has no functions/classes (e.g. settings/types/__init__), whole file chunk
        if not chunks:
            c_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:12]
            chunks.append(CodeChunk(
                chunk_id=f"{rel_str}:module:1",
                file_path=rel_str,
                symbol_name=None,
                kind="module",
                start_line=1,
                end_line=len(lines),
                content=raw_content,
                content_hash=c_hash,
            ))

        return chunks

    @staticmethod
    def _chunk_lines(rel_str: str, lines: list[str], window_size: int = 50) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        total = len(lines)
        for i in range(0, total, window_size):
            end_idx = min(i + window_size, total)
            chunk_text = "".join(lines[i:end_idx])
            c_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:12]
            chunks.append(CodeChunk(
                chunk_id=f"{rel_str}:block:{i+1}",
                file_path=rel_str,
                symbol_name=None,
                kind="block",
                start_line=i + 1,
                end_line=end_idx,
                content=chunk_text,
                content_hash=c_hash,
            ))
        return chunks

# 6. Public exports
__all__ = ["CodeChunk", "StructureAwareChunker"]
