"""Automated background memory extraction for technical decisions, project facts, and configurations."""

# 1. Standard library imports
import json
from pathlib import Path
import re
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.ai.providers.nvidia import NvidiaNimProvider
from nemo.ai.schemas import ChatMessage
from nemo.database.models import MemoryItem
from nemo.memory.repository import MemoryRepository

# 4. Types, Protocols, Schemas
class ExtractedMemory(BaseModel):
    content: str
    type: str = "fact"  # "fact" | "decision" | "preference"
    importance: float = 1.0
    subject: str | None = None


# 5. Core logic / classes / functions
class MemoryExtractor:
    """Extracts durable technical facts and decisions from agent workflows."""

    def __init__(
        self,
        provider: NvidiaNimProvider | None = None,
        repository: MemoryRepository | None = None,
    ) -> None:
        self.provider = provider or NvidiaNimProvider()
        self.repo = repository or MemoryRepository()

    async def extract_and_persist(
        self,
        objective: str,
        observations: list[dict[str, Any]],
        outcome: str,
        project_id: str | None = None,
        scope: str = "project",
    ) -> list[MemoryItem]:
        """Extract key technical facts/decisions and auto-persist to repository."""
        # Only run if meaningful observations or substantive outcome occurred
        if not observations and len(outcome.strip()) < 30:
            return []

        # Build concise extraction prompt
        obs_snippets = []
        for o in observations[:6]:
            obs_snippets.append({
                "tool": o.get("tool"),
                "arguments": o.get("arguments"),
                "success": o.get("success"),
            })

        prompt = (
            f"Objective: {objective}\n\n"
            f"Tool Execution Summary: {json.dumps(obs_snippets)}\n\n"
            f"Outcome: {outcome[:1200]}\n\n"
            "Task: Extract 1 to 3 durable technical facts, architectural decisions, project conventions, or ports learned from this execution.\n"
            "Do NOT extract transient status or trivial file paths. Only extract durable, long-term technical knowledge.\n"
            "Format: Output EXACTLY ONE JSON array of objects:\n"
            "[\n"
            '  {"content": "<concise factual statement>", "type": "fact"|"decision", "importance": 1.0, "subject": "<topic>"}\n'
            "]\n"
            "If no durable technical fact was established, output []."
        )

        messages = [
            ChatMessage(role="system", content="You are a senior technical memory consolidator. Output JSON array only."),
            ChatMessage(role="user", content=prompt),
        ]

        try:
            res = await self.provider.generate(messages, temperature=0.1, max_tokens=400, enable_thinking=False)
            text = res.content.strip()
            match = re.search(r"(\[.*\])", text, re.DOTALL)
            if not match:
                return []

            items = json.loads(match.group(1), strict=False)
            persisted: list[MemoryItem] = []
            for item in items:
                content = str(item.get("content", "")).strip()
                if not content or len(content) < 10:
                    continue

                # Deduplicate: check if this exact or highly similar memory already exists
                existing = await self.repo.search_memories(content, project_id=project_id, limit=3)
                if any(e.content.strip().lower() == content.lower() for e in existing):
                    continue

                saved = await self.repo.add_memory(
                    content=content,
                    scope=scope,
                    project_id=project_id,
                    memory_type=item.get("type", "fact"),
                    subject=item.get("subject"),
                    importance=float(item.get("importance", 1.0)),
                    metadata={"auto_extracted": True, "source_objective": objective[:100]},
                )
                persisted.append(saved)

            return persisted
        except Exception:
            return []


# 6. Public exports
__all__ = ["ExtractedMemory", "MemoryExtractor"]

