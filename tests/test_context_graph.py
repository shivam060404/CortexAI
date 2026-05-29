import pytest
import asyncio
from backend.core.context_graph import ContextGraph
from backend.core.trust_engine import TrustEngine
from backend.agents.cro_agent import get_cro_supervisor_agent
from backend.agents.search_agent import create_search_agent
from backend.agents.verification_agent import create_verification_agent
from backend.core.graph import build_graph

@pytest.mark.asyncio
async def test_context_graph_creation():
    # Test Graph OS initialization
    graph = ContextGraph("test_session_123")
    assert graph.session_id == "test_session_123"
    
    # Test Node addition with Trust Engine interception
    properties = {
        "url": "https://nature.com/article1",
        "content": "This is a scientific paper.",
        "citations": 5
    }
    node = graph.add_node("Source", properties)
    
    assert node.type == "Source"
    assert "trust_metrics" in node.properties
    assert node.properties["trust_metrics"]["trust_score"] == 0.95  # Based on TRUSTED_DOMAINS
    assert node.version == 1

@pytest.mark.asyncio
async def test_multi_agent_graph_compilation():
    # Verify the CRO Supervisor graph builds successfully without throwing errors
    compiled_graph = await build_graph("test_session_456")
    
    # Assert nodes exist in LangGraph
    assert "CRO" in compiled_graph.nodes
    assert "SearchAgent" in compiled_graph.nodes
    assert "VerificationAgent" in compiled_graph.nodes
