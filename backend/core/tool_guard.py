"""
Tool Safety & Guardrails — permission layer + path sandboxing.
Validates every tool invocation against the allowed tools list.
"""

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ToolNotAllowed(Exception):
    """Raised when an agent tries to use a tool not in the allowlist."""
    pass


class ToolPermissionGuard:
    """Validates tool calls against the configured allowed-tools list."""

    def __init__(self, allowed_tools: list[str] | None = None):
        self.allowed = set(allowed_tools or settings.ALLOWED_TOOLS)

    def check(self, tool_name: str):
        """Raise ToolNotAllowed if tool is not in the allowlist."""
        if tool_name not in self.allowed:
            logger.warning("tool_blocked", tool=tool_name, allowed=list(self.allowed))
            raise ToolNotAllowed(
                f"Tool '{tool_name}' is not allowed. Permitted tools: {sorted(self.allowed)}"
            )
        logger.debug("tool_permitted", tool=tool_name)

    def grant(self, tool_name: str):
        """Dynamically add a tool to the allowed set."""
        self.allowed.add(tool_name)

    def revoke(self, tool_name: str):
        """Remove a tool from the allowed set."""
        self.allowed.discard(tool_name)
