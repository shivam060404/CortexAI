"""
Deep Agent — core research agent factory.
Creates a LangGraph ReAct-style agent with all tools, ExecutionGuard, and ToolPermissionGuard.
"""

from langchain_openai import ChatOpenAI as ChatLiteLLM
from backend.config import settings
from backend.tools.search_tools import get_search_tools
from backend.tools.fs_tools import get_fs_tools
from backend.tools.planning_tools import get_planning_tools
from backend.tools.subagent_tools import get_subagent_tools
from backend.tools.research_loop_tools import get_research_loop_tools
from backend.tools.kg_tools import get_kg_tools
from backend.tools.experiment_tools import get_experiment_tools
from backend.tools.reflection_tools import get_reflection_tools
from backend.tools.sandbox_tools import get_sandbox_tools
from backend.tools.debate_tools import get_debate_tools
from backend.tools.export_tools import get_export_tools
from backend.agents.prompts import MAIN_RESEARCHER_PROMPT
from backend.core.logger import get_logger
from backend.mcp.global_registry import mcp_client

logger = get_logger(__name__)


def create_research_agent(session_id: str, user_memory_context: str = ""):
    """Build the deep research agent with all tools bound.

    Returns:
        tuple: (llm_with_tools, tools_list, system_prompt)
    """
    # Collect all tools for this session
    search_tools = get_search_tools()
    fs_tools = get_fs_tools(session_id)
    planning_tools = get_planning_tools(session_id)
    subagent_tools = get_subagent_tools(session_id)
    research_loop_tools = get_research_loop_tools(session_id)
    kg_tools = get_kg_tools(session_id)
    experiment_tools = get_experiment_tools(session_id)
    reflection_tools = get_reflection_tools(session_id)
    sandbox_tools = get_sandbox_tools(session_id)
    debate_tools = get_debate_tools(session_id)
    export_tools = get_export_tools(session_id)

    all_tools = (
        search_tools
        + fs_tools
        + planning_tools
        + subagent_tools
        + research_loop_tools
        + kg_tools
        + experiment_tools
        + reflection_tools
        + sandbox_tools
        + debate_tools
        + export_tools
    )

    if settings.MCP_ENABLED:
        try:
            mcp_tools = mcp_client.get_langchain_tools()
            all_tools.extend(mcp_tools)
        except Exception as e:
            logger.error("mcp_tools_load_error", error=str(e))

    # Create LLM with tools bound
    llm = ChatLiteLLM(
        model=settings.ORCHESTRATOR_MODEL,
        temperature=settings.LLM_TEMPERATURE,
    )

    llm_with_tools = llm.bind_tools(all_tools)

    logger.info("agent_created", session_id=session_id,
                 tools=[t.name for t in all_tools])

    final_prompt = MAIN_RESEARCHER_PROMPT
    if user_memory_context:
        final_prompt += f"\n\n### USER PERSONALIZED MEMORY ###\n{user_memory_context}\nUse this context to prioritize research directions if applicable."

    return llm_with_tools, all_tools, final_prompt
