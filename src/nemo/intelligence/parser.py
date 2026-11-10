"""AST-based code intelligence parser extracting imports, symbols, and call graphs."""

# 1. Standard library imports
import ast
from pathlib import Path
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class ExtractedCall(BaseModel):
    """Function or method call reference."""
    caller_symbol: str
    target_name: str
    line: int


class ExtractedImport(BaseModel):
    """Module import statement."""
    module: str
    names: list[str] = Field(default_factory=list)
    line: int


class ParsedModule(BaseModel):
    """Complete AST structural analysis of a source file."""
    file_path: str
    imports: list[ExtractedImport] = Field(default_factory=list)
    classes: list[dict[str, Any]] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    calls: list[ExtractedCall] = Field(default_factory=list)
    docstring: str | None = None

# 5. Core logic / classes / functions
class ASTCodeParser:
    """Parses Python source files using AST to extract symbols, dependencies, and call hierarchies."""

    @staticmethod
    def parse_python_file(file_path: Path | str) -> ParsedModule:
        path = Path(file_path)
        rel_str = str(path).replace("\\", "/")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(path))
        except Exception as exc:
            return ParsedModule(file_path=rel_str, docstring=f"Parse error: {exc}")

        module_doc = ast.get_docstring(tree)
        imports: list[ExtractedImport] = []
        classes: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        calls: list[ExtractedCall] = []

        # 1. Collect imports
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ExtractedImport(module=alias.name, names=[alias.asname or alias.name], line=node.lineno))
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                names = [a.name for a in node.names]
                imports.append(ExtractedImport(module=mod_name, names=names, line=node.lineno))

        # 2. Collect classes, methods, and functions
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            "name": item.name,
                            "start_line": item.lineno,
                            "end_line": getattr(item, "end_lineno", item.lineno),
                            "docstring": ast.get_docstring(item),
                            "args": [a.arg for a in item.args.args],
                        })
                        # Extract calls inside method
                        for subnode in ast.walk(item):
                            if isinstance(subnode, ast.Call):
                                target = ASTCodeParser._resolve_call_name(subnode.func)
                                if target:
                                    calls.append(ExtractedCall(caller_symbol=f"{node.name}.{item.name}", target_name=target, line=subnode.lineno))

                classes.append({
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node),
                    "bases": [ASTCodeParser._resolve_call_name(b) for b in node.bases if ASTCodeParser._resolve_call_name(b)],
                    "methods": methods,
                })

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node),
                    "args": [a.arg for a in node.args.args],
                })
                # Extract calls inside function
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Call):
                        target = ASTCodeParser._resolve_call_name(subnode.func)
                        if target:
                            calls.append(ExtractedCall(caller_symbol=node.name, target_name=target, line=subnode.lineno))

        return ParsedModule(
            file_path=rel_str,
            imports=imports,
            classes=classes,
            functions=functions,
            calls=calls,
            docstring=module_doc,
        )

    @staticmethod
    def _resolve_call_name(node: ast.AST) -> str | None:
        """Resolve target identifier from ast.Call func node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            val = ASTCodeParser._resolve_call_name(node.value)
            return f"{val}.{node.attr}" if val else node.attr
        return None

# 6. Public exports
__all__ = ["ASTCodeParser", "ParsedModule", "ExtractedImport", "ExtractedCall"]

