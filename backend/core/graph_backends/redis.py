"""Redis-backed graph backend — enables horizontal scaling across multiple CortexAI instances."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from backend.config import settings
from backend.core.graph_backends.base import GraphBackend
from backend.core.logger import get_logger

logger = get_logger(__name__)

_NODE_PREFIX = "cg:node:"
_EDGE_PREFIX = "cg:edge:"
_ADJ_PREFIX = "cg:adj:"  # adjacency set per node


class RedisGraphBackend(GraphBackend):
    """Stores graph nodes/edges in Redis for multi-instance deployments.

    Nodes are stored as JSON hashes keyed by ``cg:node:{session_id}:{node_id}``.
    Edges are stored as JSON strings in a Redis set per source node.
    Adjacency is tracked with a sorted set per node for traversal.

    Falls back to in-memory dicts when Redis is unavailable, so the system
    remains functional in single-instance / dev environments.
    """

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self._redis: aioredis.Redis | None = None
        # In-memory fallback
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, list[dict[str, Any]]] = {}
        self._adj: dict[str, set[str]] = {}

    async def _ensure_redis(self) -> bool:
        if self._redis is not None:
            return True
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
            await self._redis.ping()
            return True
        except Exception as exc:
            logger.warning("redis_graph_backend_fallback", error=str(exc))
            self._redis = None
            return False

    def _node_key(self, node_id: str) -> str:
        return f"{_NODE_PREFIX}{self.session_id}:{node_id}"

    def _edge_key(self, source_id: str) -> str:
        return f"{_EDGE_PREFIX}{self.session_id}:{source_id}"

    def _adj_key(self, node_id: str) -> str:
        return f"{_ADJ_PREFIX}{self.session_id}:{node_id}"

    # ---- Node operations ----

    async def add_node(self, node_id: str, data: dict[str, Any]) -> None:
        if await self._ensure_redis():
            await self._redis.set(self._node_key(node_id), json.dumps(data, default=str))
            return
        self._nodes[node_id] = data

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        if await self._ensure_redis():
            raw = await self._redis.get(self._node_key(node_id))
            return json.loads(raw) if raw else None
        return self._nodes.get(node_id)

    async def has_node(self, node_id: str) -> bool:
        if await self._ensure_redis():
            return bool(await self._redis.exists(self._node_key(node_id)))
        return node_id in self._nodes

    # ---- Edge operations ----

    async def add_edge(self, source_id: str, target_id: str, edge_type: str, data: dict[str, Any]) -> None:
        edge_data = {"source": source_id, "target": target_id, "type": edge_type, **data}
        if await self._ensure_redis():
            await self._redis.sadd(self._edge_key(source_id), json.dumps(edge_data, default=str))
            await self._redis.sadd(self._adj_key(source_id), target_id)
            await self._redis.sadd(self._adj_key(target_id), source_id)
            return
        self._edges.setdefault(source_id, []).append(edge_data)
        self._adj.setdefault(source_id, set()).add(target_id)
        self._adj.setdefault(target_id, set()).add(source_id)

    # ---- Traversal ----

    async def get_neighbors(self, node_id: str, depth: int = 2) -> dict[str, Any]:
        """BFS traversal up to *depth* hops using adjacency sets."""
        visited: set[str] = set()
        frontier: set[str] = {node_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                if nid in visited:
                    continue
                visited.add(nid)
                if await self._ensure_redis():
                    members = await self._redis.smembers(self._adj_key(nid))
                    next_frontier.update(members)
                else:
                    next_frontier.update(self._adj.get(nid, set()))
            frontier = next_frontier - visited

        nodes_out = []
        for nid in visited:
            node_data = await self.get_node(nid)
            if node_data is not None:
                nodes_out.append({"id": nid, **node_data})

        return {"nodes": nodes_out, "session_id": self.session_id}

    async def get_nodes_by_type(self, node_type: str) -> list[dict[str, Any]]:
        results = []
        all_nodes = await self.all_nodes()
        for nid, attrs in all_nodes:
            if attrs.get("type") == node_type:
                results.append({"id": nid, **attrs})
        return results

    async def all_nodes(self) -> list[tuple[str, dict[str, Any]]]:
        if await self._ensure_redis():
            pattern = f"{_NODE_PREFIX}{self.session_id}:*"
            nodes = []
            async for key in self._redis.scan_iter(match=pattern, count=100):
                raw = await self._redis.get(key)
                if raw:
                    node_id = key.split(":")[-1]
                    nodes.append((node_id, json.loads(raw)))
            return nodes
        return [(nid, dict(attrs)) for nid, attrs in self._nodes.items()]

    async def to_json(self) -> dict[str, Any]:
        all_n = await self.all_nodes()
        return {"nodes": [{"id": nid, **attrs} for nid, attrs in all_n], "session_id": self.session_id}
