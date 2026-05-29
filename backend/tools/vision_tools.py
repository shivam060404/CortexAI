"""
Vision LLM Tools for multimodal analysis.
Uses Groq Llama-3.2-Vision to analyze images dropped by the user.
"""

from langchain_core.tools import tool
from backend.core.logger import get_logger
import os
import requests
import json

logger = get_logger(__name__)

@tool("analyze_image")
def analyze_image(base64_image: str, prompt: str) -> str:
    """Analyzes an image using Groq Llama-3.2-Vision.
    Args:
        base64_image: The image encoded as a base64 string (including data URI prefix).
        prompt: What to look for or analyze in the image.
    """
    logger.info("analyze_image_called")
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return "Error: GROQ_API_KEY is not set."

    # Remove data URI prefix if present
    if "," in base64_image:
        base64_image = base64_image.split(",")[1]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.2-90b-vision-preview",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.5,
        "max_tokens": 1024
    }

    try:
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("vision_analysis_failed", error=str(e))
        return f"Failed to analyze image: {str(e)}"

def get_vision_tools():
    """Return the list of vision tools."""
    return [analyze_image]
