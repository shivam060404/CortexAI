"""
Verification Agent Worker.
Cross-references claims in the Context Graph and updates Trust scores.
"""
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI as ChatLiteLLM
from backend.config import settings

VERIFICATION_AGENT_PROMPT = """You are the CortexAI Verification Agent.
Your job is to read the findings produced by the Search Agent and critically evaluate them.
Look for biases, logical fallacies, or contradicting evidence. 
Your analysis will update the Trust Engine scores for the Sources in the Context Graph.

Point out any inconsistencies. If everything looks solid, explicitly state that the claims are verified.
"""

def create_verification_agent():
    """Creates the specialized verification agent."""
    llm = ChatLiteLLM(
        model=settings.ORCHESTRATOR_MODEL,
        temperature=0.3,
    )
    
    # Needs reflection/verification tools
    from backend.tools.reflection_tools import get_reflection_tools
    tools = get_reflection_tools("global")
    
    llm_with_tools = llm.bind_tools(tools)
    
    return llm_with_tools, tools, VERIFICATION_AGENT_PROMPT
