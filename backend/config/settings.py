"""
CortexAI Settings — centralized configuration with Pydantic BaseSettings.
All values are overridable via environment variables or .env file.
"""

from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application-wide settings loaded from environment / .env."""

    # --- LLM Provider ---
    MISTRAL_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    
    # Legacy fallbacks
    LLM_MODEL: str = "mistral-large-latest"
    LLM_TEMPERATURE: float = 0.0

    # Tiered Routing
    ORCHESTRATOR_MODEL: str = "mistral/mistral-large-latest"
    FAST_MODEL: str = "groq/llama3-8b-8192"

    # --- Search ---
    TAVILY_API_KEY: str = ""
    EXA_API_KEY: str = ""
    FIRECRAWL_API_KEY: str = ""
    SEARCH_MAX_PARALLEL_QUERIES: int = 20
    SEARCH_PROVIDERS: List[str] = Field(default=["tavily", "exa", "firecrawl"])

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:changeme@localhost:5432/cortexai"
    POSTGRES_PASSWORD: str = "changeme"
    TENANT_RLS_ENABLED: bool = True

    # --- LanceDB ---
    LANCEDB_PERSIST_DIR: str = "./data/lancedb"

    # --- Redis ---
    REDIS_URL: str = "redis://:changeme@localhost:6379/0"
    REDIS_PASSWORD: str = "changeme"
    CACHE_SEARCH_TTL: int = 3600        # 1 hour
    CACHE_EMBEDDING_TTL: int = 86400    # 24 hours
    WORKER_QUEUE_NAME: str = "cortex:jobs:research"
    WORKER_POLL_TIMEOUT_SECONDS: int = 5
    WORKER_READINESS_FILE: str = "./data/worker.ready"
    WORKER_HEARTBEAT_FILE: str = "./data/worker.heartbeat"
    WORKER_LEASE_SECONDS: int = 120
    WORKER_LEASE_RENEW_INTERVAL_SECONDS: int = 30
    WORKER_HEARTBEAT_TTL_SECONDS: int = 90
    WORKER_METRICS_HOST: str = "0.0.0.0"
    WORKER_METRICS_PORT: int = 9102
    WORKER_MIN_REPLICAS: int = 2
    WORKER_MAX_REPLICAS: int = 12
    WORKER_TARGET_CPU_UTILIZATION_PCT: int = 70
    WORKER_TARGET_QUEUE_DEPTH_PER_POD: int = 10

    # --- Workspace (Local FS) ---
    WORKSPACE_ROOT: str = "./data/workspaces"

    # --- MCP Protocol ---
    MCP_ENABLED: bool = True
    MCP_SERVERS_CONFIG: str = "./mcp_servers.json"

    # --- Browser Agent ---
    BROWSER_HEADLESS: bool = True
    BROWSER_PROXY_POOL: List[str] = Field(default_factory=list)
    BROWSER_CREDENTIAL_KEY: str = ""

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
        "extract_and_store_knowledge", "query_community_knowledge",
        # Experiment tracking tools
        "log_experiment",
        # Reflection tools
        "self_reflect", "cross_reference_sources",
        # Advanced Features
        "execute_code_agent_task", "run_debate", "generate_presentation"
    ])

    # --- Authentication ---
    JWT_SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- OAuth2 ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # --- CORS ---
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: [
        "http://localhost:5173",
        "http://localhost:3000",
    ])

    # --- Retry / Resilience ---
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 2.0
    CIRCUIT_BREAKER_THRESHOLD: int = 5

    # --- Production Hardening ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    
    # --- Intelligence Guardrails & Cost Tracking ---
    GUARD_MAX_USD: float = 10.00  # Default budget $10 per session
    # Mistral pricing approx (in $ per 1 Million tokens)
    COST_PER_1M_INPUT_TOKENS: float = 2.0  
    COST_PER_1M_OUTPUT_TOKENS: float = 6.0 
    COST_PER_SEARCH_API: float = 0.005 # e.g. Tavily per query

    GUARD_ENABLE_PII_REDACTION: bool = True
    GUARD_ENABLE_INJECTION_SHIELD: bool = True
    GUARD_ENABLE_OUTPUT_MODERATION: bool = True
    GUARD_SCOPE_DRIFT_THRESHOLD: int = 5 # Check every 5 iterations

    # --- WebSocket Heartbeat (Arch Issue #8) ---
    WS_HEARTBEAT_INTERVAL: int = 30        # seconds between pings
    WS_HEARTBEAT_TIMEOUT: int = 90         # close after this many seconds of no pong

    # --- Request Body Limit (Security #4) ---
    MAX_REQUEST_BODY_SIZE: int = 10 * 1024 * 1024  # 10 MB

    # --- HITL Configurable Timeout (Security #6) ---
    HITL_TIMEOUT_SECONDS: int = 300
    HITL_MAX_TIMEOUT_SECONDS: int = 600    # DoS prevention cap

    # --- Graph Cache (Arch Issue #4) ---
    GRAPH_CACHE_MAX_SIZE: int = 50
    GRAPH_CACHE_TTL_SECONDS: int = 3600    # 1 hour

    # --- Dynamic Supervisor Temperature (Arch Issue #2) ---
    SUPERVISOR_ROUTING_TEMP: float = 0.1
    SUPERVISOR_PLANNING_TEMP: float = 0.3
    SUPERVISOR_CREATIVE_TEMP: float = 0.4

    # --- Multi-Model Fallback (Arch Issue #7) ---
    FALLBACK_MODELS: List[str] = Field(default_factory=lambda: [
        "groq/llama3-70b-8192",
    ])

    # --- Sandbox (Arch Issue #3) ---
    SANDBOX_MEMORY_LIMIT_MB: int = 256
    SANDBOX_TIMEOUT: int = 30              # seconds
    TOOL_EXECUTION_TIMEOUT: int = 60       # seconds
    TOOL_MAX_OUTPUT_SIZE: int = 100_000    # chars

    # --- Graph Backend (Arch Issue #1) ---
    GRAPH_BACKEND: str = "memory"          # memory | redis

    # --- Trust Engine (Arch Issue #6) ---
    TRUST_ENGINE_MODE: str = "heuristic"   # heuristic | ml

    # --- Supervisor Loop Detection (Pillar 5) ---
    SUPERVISOR_LOOP_THRESHOLD: int = 3

    # --- Content Policy (Pillar 4) ---
    CONTENT_POLICY_MODE: str = "auto"      # auto | supervised | locked

    # --- SOC2 Compliance (Feature Gap #12) ---
    AUDIT_RETENTION_DAYS: int = 365
    SOC2_MODE: bool = False

    # --- Organization (Feature Gap #1) ---
    ORGANIZATION_ENABLED: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
