"""Base tool interface and schemas."""

# 1. Standard library imports
from typing import Any, Protocol

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
from nemo.common.types import RiskLevel, ToolResult

# 4. Types, Protocols, Schemas
class ToolDefinition(BaseModel):
    """Schema descriptor of an agent tool for LLM function calling."""
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.L0


class BaseTool(Protocol):
    """Protocol for tools callable by agent."""
    name: str
    description: str
    risk_level: RiskLevel

    def get_definition(self) -> ToolDefinition:
        """Return LLM-compatible tool definition."""
        ...

    async def execute(self, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        """Execute tool logic and return standard ToolResult."""
        ...

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["BaseTool", "ToolDefinition"]

