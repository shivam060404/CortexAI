"""FastAPI application factory — CORS, lifespan, router registration."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.core.logger import get_logger
from backend.auth.routes import router as auth_router
from backend.api.middleware import AuthMiddleware, SecurityHeadersMiddleware, RateLimitMiddleware, AuditMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
    app.add_middleware(AuthMiddleware)
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

    @app.get("/live")
    async def live():
        return {"status": "alive", "version": "2.0.0"}

    @app.get("/ready")
    async def ready():
        from sqlalchemy import text

        from backend.core.rate_limiter import rate_limiter
        from backend.core.session_store import session_store
        from backend.db.postgres import async_session

        checks = {
            "session_store": session_store.is_connected,
            "rate_limiter": getattr(rate_limiter, "_redis", None) is not None,
            "database": False,
        }

        try:
            async with async_session() as db:
                await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception as exc:
            logger.warning("readiness_database_check_failed", error=str(exc))

        if not all(checks.values()):
            raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})

        queue_depth = None
        autoscaling = None
        queue_metrics = None
        try:
            from backend.core.job_queue import job_queue

            if job_queue._redis is not None:
                queue_metrics = await job_queue.queue_metrics()
                queue_depth = queue_metrics["pending_depth"]
                autoscaling = {
                    "desired_replicas": queue_metrics["desired_replicas"],
                    "target_queue_depth_per_pod": queue_metrics["target_queue_depth_per_pod"],
                    "active_workers": queue_metrics["active_workers"],
                    "queue_depth_per_pod": queue_metrics["queue_depth_per_pod"],
                }
        except Exception as exc:
            logger.warning("readiness_queue_depth_check_failed", error=str(exc))

        return {
            "status": "ready",
            "checks": checks,
            "queue_depth": queue_depth,
            "queue_metrics": queue_metrics,
            "worker_autoscaling": autoscaling,
        }

    return app


# Module-level app instance for uvicorn
app = create_app()
