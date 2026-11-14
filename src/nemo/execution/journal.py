"""Transactional undo operation journal for Nemo filesystem and execution actions."""

# 1. Standard library imports
import json
import logging
import os
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local imports
# (None)

logger = logging.getLogger(__name__)


# 4. Types, Protocols, Schemas
class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    timestamp: float = Field(default_factory=time.time)
    task_id: str | None = None
    action: str
    description: str = ""
    forward_data: dict[str, Any] = Field(default_factory=dict)
    rollback_data: dict[str, Any] = Field(default_factory=dict)


# 5. Core logic / classes / functions
class OperationJournal:
    """Records reversible operations and executes LIFO transaction rollbacks."""

    def __init__(self, journal_dir: Path | None = None) -> None:
        self.journal_dir = journal_dir or (Path.home() / ".nemo" / "journal")
        self.trash_dir = Path.home() / ".nemo" / "trash"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        try:
            self.journal_dir.mkdir(parents=True, exist_ok=True)
            self.trash_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("Could not create journal directories: %s", e)

    def record_action(
        self,
        action: str,
        forward_data: dict[str, Any],
        rollback_data: dict[str, Any],
        description: str = "",
        task_id: str | None = None,
    ) -> JournalEntry:
        """Record an atomic mutating action and its inverse rollback specification."""
        entry = JournalEntry(
            action=action,
            forward_data=forward_data,
            rollback_data=rollback_data,
            description=description,
            task_id=task_id,
        )
        file_name = f"{int(entry.timestamp * 1000)}_{entry.action}_{entry.id}.json"
        target_file = self.journal_dir / file_name

        try:
            target_file.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to record journal entry: %s", e)

        return entry

    def list_entries(self, limit: int = 20) -> list[JournalEntry]:
        """List recorded journal entries in reverse chronological order (newest first)."""
        if not self.journal_dir.exists():
            return []

        entries: list[JournalEntry] = []
        files = sorted(self.journal_dir.glob("*.json"), reverse=True)
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entries.append(JournalEntry(**data))
            except Exception:
                continue

        return entries

    def undo_last(self, count: int = 1) -> dict[str, Any]:
        """Roll back the last N recorded journal operations in LIFO order."""
        if not self.journal_dir.exists():
            return {"success": False, "message": "No journal found."}

        files = sorted(self.journal_dir.glob("*.json"), reverse=True)
        if not files:
            return {"success": False, "message": "No operations recorded in journal to undo."}

        target_files = files[:count]
        reverted: list[str] = []
        errors: list[str] = []

        for j_file in target_files:
            try:
                data = json.loads(j_file.read_text(encoding="utf-8"))
                entry = JournalEntry(**data)
                res = self._execute_rollback(entry)

                if res.get("success"):
                    reverted.append(res.get("summary", entry.description or entry.action))
                    # Safely delete processed journal entry file
                    try:
                        j_file.unlink()
                    except Exception:
                        pass
                else:
                    errors.append(res.get("error", "Unknown rollback error"))
            except Exception as exc:
                errors.append(f"Failed to process {j_file.name}: {exc}")

        return {
            "success": len(reverted) > 0,
            "reverted_count": len(reverted),
            "reverted_actions": reverted,
            "errors": errors if errors else None,
            "message": f"Successfully reverted {len(reverted)} operation(s)." if reverted else "Rollback failed.",
        }

    def _execute_rollback(self, entry: JournalEntry) -> dict[str, Any]:
        """Execute inverse operation for a single entry."""
        action = entry.action
        rb = entry.rollback_data

        try:
            if action in ("create_file", "write_file"):
                target_path = Path(rb.get("path", ""))
                previous_content = rb.get("previous_content")
                was_created = rb.get("was_created", False)

                if was_created and target_path.exists():
                    # Move to trash rather than permanent deletion
                    trash_dest = self.trash_dir / f"{int(time.time())}_{target_path.name}"
                    shutil.move(str(target_path), str(trash_dest))
                    return {"success": True, "summary": f"Removed created file {target_path.name}"}
                elif previous_content is not None and target_path.exists():
                    target_path.write_text(previous_content, encoding="utf-8")
                    return {"success": True, "summary": f"Restored previous content in {target_path.name}"}

            elif action == "create_folder":
                target_dir = Path(rb.get("path", ""))
                if target_dir.exists() and target_dir.is_dir():
                    # If empty or only contains safe files, remove
                    try:
                        target_dir.rmdir()
                        return {"success": True, "summary": f"Removed created folder {target_dir.name}"}
                    except OSError:
                        # Directory not empty, move to trash
                        trash_dest = self.trash_dir / f"{int(time.time())}_{target_dir.name}"
                        shutil.move(str(target_dir), str(trash_dest))
                        return {"success": True, "summary": f"Moved created folder {target_dir.name} to trash"}

            elif action in ("copy", "copy_file"):
                dst = Path(rb.get("dst", ""))
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst, ignore_errors=True)
                    else:
                        dst.unlink()
                    return {"success": True, "summary": f"Deleted copied artifact {dst.name}"}

            elif action == "move":
                src = Path(rb.get("original_src", ""))
                dst = Path(rb.get("dst", ""))
                if dst.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
                    return {"success": True, "summary": f"Restored moved file {dst.name} -> {src}"}

            elif action == "batch_transfer":
                files = rb.get("transferred_files", [])
                target_dir = Path(rb.get("target_directory", ""))
                removed_count = 0
                for f_str in files:
                    fp = Path(f_str)
                    if fp.exists():
                        if fp.is_dir():
                            shutil.rmtree(fp, ignore_errors=True)
                        else:
                            fp.unlink()
                        removed_count += 1

                # Clean up target dir if now empty
                if target_dir.exists() and not any(target_dir.iterdir()):
                    try:
                        target_dir.rmdir()
                    except Exception:
                        pass

                return {"success": True, "summary": f"Removed {removed_count} batch transferred file(s)"}

            elif action == "zip":
                archive = Path(rb.get("archive", ""))
                if archive.exists():
                    archive.unlink()
                    return {"success": True, "summary": f"Deleted zip archive {archive.name}"}

            return {"success": False, "error": f"Unhandled rollback action: {action}"}

        except Exception as e:
            logger.error("Error executing rollback for %s: %s", action, e)
            return {"success": False, "error": str(e)}


# 6. Public exports
__all__ = ["JournalEntry", "OperationJournal"]
