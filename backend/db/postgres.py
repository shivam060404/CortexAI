"""
PostgreSQL async models — SQLAlchemy 2.0 with asyncpg.
Includes TodoStatus state machine and AgentTrace for observability.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime, ForeignKey, Enum, JSON, func,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Session, relationship

from backend.config import settings
from backend.db.tenant import get_tenant_context


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------
RLS_DIRECT_USER_TABLES = {
    "research_sessions": "user_id",
    "user_memories": "user_id",
    "feedback_logs": "user_id",
    "user_preferences": "user_id",
    "audit_logs": "user_id",
}
RLS_SESSION_BOUND_TABLES = {
    "research_plans": "session_id",
    "research_results": "session_id",
    "todo_items": "session_id",
    "workspace_files": "session_id",
    "agent_traces": "session_id",
    "knowledge_nodes": "session_id",
    "knowledge_edges": "session_id",
    "experiment_tracks": "session_id",
}

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)


class TenantAwareSession(Session):
    """Sync session used under AsyncSession for tenant-aware transaction state."""


class TenantAwareAsyncSession(AsyncSession):
    """Async session that snapshots the current tenant context into session info."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("sync_session_class", TenantAwareSession)
        super().__init__(*args, **kwargs)
        self.sync_session.info["tenant_context"] = get_tenant_context()


