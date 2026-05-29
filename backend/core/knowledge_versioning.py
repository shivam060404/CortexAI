"""
Knowledge Versioning for the Context Graph.
Tracks temporal changes and the provenance of knowledge modifications.
"""
from typing import Dict, Any, List
import time
from backend.core.logger import get_logger

logger = get_logger(__name__)

class KnowledgeVersionTracker:
    def __init__(self):
        # Maps node_id -> List of historical states
        self._history: Dict[str, List[Dict[str, Any]]] = {}

    def track_change(self, node_id: str, new_properties: Dict[str, Any], agent_name: str, reason: str = ""):
        """
        Records a modification to a node, preserving its prior state.
        """
        if node_id not in self._history:
            self._history[node_id] = []
            
        record = {
            "timestamp": time.time(),
            "properties": new_properties.copy(),
            "modified_by_agent": agent_name,
            "reason": reason
        }
        
        self._history[node_id].append(record)
        logger.debug("knowledge_version_tracked", node_id=node_id, agent=agent_name, reason=reason)

    def get_history(self, node_id: str) -> List[Dict[str, Any]]:
        """Retrieve the evolutionary history of a node."""
        return self._history.get(node_id, [])

# Singleton tracker for the session (ideally this would be bound to the ContextGraph instance)
version_tracker = KnowledgeVersionTracker()
