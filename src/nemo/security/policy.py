"""Security policy engine and risk classification."""

# 1. Standard library imports
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.common.types import RiskLevel

# 4. Types, Protocols, Schemas
DANGEROUS_COMMAND_PATTERNS = [
    r"\brmdir\s+/[sS]\b",
    r"\bdel\s+/[fF]\s+/[sS]\s+/[qQ]\s+[*c-zC-Z]:",
    r"\bformat\s+[a-zA-Z]:",
    r"\bdiskpart\b",
    r"\breg\s+delete\b",
    r"\bdrop\s+database\b",
    r"\bcurl.*\|\s*(bash|sh|powershell|pwsh)\b",
]

# 5. Core logic / classes / functions
class SecurityPolicy:
    """Evaluates risk levels and enforces workspace sandbox boundaries."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()

    def is_path_safe(self, path: Path | str, base_dir: Path | str | None = None) -> bool:
        """Verify path is contained inside workspace or allowed project boundary."""
        base = Path(base_dir).resolve() if base_dir else self.workspace_root
        p = Path(path)
        target = (base / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            target.relative_to(self.workspace_root)
            return True
        except ValueError:
            return False

    def assess_command_risk(self, command: str) -> RiskLevel:
        """Classify shell command risk based on side effects."""
        cmd_clean = command.strip()

        # Check dangerous system-destructive commands
        for pattern in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, cmd_clean, re.IGNORECASE):
                return RiskLevel.L3

        # L0: Pure read-only/inspection commands
        read_prefixes = (
            "git status", "git log", "git diff", "git branch",
            "dir", "ls", "python --version", "node --version",
            "npm --version", "uv --version", "pytest --version",
            "Get-ChildItem", "Get-Content", "Get-Date", "whoami",
        )
        if any(cmd_clean.startswith(p) for p in read_prefixes):
            return RiskLevel.L0

        # L1: Build, test, package operations in trusted project
        routine_prefixes = (
            "pytest", "npm test", "npm run build", "python -m unittest",
            "cargo test", "cargo build", "uv run", "pip list",
        )
        if any(cmd_clean.startswith(p) for p in routine_prefixes):
            return RiskLevel.L1

        # L2: Source code changes, installs, config updates
        return RiskLevel.L2

    def assess_tool_risk(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> RiskLevel:
        """Classify tool invocation risk within execution context."""
        ctx = context or {}
        base_dir = ctx.get("working_directory", self.workspace_root)

        if tool_name in ("read_file", "list_directory", "memory_recall", "ide_detect"):
            return RiskLevel.L0
        if tool_name == "terminal_execute":
            cmd = arguments.get("command", "")
            return self.assess_command_risk(cmd)
        if tool_name in ("write_file", "delete_file"):
            target = arguments.get("path", "")
            if not self.is_path_safe(target, base_dir=base_dir):
                return RiskLevel.L3
            return RiskLevel.L2
        if tool_name in ("ide_open", "ide_open_file"):
            return RiskLevel.L0

        return RiskLevel.L2

# 6. Public exports
__all__ = ["SecurityPolicy", "DANGEROUS_COMMAND_PATTERNS"]
