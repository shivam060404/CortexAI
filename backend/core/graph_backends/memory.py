"""NetworkX in-memory graph backend — the default for single-instance deployments."""

from __future__ import annotations

from typing import Any

import networkx as nx

from backend.core.graph_backends.base import GraphBackend


class NetworkXBackend(GraphBackend):
    """Wraps a NetworkX MultiDiGraph for in-memory graph operations."""

    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()

    async def add_node(self, node_id: str, data: dict[str, Any]) -> None:
        self.graph.add_node(node_id, **data)

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        if self.graph.has_node(node_id):
            return dict(self.graph.nodes[node_id])
        return None

    async def has_node(self, node_id: str) -> bool:
        return self.graph.has_node(node_id)

    async def add_edge(self, source_id: str, target_id: str, edge_type: str, data: dict[str, Any]) -> None:
        self.graph.add_edge(source_id, target_id, key=edge_type, **data)

    async def get_neighbors(self, node_id: str, depth: int = 2) -> dict[str, Any]:
        if not self.graph.has_node(node_id):
            return {}

        outbound = nx.single_source_shortest_path_length(self.graph, node_id, cutoff=depth)
        rev = self.graph.reverse()
        inbound = nx.single_source_shortest_path_length(rev, node_id, cutoff=depth)

        all_nodes = set(outbound.keys()) | set(inbound.keys())
        subgraph = self.graph.subgraph(all_nodes)
        return nx.node_link_data(subgraph)

    async def get_nodes_by_type(self, node_type: str) -> list[dict[str, Any]]:
        return [
            {"id": nid, **attrs}
            for nid, attrs in self.graph.nodes(data=True)
            if attrs.get("type") == node_type
        ]

    async def all_nodes(self) -> list[tuple[str, dict[str, Any]]]:
        return [(nid, dict(attrs)) for nid, attrs in self.graph.nodes(data=True)]

    async def to_json(self) -> dict[str, Any]:
        return nx.node_link_data(self.graph)
