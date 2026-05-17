"""
CortexAI Settings — centralized configuration with Pydantic BaseSettings.
All values are overridable via environment variables or .env file.
"""

import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application-wide settings loaded from environment / .env."""

    # --- LLM Provider ---
    MISTRAL_API_KEY: str = ""
    LLM_MODEL: str = "mistral-large-latest"
    LLM_TEMPERATURE: float = 0.0

    # --- Search ---
    TAVILY_API_KEY: str = ""

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cortexai"

    # --- ChromaDB ---
    CHROMA_PERSIST_DIR: str = "./data/chromadb"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_SEARCH_TTL: int = 3600        # 1 hour
    CACHE_EMBEDDING_TTL: int = 86400    # 24 hours

    # --- Workspace (Local FS) ---
    WORKSPACE_ROOT: str = "./data/workspaces"

    # --- Execution Control ---
    MAX_ITERATIONS: int = 20
    MAX_TOKENS_PER_SESSION: int = 50_000
    AGENT_TIMEOUT_SECONDS: int = 120

    # --- Sub-agent Limits ---
    SUBAGENT_MAX_TOKENS: int = 10_000
    SUBAGENT_MAX_STEPS: int = 10
    SUBAGENT_TIMEOUT: int = 60

    # --- Tool Permissions ---
    ALLOWED_TOOLS: List[str] = Field(default=[
        # Search tools
        "web_search", "academic_search", "news_search",
        # Filesystem tools
        "read_file", "write_file", "edit_file", "list_files", "grep_files",
        # Planning tools
        "write_todos", "get_todos",
        # Sub-agent tools
        "spawn_subagent", "spawn_parallel_subagents",
        # Research loop tools
        "generate_hypothesis", "evaluate_findings",
        # Knowledge graph tools
        "add_to_knowledge_graph", "query_knowledge_graph",
        # Experiment tracking tools
        "log_experiment",
        # Reflection tools
        "self_reflect", "cross_reference_sources",
        # Advanced Features
        "execute_python_script", "run_debate", "generate_presentation"
    ])

    # --- CORS ---
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # --- Retry / Resilience ---
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 2.0
    CIRCUIT_BREAKER_THRESHOLD: int = 5

    # --- Intelligence Guardrails & Cost Tracking ---
    GUARD_MAX_USD: float = 1.00  # Default budget $1 per session
    # Mistral pricing approx (in $ per 1 Million tokens)
    COST_PER_1M_INPUT_TOKENS: float = 2.0  
    COST_PER_1M_OUTPUT_TOKENS: float = 6.0 
    COST_PER_SEARCH_API: float = 0.005 # e.g. Tavily per query

    GUARD_ENABLE_PII_REDACTION: bool = True
    GUARD_ENABLE_INJECTION_SHIELD: bool = True
    GUARD_ENABLE_OUTPUT_MODERATION: bool = True
    GUARD_SCOPE_DRIFT_THRESHOLD: int = 5 # Check every 5 iterations

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
