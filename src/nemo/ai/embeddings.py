"""NVIDIA NIM dense vector embeddings and cosine similarity retrieval engine."""

# 1. Standard library imports
import math
from typing import Sequence

# 2. Third-party imports
from openai import AsyncOpenAI

# 3. Local / internal imports
from nemo.config.settings import get_settings

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class NvidiaEmbeddingProvider:
    """NVIDIA NIM embedding provider using nvidia/nemotron-3.5-embed-1b."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "nvidia/nemotron-3.5-embed-1b",
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.nvidia_api_key
        self.base_url = base_url or settings.nvidia_base_url
        self.model = model
        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)

    async def embed_query(self, query: str) -> list[float]:
        """Generate dense embedding for search query."""
        if not self.api_key:
            return []
        try:
            res = await self.client.embeddings.create(
                model=self.model,
                input=[query],
                extra_body={"input_type": "query"},
            )
            return res.data[0].embedding
        except Exception:
            # Fallback to secondary compatible nemotron model
            try:
                res2 = await self.client.embeddings.create(
                    model="nvidia/nemotron-3-embed-1b",
                    input=[query],
                )
                return res2.data[0].embedding
            except Exception:
                return []

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        """Batch generate embeddings for code chunks or documents."""
        if not self.api_key or not documents:
            return []
        try:
            # Batch in chunks of 16 to respect payload limits
            results: list[list[float]] = []
            for i in range(0, len(documents), 16):
                batch = documents[i : i + 16]
                res = await self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    extra_body={"input_type": "passage"},
                )
                results.extend([item.embedding for item in res.data])
            return results
        except Exception:
            return []

# 6. Public exports
__all__ = ["NvidiaEmbeddingProvider", "cosine_similarity"]
