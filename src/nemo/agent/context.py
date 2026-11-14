"""Multi-turn session and task context persistence across agent executions."""

# 1. Standard library imports
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class ContextSnapshot(BaseModel):
    objective: str
    outcome: str
    target_paths: list[str] = Field(default_factory=list)
    working_directory: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 5. Core logic / classes / functions
class SessionContextManager:
    """Manages short-term context across successive CLI invocations."""

    def __init__(self, context_file: Path | None = None) -> None:
        self.context_file = context_file or (Path.home() / ".nemo" / "last_context.json")

    def save_context(
        self,
        objective: str,
        outcome: str,
        tool_history: list[dict[str, Any]],
        working_directory: str,
    ) -> None:
        """Extract paths and entities from completed task and save snapshot."""
        paths = set()
        for rec in tool_history:
            args = rec.get("arguments", {})
            if isinstance(args, dict):
                for k in ("path", "file", "target", "destination", "project_name"):
                    val = args.get(k)
                    if isinstance(val, str) and len(val.strip()) > 1:
                        paths.add(val.strip())
                cmd = str(args.get("command", ""))
                if cmd:
                    matches = re.findall(r"[\"']?([A-Za-z]:\\[^\"'\n\s]+|(?:\$env:[A-Za-z]+\\[^\"'\n\s]+))[\"']?", cmd)
                    for m in matches:
                        expanded = m.replace("$env:USERPROFILE", str(Path.home()))
                        paths.add(expanded)

        snapshot = ContextSnapshot(
            objective=objective,
            outcome=outcome[:1500],
            target_paths=list(paths)[:5],
            working_directory=working_directory,
        )
        try:
            self.context_file.parent.mkdir(parents=True, exist_ok=True)
            self.context_file.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_recent_context(self, current_objective: str, max_age_minutes: float = 30.0) -> str:
        """If current objective references previous context, return structured hint."""
        if not self.context_file.exists():
            return ""

        try:
            data = json.loads(self.context_file.read_text(encoding="utf-8"))
            saved_time = datetime.fromisoformat(data["timestamp"])
            age = (datetime.now(timezone.utc) - saved_time).total_seconds() / 60.0
            if age > max_age_minutes:
                return ""

            relative_words = {"that", "this", "it", "inside", "there", "above", "same", "continue", "previous", "copy", "move", "zip", "delete", "run", "check", "verify", "compress"}
            tokens = set(current_objective.lower().split())
            has_reference = bool(tokens & relative_words)

            paths_str = ", ".join(data.get("target_paths", []))
            ref_warning = "CRITICAL: The user refers to previous context. Resolve 'that folder', 'that file', or 'it' to the path above.\n" if has_reference else ""
            return (
                f"\nRecent Workspace Context (last task completed {int(age)} minutes ago):\n"
                f"- Previous Objective: {data.get('objective', '')}\n"
                f"- Target Paths / Artifacts: {paths_str or data.get('working_directory', '')}\n"
                f"- Previous Result Summary: {data.get('outcome', '')[:300]}\n"
                f"{ref_warning}"
            )
        except Exception:
            return ""


# 6. Public exports
__all__ = ["ContextSnapshot", "SessionContextManager"]

