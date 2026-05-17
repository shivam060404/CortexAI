"""
Structured JSON logging via structlog — agent trace events for observability.
"""

import sys
import logging
import structlog


def _setup_structlog():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


_setup_structlog()


def get_logger(name: str = __name__):
    """Get a structured logger bound to the given module name."""
    return structlog.get_logger(name)
