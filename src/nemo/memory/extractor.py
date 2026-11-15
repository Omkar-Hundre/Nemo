"""Automated background memory extraction for technical decisions, project facts, and configurations."""

# 1. Standard library imports
import json
from pathlib import Path
import re
import time
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

    _last_nim_call_time: float = 0.0
    NIM_RATE_LIMIT_COOLDOWN_SEC: float = 120.0

    def __init__(
        self,
        provider: NvidiaNimProvider | None = None,
        repository: MemoryRepository | None = None,
    ) -> None:
        self.provider = provider or NvidiaNimProvider()
        self.repo = repository or MemoryRepository()

    @staticmethod
    def _local_rule_extract(objective: str, outcome: str) -> list[dict[str, Any]]:
        """Zero-cost local pattern extractor for preferences and architectural choices."""
        combined = f"{objective}\n{outcome}"
        triplets: list[dict[str, Any]] = []

        # 1. Editor / IDE preference
        combined_lower = combined.lower()
        if "editor" in combined_lower or "ide" in combined_lower:
            for known in ("antigravity ide", "antigravity", "vscode", "vs code", "cursor", "pycharm", "neovim"):
                if known in combined_lower:
                    obj_name = "Antigravity IDE" if "antigravity" in known else ("VS Code" if "vs" in known else known.title())
                    triplets.append({
                        "subject": "Omkar",
                        "predicate": "uses_editor",
                        "object": obj_name,
                        "content": f"Developer uses {obj_name} as primary editor.",
                        "type": "preference",
                        "importance": 1.0,
                    })
                    break

        # 2. Browser preference
        if "browser" in combined_lower:
            for known in ("brave", "chrome", "firefox", "edge", "safari"):
                if known in combined_lower:
                    triplets.append({
                        "subject": "Omkar",
                        "predicate": "prefers_browser",
                        "object": f"{known.title()} Browser",
                        "content": f"Developer prefers {known.title()} browser.",
                        "type": "preference",
                        "importance": 1.0,
                    })
                    break

        # 3. Direct statements ("I prefer X", "My favorite X is Y", "Remember that X")
        m_pref = re.search(r"(?:i prefer|my favorite|always use|remember that|we use)\s+([^.]+)", combined, re.IGNORECASE)
        if m_pref:
            stmt = m_pref.group(1).strip()
            if 3 < len(stmt) < 70:
                triplets.append({
                    "subject": "Developer",
                    "predicate": "preference",
                    "object": stmt,
                    "content": f"Developer preference: {stmt}.",
                    "type": "preference",
                    "importance": 1.0,
                })

        # 4. Port configuration
        m_port = re.search(r"(?:port)\s*(?:is|=|:|\s)\s*(\d{2,5})", combined, re.IGNORECASE)
        if m_port:
            p_val = m_port.group(1)
            triplets.append({
                "subject": "Project",
                "predicate": "port",
                "object": p_val,
                "content": f"Project runs on port {p_val}.",
                "type": "fact",
                "importance": 0.9,
            })

        # 5. Frameworks
        for fw in ("fastapi", "react", "next.js", "tailwind", "pyside6", "rich"):
            if fw in combined.lower():
                triplets.append({
                    "subject": "Project",
                    "predicate": "framework",
                    "object": fw.upper() if len(fw) <= 4 else fw.title(),
                    "content": f"Project utilizes {fw}.",
                    "type": "decision",
                    "importance": 0.9,
                })
                break

        return triplets

    async def extract_and_persist(
        self,
        objective: str,
        observations: list[dict[str, Any]],
        outcome: str,
        project_id: str | None = None,
        scope: str = "project",
    ) -> list[MemoryItem]:
        """Extract key technical facts/decisions and auto-persist to repository."""
        # 1. Zero-cost local rule extraction first (consumes 0 NIM tokens, 0ms latency)
        local_items = self._local_rule_extract(objective, outcome)
        if local_items:
            persisted: list[MemoryItem] = []
            for item in local_items:
                content = str(item.get("content", "")).strip()
                subj = str(item.get("subject") or "Project")
                pred = str(item.get("predicate") or "decision")
                obj_val = str(item.get("object") or content[:40])

                # Deduplicate: check if exact triplet or content already exists
                existing = await self.repo.search_memories(content, project_id=project_id, limit=5)
                if any(
                    e.content.strip().lower() == content.lower() or
                    (
                        e.subject and e.subject.lower() == subj.lower() and
                        e.predicate and e.predicate.lower() == pred.lower() and
                        e.object and e.object.lower() == obj_val.lower()
                    )
                    for e in existing
                ):
                    continue

                saved = await self.repo.add_triplet(
                    subject=subj,
                    predicate=pred,
                    obj=obj_val,
                    content=content,
                    memory_type=str(item.get("type", "fact")),
                    importance=float(item.get("importance", 1.0)),
                    scope=scope,
                    project_id=project_id,
                    metadata={"auto_extracted": True, "source": "local_rule"},
                )
                persisted.append(saved)
            return persisted

        # Only run LLM if substantive outcome occurred and NIM cooldown has passed
        if not observations and len(outcome.strip()) < 30:
            return []

        now = time.time()
        if isinstance(self.provider, NvidiaNimProvider) and (now - MemoryExtractor._last_nim_call_time) < self.NIM_RATE_LIMIT_COOLDOWN_SEC:
            return []
        MemoryExtractor._last_nim_call_time = now

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
            "Task: Extract 1 to 3 durable technical facts, architectural decisions, project conventions, or developer preferences learned from this execution.\n"
            "Do NOT extract transient status or trivial file paths. Only extract durable, long-term technical knowledge.\n"
            "Format: Output EXACTLY ONE JSON array of objects:\n"
            "[\n"
            '  {"subject": "<Entity>", "predicate": "<relation>", "object": "<Target>", "content": "<concise factual statement>", "type": "fact"|"decision"|"preference", "importance": 1.0}\n'
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

                saved = await self.repo.add_triplet(
                    subject=str(item.get("subject") or "Project"),
                    predicate=str(item.get("predicate") or "decision"),
                    obj=str(item.get("object") or content[:40]),
                    content=content,
                    memory_type=str(item.get("type", "fact")),
                    importance=float(item.get("importance", 1.0)),
                    scope=scope,
                    project_id=project_id,
                    metadata={"auto_extracted": True, "source_objective": objective[:100]},
                )
                persisted.append(saved)

            return persisted
        except Exception:
            return []


# 6. Public exports
__all__ = ["ExtractedMemory", "MemoryExtractor"]

