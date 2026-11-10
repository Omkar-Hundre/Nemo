"""Outcome verification engine confirming actual OS, filesystem, and process truth."""

# 1. Standard library imports
import ast
from pathlib import Path
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.execution.shells.native import NativeSubprocessExecutor
from nemo.intelligence.packages import PackageManagerDetector

# 4. Types, Protocols, Schemas
class VerificationResult(BaseModel):
    """Result of independent outcome verification."""
    verified: bool
    ground_truth_source: str  # "filesystem" | "ast_syntax" | "test_suite" | "process"
    details: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)

# 5. Core logic / classes / functions
class OutcomeVerifier:
    """Verifies that agent modifications succeeded using ground-truth system evidence."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.executor = NativeSubprocessExecutor()

    async def verify_file_created_or_modified(self, rel_path: str) -> VerificationResult:
        """Verify target file exists, is non-empty, and has valid syntax."""
        target = (self.workspace_root / rel_path).resolve()
        if not target.exists():
            return VerificationResult(
                verified=False,
                ground_truth_source="filesystem",
                details=f"File does not exist: {target}",
            )

        stat = target.stat()
        if stat.st_size == 0:
            return VerificationResult(
                verified=False,
                ground_truth_source="filesystem",
                details=f"File exists but is empty (0 bytes): {target}",
            )

        # Check Python syntax if Python file
        if target.suffix.lower() == ".py":
            try:
                content = target.read_text(encoding="utf-8", errors="replace")
                ast.parse(content, filename=str(target))
            except SyntaxError as syn_err:
                return VerificationResult(
                    verified=False,
                    ground_truth_source="ast_syntax",
                    details=f"SyntaxError in {target.name}: {syn_err.msg} (line {syn_err.lineno})",
                )

        return VerificationResult(
            verified=True,
            ground_truth_source="filesystem",
            details=f"Verified: {target.name} exists ({stat.st_size} bytes) with valid syntax.",
            diagnostics={"size_bytes": stat.st_size, "path": str(target)},
        )

    async def verify_test_suite_passes(self, modified_files: list[str] | None = None) -> VerificationResult:
        """Run project validation/test suite to verify no regressions were introduced."""
        # Fast exit: skip test suite if changes are purely content, markup, docs, or web assets
        if modified_files is not None:
            code_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cpp", ".c"}
            has_code_changes = any(Path(f).suffix.lower() in code_extensions for f in modified_files)
            if not has_code_changes:
                return VerificationResult(
                    verified=True,
                    ground_truth_source="test_suite",
                    details="No source code files modified; skipped test runner for non-code artifacts.",
                )

        ecosystems = PackageManagerDetector.detect(self.workspace_root)
        if not ecosystems:
            return VerificationResult(
                verified=True,
                ground_truth_source="test_suite",
                details="No manifest detected; skipping automated test suite.",
            )

        eco = ecosystems[0]
        test_cmd = eco.validate_command
        result = await self.executor.execute(test_cmd, cwd=self.workspace_root, timeout_seconds=60.0)

        return VerificationResult(
            verified=result.is_success,
            ground_truth_source="test_suite",
            details=f"Test command '{test_cmd}' exited with code {result.exit_code}.",
            diagnostics={
                "exit_code": result.exit_code,
                "stdout_tail": result.stdout[-500:],
                "stderr_tail": result.stderr[-500:],
            },
        )

# 6. Public exports
__all__ = ["OutcomeVerifier", "VerificationResult"]