async_session = async_sessionmaker(
    engine,
    class_=TenantAwareAsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# Import auth models only after Base exists to avoid circular imports.
from backend.auth.models import User  # noqa: E402,F401


def _build_rls_subject_expr(column_ref: str) -> str:
    same_org_expr = (
        "coalesce(tenant_subject.organization_id::text, tenant_subject.id::text) = "
        "nullif(current_setting('app.current_organization_id', true), '')"
    )
    same_user_expr = (
        "tenant_subject.id::text = nullif(current_setting('app.current_user_id', true), '')"
    )
    wide_role_expr = "current_setting('app.current_role', true) IN ('owner', 'admin', 'operator')"
    return (
        "current_setting('app.request_source', true) = 'system' "
        "OR current_setting('app.current_user_is_admin', true) = 'true' "
        "OR EXISTS ("
        "SELECT 1 FROM users tenant_subject "
        f"WHERE tenant_subject.id = {column_ref} "
        f"AND ({same_org_expr}) "
        f"AND ({wide_role_expr} OR {same_user_expr})"
        ")"
    )


def build_rls_sql() -> list[str]:
    """Return the Postgres statements required to enforce tenant RLS."""
    statements: list[str] = []

    for table_name, user_column in RLS_DIRECT_USER_TABLES.items():
        policy_name = f"{table_name}_tenant_isolation"
        predicate = _build_rls_subject_expr(user_column)
        statements.extend(
            [
                f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY",
                f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY",
                f"DROP POLICY IF EXISTS {policy_name} ON {table_name}",
                (
                    f"CREATE POLICY {policy_name} ON {table_name} "
                    f"USING ({predicate}) WITH CHECK ({predicate})"
                ),
            ]
        )

    for table_name, session_column in RLS_SESSION_BOUND_TABLES.items():
        policy_name = f"{table_name}_tenant_isolation"
        predicate = (
            "EXISTS ("
            "SELECT 1 FROM research_sessions rs "
            "JOIN users tenant_subject ON tenant_subject.id = rs.user_id "
            f"WHERE rs.id = {table_name}.{session_column} "
            "AND ("
            "current_setting('app.request_source', true) = 'system' "
            "OR current_setting('app.current_user_is_admin', true) = 'true' "
            "OR ("
            "coalesce(tenant_subject.organization_id::text, tenant_subject.id::text) = "
            "nullif(current_setting('app.current_organization_id', true), '') "
            "AND ("
            "current_setting('app.current_role', true) IN ('owner', 'admin', 'operator') "
            "OR tenant_subject.id::text = nullif(current_setting('app.current_user_id', true), '')"
            ")"
            ")"
            ")"
            ")"
        )
        statements.extend(
            [
                f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY",
                f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY",
                f"DROP POLICY IF EXISTS {policy_name} ON {table_name}",
                (
                    f"CREATE POLICY {policy_name} ON {table_name} "
                    f"USING ({predicate}) WITH CHECK ({predicate})"
                ),
            ]
        )

    return statements


def _apply_tenant_settings(session: Session, connection) -> None:
    """Push request tenant context into PostgreSQL transaction-local settings."""
    if connection.dialect.name != "postgresql":
        return

    tenant_context = session.info.get("tenant_context") or get_tenant_context()
    settings_to_apply = {
        "app.current_organization_id": tenant_context.organization_id or tenant_context.user_id or "",
        "app.current_user_id": tenant_context.user_id or "",
        "app.current_role": tenant_context.role or "viewer",
        "app.current_user_is_admin": "true" if tenant_context.is_admin else "false",
        "app.request_source": tenant_context.source or "anonymous",
    }
    for key, value in settings_to_apply.items():
        connection.execute(
            text("SELECT set_config(:setting_name, :setting_value, true)"),
            {"setting_name": key, "setting_value": value},
        )


@event.listens_for(TenantAwareSession, "after_begin")
def _set_transaction_tenant_context(session, transaction, connection):
    _apply_tenant_settings(session, connection)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SessionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TodoStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    user_request = Column(Text, nullable=False)
    status = Column(Enum(SessionStatus), default=SessionStatus.PENDING, nullable=False)
    final_report = Column(Text, default="")
    iterations_used = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    tool_calls_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    results = relationship("ResearchResult", back_populates="session", cascade="all, delete-orphan")
    todos = relationship("TodoItem", back_populates="session", cascade="all, delete-orphan",
                         order_by="TodoItem.order")
    plans = relationship("ResearchPlan", back_populates="session", cascade="all, delete-orphan",
                         order_by="ResearchPlan.version.desc()")
    files = relationship("WorkspaceFile", back_populates="session", cascade="all, delete-orphan")
    traces = relationship("AgentTrace", back_populates="session", cascade="all, delete-orphan",
                          order_by="AgentTrace.timestamp")


class ResearchResult(Base):
    __tablename__ = "research_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    source_url = Column(String(2000), default="")
    content = Column(Text, default="")
    relevance_score = Column(Float, default=0.0)
    agent_name = Column(String(100), default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("ResearchSession", back_populates="results")


class TodoItem(Base):
    """Task state machine: PENDING → IN_PROGRESS → COMPLETED | FAILED"""
    __tablename__ = "todo_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(Enum(TodoStatus), default=TodoStatus.PENDING, nullable=False)
    order = Column(Integer, default=0)
    error_message = Column(Text, default="")
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    session = relationship("ResearchSession", back_populates="todos")


class ResearchPlan(Base):
    __tablename__ = "research_plans"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_research_plans_session_version"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(50), nullable=False, default="draft")
    source = Column(String(50), nullable=False, default="tool")
    summary = Column(Text, default="")
    todos = Column(JSON, nullable=False, default=list)
    is_current = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    session = relationship("ResearchSession", back_populates="plans")


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    path = Column(String(1000), nullable=False)
    description = Column(Text, default="")
    size_bytes = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("ResearchSession", back_populates="files")


class AgentTrace(Base):
    """Structured trace log for observability — persisted per tool call."""
    __tablename__ = "agent_traces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)  # tool_call, agent_iteration, error, subagent_spawn
    tool_name = Column(String(100), default="")
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    latency_ms = Column(Float, default=0.0)
    tokens_used = Column(Integer, default=0)
    is_error = Column(Boolean, default=False)
    error_detail = Column(Text, default="")
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("ResearchSession", back_populates="traces")


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("session_id", "name", name="uq_knowledge_nodes_session_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=True)  # Nullable for global knowledge
    name = Column(String(500), nullable=False)
    node_type = Column(String(100), default="concept")  # concept, paper, entity, finding
    attributes = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False)
    relation = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExperimentTrack(Base):
    __tablename__ = "experiment_tracks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    hypothesis = Column(Text, nullable=False)
    approach = Column(Text, default="")
    result = Column(Text, default="")
    conclusion = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic = Column(String(200), nullable=False)
    relevance_score = Column(Integer, default=1)
    last_accessed = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FeedbackLog(Base):
    """RLHF feedback capture — user rates research output quality."""
    __tablename__ = "feedback_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 stars or thumbs -1/+1
    comment = Column(Text, default="")
    query = Column(Text, default="")
    research_mode = Column(String(50), default="deep")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserPreference(Base):
    """Learned preferences from RLHF feedback — adapts future research."""
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(100), nullable=False)  # e.g. "depth", "verbosity", "style"
    value = Column(String(500), nullable=False)
    confidence = Column(Float, default=0.5)  # How confident we are in this preference (0-1)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ---------------------------------------------------------------------------
# DB init helper
# ---------------------------------------------------------------------------
async def init_db():
    """Create all tables. Call on app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_id UUID")
            )
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'owner'")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_users_organization_id ON users (organization_id)")
            )
        if settings.TENANT_RLS_ENABLED and conn.dialect.name == "postgresql":
            for statement in build_rls_sql():
                await conn.execute(text(statement))
