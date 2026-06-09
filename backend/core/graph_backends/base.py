"""Abstract graph backend interface for the Context Graph OS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GraphBackend(ABC):
    """Pluggable storage backend for ContextGraph.

    Implementations must support node/edge CRUD and subgraph extraction.
    """

    @abstractmethod
    async def add_node(self, node_id: str, data: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_node(self, node_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def has_node(self, node_id: str) -> bool: ...

    @abstractmethod
    async def add_edge(self, source_id: str, target_id: str, edge_type: str, data: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_neighbors(self, node_id: str, depth: int = 2) -> dict[str, Any]: ...

    @abstractmethod
    async def get_nodes_by_type(self, node_type: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def to_json(self) -> dict[str, Any]: ...

    @abstractmethod
    async def all_nodes(self) -> list[tuple[str, dict[str, Any]]]: ...
