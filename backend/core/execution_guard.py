"""
Execution Control Layer — prevents runaway agents.
Tracks iterations, tool calls, tokens used, and wall-clock time per session.
Raises ExecutionLimitExceeded if any budget is exhausted.
"""

import time
from dataclasses import dataclass, field

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ExecutionLimitExceeded(Exception):
    """Raised when an agent exceeds its execution budget."""
    def __init__(self, metric: str, current: float, limit: float):
        self.metric = metric
        self.current = current
        self.limit = limit
        super().__init__(f"Execution limit exceeded: {metric}={current} (limit={limit})")


@dataclass
class ExecutionGuard:
    """Per-session execution budget tracker.

    Usage:
        guard = ExecutionGuard(max_iterations=20, max_tokens=50000, timeout=120)
        guard.check()  # call before each iteration
        guard.record_tool_call()
        guard.record_tokens(500)
    """
    max_iterations: int = field(default_factory=lambda: settings.MAX_ITERATIONS)
    max_tokens: int = field(default_factory=lambda: settings.MAX_TOKENS_PER_SESSION)
    timeout: int = field(default_factory=lambda: settings.AGENT_TIMEOUT_SECONDS)
    max_usd: float = field(default_factory=lambda: settings.GUARD_MAX_USD)

    # Tracked counters
    iterations_count: int = 0
    tool_calls_count: int = 0
    tokens_used: int = 0
    spent_usd: float = 0.0
    _start_time: float = field(default_factory=time.time)

    @property
    def time_elapsed(self) -> float:
        return time.time() - self._start_time

    def check(self):
        """Check all limits. Raises ExecutionLimitExceeded if breached."""
        if self.iterations_count >= self.max_iterations:
            logger.warning("limit_exceeded", metric="iterations",
                           current=self.iterations_count, limit=self.max_iterations)
            raise ExecutionLimitExceeded("iterations", self.iterations_count, self.max_iterations)

        if self.tokens_used >= self.max_tokens:
            logger.warning("limit_exceeded", metric="tokens",
                           current=self.tokens_used, limit=self.max_tokens)
            raise ExecutionLimitExceeded("tokens", self.tokens_used, self.max_tokens)

        elapsed = self.time_elapsed
        if elapsed >= self.timeout:
            logger.warning("limit_exceeded", metric="timeout_seconds",
                           current=elapsed, limit=self.timeout)
            raise ExecutionLimitExceeded("timeout_seconds", elapsed, self.timeout)

        if self.spent_usd >= self.max_usd:
            logger.warning("limit_exceeded", metric="spent_usd",
                           current=self.spent_usd, limit=self.max_usd)
            raise ExecutionLimitExceeded("spent_usd", self.spent_usd, self.max_usd)

    def record_iteration(self):
        self.iterations_count += 1
        logger.debug("iteration", count=self.iterations_count,
                     tokens=self.tokens_used, elapsed=round(self.time_elapsed, 1))

    def record_tool_call(self):
        self.tool_calls_count += 1

    def record_tokens(self, count: int, input_tokens: int = 0, output_tokens: int = 0):
        self.tokens_used += count
        
        # Calculate cost
        in_cost = (input_tokens / 1_000_000) * settings.COST_PER_1M_INPUT_TOKENS
        out_cost = (output_tokens / 1_000_000) * settings.COST_PER_1M_OUTPUT_TOKENS
        
        # Fallback if specific breakdown not provided
        if input_tokens == 0 and output_tokens == 0 and count > 0:
            in_cost = (count / 1_000_000) * settings.COST_PER_1M_INPUT_TOKENS # Conservative fallback
            
        self.spent_usd += (in_cost + out_cost)

    def record_search_call(self):
        self.spent_usd += settings.COST_PER_SEARCH_API

    def metrics(self) -> dict:
        """Return snapshot of current execution metrics."""
        return {
            "iterations_count": self.iterations_count,
            "tool_calls_count": self.tool_calls_count,
            "tokens_used": self.tokens_used,
            "time_elapsed": round(self.time_elapsed, 2),
            "spent_usd": round(self.spent_usd, 4),
            "limits": {
                "max_iterations": self.max_iterations,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout,
                "max_usd": self.max_usd,
            },
        }
