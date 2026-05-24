"""
Multi-Agent Debate Engine — Spawns specialized LLMs to vigorously debate a topic
before returning a synthesized transcript to the main orchestrator agent.
All calls are fully async to prevent blocking the FastAPI event loop.
"""

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_community.chat_models import ChatLiteLLM
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Core Prompts for the Debaters
PRO_PROMPT = """You are the DEFENDER in a strict debate. 
Your objective is to vigorously support and prove the provided hypothesis or topic. 
You must marshal facts, ignore distractions, and strictly argue FOR the topic. 
Always remain analytical, professional, but relentless in your defense.
Address the claims made by the skeptic and dismantle them.
"""

CON_PROMPT = """You are the SKEPTIC in a strict debate.
Your objective is to vigorously attack and debunk the provided hypothesis or topic. 
You must marshal facts, highlight logical fallacies, demand evidence, and strictly argue AGAINST the topic. 
Always remain analytical, professional, but relentless in your attack.
Address the claims made by the defender and dismantle them.
"""

def get_debate_tools(session_id: str) -> list:
    """Return debate tools bound to a specific session workspace."""

    @tool
    async def run_debate(topic: str, rounds: int = 3) -> str:
        """
        Run a rigorously structured multi-agent debate on a specific complex topic.
        This spawns two distinct sub-agents: a Defender who aggressively proves the topic,
        and a Skeptic who aggressively debunks the topic.
        They will debate for the specified number of rounds (default 3).
        Returns the full verbatim transcript of the debate. Use this tool when you need
        multiple perspectives to eliminate bias before finalizing a conclusion.
        """
        if rounds > 5:
            rounds = 5  # Hard cap to prevent excessive token burn
            
        logger.info("debate_started", session_id=session_id, topic=topic[:80])
        
        # Initialize isolated models for the debate
        pro_agent = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.7, # Higher temp for more creative argumentation
        )
        
        con_agent = ChatLiteLLM(
            model=settings.FAST_MODEL,
            temperature=0.7,
        )
        
        # State tracking for the debate
        pro_history = [SystemMessage(content=PRO_PROMPT)]
        con_history = [SystemMessage(content=CON_PROMPT)]
        
        transcript = []
        transcript.append(f"### ⚔️ DEBATE INITIATED: {topic}\n")
        
        # Round 1: Opening Statement by Pro (async)
        try:
            pro_history.append(HumanMessage(content=f"Debate Topic: {topic}. Please provide your opening statement defending this."))
            pro_response = await pro_agent.ainvoke(pro_history)
            pro_history.append(AIMessage(content=pro_response.content))
            transcript.append(f"**🟢 DEFENDER (Opening):**\n{pro_response.content}\n")
            last_argument = pro_response.content
        except Exception as e:
            logger.error("debate_pro_opening_failed", error=str(e))
            return f"Debate failed during opening statement: {e}"
        
        # Alternate turns (all async)
        for i in range(rounds):
            # Con turn
            try:
                con_message = f"The Defender stated:\n\n{last_argument}\n\nProvide your rebuttal and counter-arguments."
                con_history.append(HumanMessage(content=con_message))
                con_response = await con_agent.ainvoke(con_history)
                con_history.append(AIMessage(content=con_response.content))
                transcript.append(f"**🔴 SKEPTIC (Round {i+1}):**\n{con_response.content}\n")
                last_argument = con_response.content
            except Exception as e:
                logger.error("debate_con_round_failed", round=i+1, error=str(e))
                transcript.append(f"**🔴 SKEPTIC (Round {i+1}):** [API failure — round skipped: {e}]\n")
                break
            
            # Skip Pro response on the very last turn so Con gets the final word
            if i < rounds - 1:
                try:
                    pro_message = f"The Skeptic rebutted with:\n\n{last_argument}\n\nProvide your defense and counter-arguments."
                    pro_history.append(HumanMessage(content=pro_message))
                    pro_response = await pro_agent.ainvoke(pro_history)
                    pro_history.append(AIMessage(content=pro_response.content))
                    transcript.append(f"**🟢 DEFENDER (Round {i+1}):**\n{pro_response.content}\n")
                    last_argument = pro_response.content
                except Exception as e:
                    logger.error("debate_pro_round_failed", round=i+1, error=str(e))
                    transcript.append(f"**🟢 DEFENDER (Round {i+1}):** [API failure — round skipped: {e}]\n")
                    break

        transcript.append(f"\n### 🏁 DEBATE CONCLUDED")
        final_log = "\n".join(transcript)
        
        logger.info("debate_concluded", session_id=session_id)
        return final_log

    return [run_debate]
