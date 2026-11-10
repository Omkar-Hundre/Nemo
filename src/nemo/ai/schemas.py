"""Schemas for AI model requests and responses."""

# 1. Standard library imports
from typing import Any, Literal
from pydantic import BaseModel, Field

# 2. Third-party imports
# (None)

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
RoleType = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """Normalized chat message."""
    role: RoleType
    content: str


class LLMResponse(BaseModel):
    """Normalized response from an AI provider."""
    content: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    finish_reason: str | None = None
    raw_response: dict[str, Any] | None = None

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["RoleType", "ChatMessage", "LLMResponse"]
