"""
FastAPI application factory — CORS, lifespan, router registration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    logger.info("app_startup", cors_origins=settings.CORS_ORIGINS)

    # Create workspace and ChromaDB data dirs
    import os
    os.makedirs(settings.WORKSPACE_ROOT, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)

    # Try to initialize PostgreSQL tables (graceful if DB not available)
    try:
        from backend.db.postgres import init_db
        await init_db()
        logger.info("postgres_initialized")

        # Hydrate in-memory session cache from DB
        from backend.api.routes import hydrate_sessions_from_db
        await hydrate_sessions_from_db()
        
        # Start background job scheduler
        from backend.core.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning("postgres_init_skipped", error=str(e),
                        note="Running with in-memory storage. PostgreSQL optional.")

    yield

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CortexAI — Advanced Deep Researcher Agent Platform",
        description="Autonomous research agent with dynamic planning, filesystem workspace, sub-agents, and real-time streaming.",
        version="2.0.0",
        lifespan=lifespan,
    )

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

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "2.0.0"}

    return app


# Module-level app instance for uvicorn
app = create_app()
