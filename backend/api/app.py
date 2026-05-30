"""
FastAPI application factory — CORS, lifespan, router registration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.core.logger import get_logger
from backend.api.routes import router
from backend.auth.routes import router as auth_router
from backend.api.middleware import SecurityHeadersMiddleware, RateLimitMiddleware, AuditMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    logger.info("app_startup", cors_origins=settings.CORS_ORIGINS)

    # Create workspace and LanceDB data dirs
    import os
    os.makedirs(settings.WORKSPACE_ROOT, exist_ok=True)
    os.makedirs(settings.LANCEDB_PERSIST_DIR, exist_ok=True)

    # Initialize session store and rate limiter
    from backend.core.session_store import session_store
    from backend.core.rate_limiter import rate_limiter
    await session_store.connect()
    await rate_limiter.connect()

    # Try to initialize PostgreSQL tables (graceful if DB not available)
    try:
        from backend.db.postgres import init_db
        await init_db()
        logger.info("postgres_initialized")
        
        # Start background job scheduler
        from backend.core.scheduler import start_scheduler
        start_scheduler()
        
        # Start MCP servers
        if settings.MCP_ENABLED:
            from backend.mcp.global_registry import mcp_registry
            await mcp_registry.load_config()
            await mcp_registry.start_all()
    except Exception as e:
        logger.warning("postgres_init_skipped", error=str(e),
                        note="Running with in-memory storage. PostgreSQL optional.")

    yield

    if settings.MCP_ENABLED:
        from backend.mcp.global_registry import mcp_registry
        await mcp_registry.shutdown_all()

    # Close session store and rate limiter
    from backend.core.session_store import session_store
    from backend.core.rate_limiter import rate_limiter
    await session_store.close()
    await rate_limiter.close()

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CortexAI — Advanced Deep Researcher Agent Platform",
        description="Autonomous research agent with dynamic planning, filesystem workspace, sub-agents, and real-time streaming.",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Security & rate limiting middleware (order matters: last added = first executed)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    # Setup Arize Phoenix Observability
    try:
        import phoenix as px
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from openinference.instrumentation.litellm import LiteLLMInstrumentor
        from opentelemetry import trace as trace_api
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk import trace as trace_sdk
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        # Launch Phoenix local server (runs on port 6006 by default)
        px.launch_app()
        
        # Connect OTEL to Phoenix
        endpoint = "http://127.0.0.1:6006/v1/traces"
        tracer_provider = trace_sdk.TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))
        trace_api.set_tracer_provider(tracer_provider)
        
        # Instrument LLM libraries
        LangChainInstrumentor().instrument()
        LiteLLMInstrumentor().instrument()
        logger.info("phoenix_observability_enabled")
    except ImportError as e:
        logger.warning("phoenix_not_installed", error=str(e))
    except Exception as e:
        logger.error("phoenix_setup_failed", error=str(e))

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    from backend.api.routes import router
    app.include_router(router)
    app.include_router(auth_router)

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "2.0.0"}

    return app


# Module-level app instance for uvicorn
app = create_app()
