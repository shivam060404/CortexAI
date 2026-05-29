"""
Search Agent Worker.
Specialized agent for searching and populating the Context Graph.
"""
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI as ChatLiteLLM
from backend.config import settings
from backend.tools.search_tools import get_search_tools

SEARCH_AGENT_PROMPT = """You are the CortexAI Search Agent.
Your sole responsibility is to use search tools (Tavily, Exa, Firecrawl) to find high-quality information 
relevant to the user's query and extract it. 
When you find information, it will automatically be converted into [Source] and [Finding] nodes in the Context Graph.

Search exhaustively. When you are done, return a summary of what you searched for.
"""

def create_search_agent():
    """Creates the specialized search agent."""
    llm = ChatLiteLLM(
        model=settings.ORCHESTRATOR_MODEL,
        temperature=settings.LLM_TEMPERATURE,
    )
    
    tools = get_search_tools()
    llm_with_tools = llm.bind_tools(tools)
    
    return llm_with_tools, tools, SEARCH_AGENT_PROMPT
