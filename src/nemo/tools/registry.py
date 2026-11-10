"""Tool registry for managing and dispatching agent tools."""

# 1. Standard library imports
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.common.types import RiskLevel, ToolResult
from nemo.security.policy import SecurityPolicy
from nemo.tools.base import BaseTool, ToolDefinition
from nemo.tools.builtin import (
    IDEOpenTool,
    ListDirectoryTool,
    MemoryRecallTool,
    ReadFileTool,
    TerminalTool,
    WriteFileTool,
)

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class ToolRegistry:
    """Manages available agent tools, schemas, and safe execution dispatch."""

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self.policy = policy or SecurityPolicy()
        self._tools: dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register core development tools."""
        self.register(TerminalTool())
        self.register(ReadFileTool())
        self.register(WriteFileTool(policy=self.policy))
        self.register(ListDirectoryTool())
        self.register(MemoryRecallTool())
        self.register(IDEOpenTool())

    def register(self, tool: BaseTool) -> None:
        """Register a new tool."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool | None:
        """Retrieve tool by name."""
        return self._tools.get(name)

    def get_definitions(self) -> list[ToolDefinition]:
        """Return definitions of all registered tools."""
        return [tool.get_definition() for tool in self._tools.values()]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Assess risk and execute registered tool."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: '{name}'")

        ctx = context or {}
        # Evaluate security risk within active context
        risk = self.policy.assess_tool_risk(name, arguments, context=ctx)
        if risk == RiskLevel.L3:
            return ToolResult(
                success=False,
                error=f"Security Policy Blocked: Action evaluated as High Risk ({risk.value})",
            )

        return await tool.execute(arguments, ctx)

# 6. Public exports
__all__ = ["ToolRegistry"]
