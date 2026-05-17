"""
Error Recovery — retry with exponential backoff + circuit breaker.
Uses tenacity for retries and a simple circuit breaker for external APIs.
"""

import time
import functools
from typing import Callable, Any

from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log,
)
import logging

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)
_py_logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_retries: int | None = None,
    backoff_factor: float | None = None,
    exceptions: tuple = (Exception,),
):
    """Decorator: retry with exponential backoff on specified exceptions."""
    _max = max_retries or settings.MAX_RETRIES
    _back = backoff_factor or settings.RETRY_BACKOFF_FACTOR

    def decorator(func):
        @retry(
            stop=stop_after_attempt(_max),
            wait=wait_exponential(multiplier=_back, min=1, max=30),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(_py_logger, logging.WARNING),
            reraise=True,
        )
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        @retry(
            stop=stop_after_attempt(_max),
            wait=wait_exponential(multiplier=_back, min=1, max=30),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(_py_logger, logging.WARNING),
            reraise=True,
        )
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class CircuitBreaker:
    """Simple circuit breaker for external APIs.

    If `threshold` consecutive failures occur, the circuit opens and
    calls are rejected for `reset_timeout` seconds.
    """

    def __init__(self, threshold: int | None = None, reset_timeout: float = 60.0):
        self.threshold = threshold or settings.CIRCUIT_BREAKER_THRESHOLD
        self.reset_timeout = reset_timeout
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._is_open = False

    def check(self, service_name: str = "external"):
        """Raise if circuit is open."""
        if self._is_open:
            if (time.time() - self._last_failure_time) > self.reset_timeout:
                self._is_open = False
                self._failure_count = 0
                logger.info("circuit_breaker_reset", service=service_name)
            else:
                raise ConnectionError(
                    f"Circuit breaker OPEN for {service_name}. "
                    f"Retry after {self.reset_timeout}s."
                )

    def record_success(self):
        self._failure_count = 0
        self._is_open = False

    def record_failure(self, service_name: str = "external"):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.threshold:
            self._is_open = True
            logger.error("circuit_breaker_open", service=service_name,
                         failures=self._failure_count)
