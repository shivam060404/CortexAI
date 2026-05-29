"""
Chief Research Officer (CRO) Agent.
Acts as the Supervisor in the Multi-Agent Context Graph OS.
Routes tasks to SearchAgent and VerificationAgent based on the current Context Graph state.
"""
from typing import Literal
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI as ChatLiteLLM
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# The CRO Supervisor Prompt
CRO_SYSTEM_PROMPT = """You are the Chief Research Officer (CRO) of CortexAI.
Your job is to orchestrate a team of specialized agents to fulfill the user's research request.

You have access to the following worker agents:
- SearchAgent: Specialized in searching the web and scraping documents to populate the Context Graph.
- VerificationAgent: Specialized in cross-referencing claims and updating the Trust Engine scores.

Based on the current state of the research (and the user's request), decide who should act next.
If the research is complete, output "FINISH".
Otherwise, output the exact name of the agent to delegate to: "SearchAgent" or "VerificationAgent".

Do not output anything else except the agent name or FINISH.
"""

def get_cro_supervisor_agent():
    """Returns the LLM bound with the CRO routing logic."""
    
    llm = ChatLiteLLM(
        model=settings.ORCHESTRATOR_MODEL,
        temperature=0.1,  # Low temperature for deterministic routing
    )
    
    # We will use this in the LangGraph supervisor node
    return llm
