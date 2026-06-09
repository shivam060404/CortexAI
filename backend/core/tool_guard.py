"""
Tool Safety & Guardrails — permission layer + path sandboxing + execution limits.
Validates every tool invocation against the allowed tools list.
Enforces per-tool timeout and max output size (Arch Issue #3, Pillar 1).
"""

import asyncio
import time
from typing import Any, Awaitable, Callable

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ToolNotAllowed(Exception):
    """Raised when an agent tries to use a tool not in the allowlist."""
    pass


class ToolTimeoutExceeded(Exception):
    """Raised when a tool execution exceeds its timeout."""
    pass


class ToolOutputTooLarge(Exception):
    """Raised when a tool's output exceeds the max size."""
    pass


class ToolPermissionGuard:
    """Validates tool calls against the configured allowed-tools list.
    
    Also enforces execution timeout and output size limits (Pillar 1).
    """

    def __init__(self, allowed_tools: list[str] | None = None):
        self.allowed = set(allowed_tools or settings.ALLOWED_TOOLS)
        self._execution_counts: dict[str, int] = {}  # Track per-tool execution counts

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

    def record_execution(self, tool_name: str):
        """Track execution count for a tool (for observability)."""
        self._execution_counts[tool_name] = self._execution_counts.get(tool_name, 0) + 1

    def get_execution_stats(self) -> dict[str, int]:
        """Return per-tool execution counts."""
        return dict(self._execution_counts)

    def truncate_output(self, output: str) -> str:
        """Truncate tool output if it exceeds max size (Pillar 1)."""
        max_size = settings.TOOL_MAX_OUTPUT_SIZE
        if len(output) > max_size:
            logger.warning(
                "tool_output_truncated",
                original_size=len(output),
                max_size=max_size,
            )
            return output[:max_size] + f"\n[TRUNCATED: output exceeded {max_size} chars]"
        return output

    async def execute_with_timeout(
        self,
        tool_name: str,
        coroutine: Awaitable[Any],
        timeout: float | None = None,
    ) -> Any:
        """Execute a tool coroutine with timeout enforcement (Pillar 1).

        Args:
            tool_name: Name of the tool being executed.
            coroutine: The awaitable to run.
            timeout: Override timeout in seconds; defaults to TOOL_EXECUTION_TIMEOUT.

        Raises:
            ToolTimeoutExceeded: If the tool exceeds its execution time.
        """
        effective_timeout = timeout or settings.TOOL_EXECUTION_TIMEOUT
        start = time.time()
        try:
            result = await asyncio.wait_for(coroutine, timeout=effective_timeout)
            elapsed = time.time() - start
            self.record_execution(tool_name)
            logger.debug("tool_execution_complete", tool=tool_name, elapsed_ms=round(elapsed * 1000, 1))
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "tool_execution_timeout",
                tool=tool_name,
                timeout=effective_timeout,
            )
            raise ToolTimeoutExceeded(
                f"Tool '{tool_name}' exceeded {effective_timeout}s execution timeout."
            )
