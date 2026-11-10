"""AI Provider interface specification."""

# 1. Standard library imports
from typing import AsyncIterator, Protocol

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.ai.schemas import ChatMessage, LLMResponse

# 4. Types, Protocols, Schemas
class AIProvider(Protocol):
    """Protocol for model inference providers."""

    async def generate(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a complete response from the model."""
        ...

    async def stream(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream response chunks from the model."""
        ...

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["AIProvider"]

