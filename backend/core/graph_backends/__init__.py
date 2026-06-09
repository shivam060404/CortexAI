"""Pluggable graph backends for the CortexAI Context Graph."""

from backend.core.graph_backends.base import GraphBackend
from backend.core.graph_backends.memory import NetworkXBackend
from backend.core.graph_backends.redis import RedisGraphBackend


def create_backend(backend_type: str = "memory", **kwargs) -> GraphBackend:
    """Factory: create the appropriate graph backend."""
    if backend_type == "redis":
        return RedisGraphBackend(**kwargs)
    return NetworkXBackend()
