import time
import uuid
import networkx as nx
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from backend.core.logger import get_logger
from backend.core.trust_engine import TrustEngine
from backend.core.knowledge_versioning import version_tracker
from backend.config import settings

logger = get_logger(__name__)

@dataclass
class GraphNode:
    id: str
    type: str  # User, Session, Source, Entity, Finding, Hypothesis, Observation, ToolCall, Document
    properties: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    type: str  # GENERATES, SUPPORTED_BY, INVALIDATES, CONFIRMS, EXTRACTED_FROM
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

class ContextGraph:
    """
    Central Operating System Graph for CortexAI.
    Manages Nodes (Entities, Sources, Findings) and Edges (Relationships).

    Supports pluggable backends (Arch Issue #1):
      - ``memory`` (default): NetworkX in-process MultiDiGraph
      - ``redis``: Redis-backed graph for horizontal scaling

    The sync NetworkX API is retained for backward compatibility with
    existing graph.py callers; when ``GRAPH_BACKEND=redis`` the sync
    methods still operate on a local NetworkX mirror while async
    ``a_*`` methods persist to Redis.
    """
    def __init__(self, session_id: str, backend=None):
        self.session_id = session_id
        self.graph = nx.MultiDiGraph()
        self.trust_engine = TrustEngine()

        # Pluggable backend (async-capable)
        if backend is not None:
            self._backend = backend
        else:
            self._backend = None  # None = pure NetworkX (legacy path)

        logger.info("context_graph_initialized",
                     session_id=self.session_id,
                     backend=type(self._backend).__name__ if self._backend else "networkx")
        
        # Initialize root node for the session
        self.add_node("Session", {"session_id": session_id}, node_id=f"session_{session_id}")

    def add_node(self, node_type: str, properties: Dict[str, Any], node_id: Optional[str] = None) -> GraphNode:
        """Add a new node to the Context Graph."""
        node_id = node_id or f"{node_type.lower()}_{uuid.uuid4().hex[:8]}"
        
        # If this is a Source node, run it through the Trust Engine
        if node_type == "Source" and "url" in properties:
            trust_metrics = self.trust_engine.evaluate_source(
                url=properties.get("url"),
                content=properties.get("content", ""),
                citations=properties.get("citations", 0)
            )
            properties["trust_metrics"] = trust_metrics
            
        # Check for versioning
        version = 1
        if self.graph.has_node(node_id):
            existing_data = self.graph.nodes[node_id].get("data")
            if existing_data:
                version = existing_data.version + 1
                
        node = GraphNode(id=node_id, type=node_type, properties=properties, version=version)
        self.graph.add_node(node.id, data=node)

        # Mirror to pluggable backend if present
        if self._backend is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._backend.add_node(
                    node_id,
                    {"type": node_type, "properties": properties, "version": version,
                     "created_at": node.created_at, "updated_at": node.updated_at},
                ))
            except RuntimeError:
                pass  # No running loop; sync-only usage
        
        # Track version
        version_tracker.track_change(node_id, properties, agent_name="ContextGraphSystem")
        
        logger.debug("graph_node_added", node_id=node.id, type=node.type, version=version)
        return node

    def add_edge(self, source_id: str, target_id: str, edge_type: str, properties: Optional[Dict[str, Any]] = None) -> GraphEdge:
        """Add a directed edge between two nodes."""
        if not properties:
            properties = {}
            
        if not self.graph.has_node(source_id) or not self.graph.has_node(target_id):
            raise ValueError(f"Cannot add edge {edge_type}: Source or Target node does not exist.")
            
        edge = GraphEdge(source_id=source_id, target_id=target_id, type=edge_type, properties=properties)
        self.graph.add_edge(source_id, target_id, key=edge_type, data=edge)

        # Mirror to pluggable backend if present
        if self._backend is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._backend.add_edge(
                    source_id, target_id, edge_type,
                    {"properties": properties, "created_at": edge.created_at},
                ))
            except RuntimeError:
                pass
        
        logger.debug("graph_edge_added", source=source_id, target=target_id, type=edge_type)
        return edge

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        if self.graph.has_node(node_id):
            return self.graph.nodes[node_id].get("data")
        return None

    def get_nodes_by_type(self, node_type: str) -> List[GraphNode]:
        return [data["data"] for _, data in self.graph.nodes(data=True) if data["data"].type == node_type]

    def get_subgraph_context(self, focus_node_id: str, depth: int = 2) -> Dict[str, Any]:
        """Extract a local neighborhood around a node to pass as LLM context."""
        if not self.graph.has_node(focus_node_id):
            return {}
            
        subgraph_nodes = nx.single_source_shortest_path_length(self.graph, focus_node_id, cutoff=depth)
        
        # Include predecessors (incoming edges) as well
        rev_graph = self.graph.reverse()
        incoming_nodes = nx.single_source_shortest_path_length(rev_graph, focus_node_id, cutoff=depth)
        
        all_nodes = set(subgraph_nodes.keys()).union(set(incoming_nodes.keys()))
        subgraph = self.graph.subgraph(all_nodes)
        
        return nx.node_link_data(subgraph)

    def to_json(self) -> Dict[str, Any]:
        """Serialize the graph for persistence."""
        return nx.node_link_data(self.graph)

    # ------------------------------------------------------------------
    # Async API — delegates to pluggable backend when available
    # ------------------------------------------------------------------

    async def async_get_neighbors(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        """Async subgraph extraction via the pluggable backend."""
        if self._backend is not None:
            return await self._backend.get_neighbors(node_id, depth=depth)
        return self.get_subgraph_context(node_id, depth=depth)

    async def async_to_json(self) -> Dict[str, Any]:
        if self._backend is not None:
            return await self._backend.to_json()
        return self.to_json()
