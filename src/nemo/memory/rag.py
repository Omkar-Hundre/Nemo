"""Unified Semantic RAG Engine across Knowledge Graph, Historical Tasks, and Developer Profile."""

# 1. Standard library imports
import asyncio
from collections import Counter
import logging
import math
import re
from typing import Any, Sequence

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.ai.embeddings import NvidiaEmbeddingProvider, cosine_similarity
from nemo.memory.backfill import KnowledgeGraphBootstrapper
from nemo.memory.repository import (
    MemoryRepository,
    TaskRepository,
    UserProfileRepository,
)

logger = logging.getLogger(__name__)


# 4. Helper vectorizer fallback
def _char_ngram_vector(text: str, n: int = 3) -> dict[str, float]:
    """Compute normalized character n-gram frequency vector for offline semantic similarity."""
    clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = clean.split()
    ngrams: list[str] = []
    for w in words:
        if len(w) < n:
            ngrams.append(w)
        else:
            for i in range(len(w) - n + 1):
                ngrams.append(w[i : i + n])

    counts = Counter(ngrams)
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def _sparse_cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Calculate cosine similarity between two sparse n-gram vectors."""
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    return sum(vec_a[k] * vec_b[k] for k in common_keys)


# 5. Core logic / classes / functions
class UnifiedMemoryRAG:
    """Consolidated semantic retrieval engine indexing Developer Profile, Knowledge Graph, and Historical Tasks."""

    def __init__(
        self,
        embed_provider: NvidiaEmbeddingProvider | None = None,
        mem_repo: MemoryRepository | None = None,
        user_repo: UserProfileRepository | None = None,
        task_repo: TaskRepository | None = None,
    ) -> None:
        self.embed_provider = embed_provider or NvidiaEmbeddingProvider()
        self.mem_repo = mem_repo or MemoryRepository()
        self.user_repo = user_repo or UserProfileRepository()
        self.task_repo = task_repo or TaskRepository()
        self._bootstrapped = False

    async def _ensure_bootstrapped(self) -> None:
        """Ensure baseline profile and triplets exist in database."""
        if self._bootstrapped:
            return
        profile = await self.user_repo.get_profile()
        if not profile:
            bootstrapper = KnowledgeGraphBootstrapper(
                mem_repo=self.mem_repo,
                user_repo=self.user_repo,
                task_repo=self.task_repo,
            )
            await bootstrapper.run()
        self._bootstrapped = True

    async def search_historical_tasks(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        """Semantically search past tasks executed days, weeks, or months ago."""
        tasks = await self.task_repo.list_tasks(limit=120)
        if not tasks:
            return []

        # Try dense embeddings if available
        query_dense = await self.embed_provider.embed_query(query)
        scored_tasks: list[tuple[float, Any]] = []

        if query_dense:
            task_texts = [f"{t.objective} ({t.status})" for t in tasks[:32]]
            try:
                task_embeddings = await self.embed_provider.embed_documents(task_texts)
                for t, emb in zip(tasks[:32], task_embeddings):
                    sim = cosine_similarity(query_dense, emb)
                    scored_tasks.append((sim, t))
            except Exception:
                pass

        # Fallback to sparse semantic vectorizer if dense is unavailable
        if not scored_tasks:
            q_vec = _char_ngram_vector(query)
            for t in tasks:
                t_vec = _char_ngram_vector(t.objective)
                sim = _sparse_cosine_similarity(q_vec, t_vec)
                scored_tasks.append((sim, t))

        scored_tasks.sort(key=lambda x: x[0], reverse=True)
        # Filter top matches with score threshold
        results = []
        for score, t in scored_tasks[:limit]:
            if score > 0.08:
                results.append({
                    "objective": t.objective,
                    "status": t.status,
                    "created_at": t.created_at.strftime("%Y-%m-%d") if t.created_at else "past",
                    "score": round(score, 3),
                })
        return results

    async def search_knowledge_triplets(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """Search knowledge graph relations matching entities in the query."""
        triplets = await self.mem_repo.list_triplets()
        if not triplets:
            return []

        q_lower = query.lower()
        q_tokens = set(re.findall(r"\w+", q_lower))

        scored_triplets: list[tuple[float, dict[str, Any]]] = []
        for trip in triplets:
            subj = str(trip.get("subject", "")).lower()
            pred = str(trip.get("predicate", "")).lower()
            obj = str(trip.get("object", "")).lower()
            content = str(trip.get("content", "")).lower()

            score = 0.0
            if subj in q_lower or any(tok in subj for tok in q_tokens if len(tok) >= 3):
                score += 0.5
            if pred.replace("_", " ") in q_lower:
                score += 0.3
            if obj in q_lower or any(tok in obj for tok in q_tokens if len(tok) >= 3):
                score += 0.4
            if any(tok in content for tok in q_tokens if len(tok) >= 4):
                score += 0.2

            score *= float(trip.get("importance", 1.0))
            if score > 0:
                scored_triplets.append((score, trip))

        scored_triplets.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_triplets[:limit]]

    async def retrieve_context(self, query: str, project_id: str | None = None) -> str:
        """Generate high-density unified memory context block for agent reasoning."""
        await self._ensure_bootstrapped()

        # 1. Fetch Developer Profile
        profile = await self.user_repo.get_or_create_profile()
        prefs = profile.preferences or {}
        profile_line = (
            f"Developer Profile: {profile.name} | OS: {prefs.get('os', 'Windows')} | "
            f"IDE: {prefs.get('ide', 'Antigravity IDE')} | Browser: {prefs.get('browser', 'Brave')} | "
            f"Stack: {', '.join(prefs.get('python_stack', ['Python 3.12', 'UV']))}"
        )

        # 2. Semantic memories search
        memories = await self.mem_repo.search_memories(query, project_id=project_id, limit=5)

        # 3. Knowledge Graph triplets search
        triplets = await self.search_knowledge_triplets(query, limit=5)

        # 4. Historical tasks RAG search (tasks from months or days ago)
        tasks = await self.search_historical_tasks(query, limit=4)

        sections = [f"[NEMO UNIFIED MEMORY & KNOWLEDGE GRAPH]\n• {profile_line}"]

        if triplets:
            t_lines = ["• Knowledge Graph Entities & Relations:"]
            for t in triplets:
                t_lines.append(f"  - [{t.get('subject')}] ── {t.get('predicate')} ──► {t.get('object')}")
            sections.append("\n".join(t_lines))

        if memories:
            m_lines = ["• Architectural Decisions & Facts:"]
            for m in memories:
                m_lines.append(f"  - {m.content}")
            sections.append("\n".join(m_lines))

        if tasks:
            task_lines = ["• Relevant Historical Tasks (Past Executions):"]
            for tk in tasks:
                task_lines.append(f"  - [{tk['created_at']}] {tk['objective']} ({tk['status']})")
            sections.append("\n".join(task_lines))

        return "\n\n".join(sections)


# 6. Public exports
__all__ = ["UnifiedMemoryRAG"]
