from backend.db.postgres import _apply_tenant_settings, build_rls_sql
from backend.db.tenant import (
    bind_tenant_context,
    bind_user_tenant_context,
    get_tenant_context,
    reset_tenant_context,
    tenant_context_from_user,
)


class _FakeSession:
    def __init__(self, info=None):
        self.info = info or {}


class _FakeDialect:
    name = "postgresql"


class _FakeConnection:
    def __init__(self, dialect_name="postgresql"):
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))


def test_tenant_context_round_trip():
    token = bind_tenant_context(
        organization_id="org-123",
        user_id="tenant-123",
        role="admin",
        is_admin=True,
        source="request",
    )
    try:
        context = get_tenant_context()
        assert context.organization_id == "org-123"
        assert context.user_id == "tenant-123"
        assert context.role == "admin"
        assert context.is_admin is True
        assert context.source == "request"
    finally:
        reset_tenant_context(token)

    reset_context = get_tenant_context()
    assert reset_context.organization_id is None
    assert reset_context.user_id is None
    assert reset_context.role == "viewer"
    assert reset_context.is_admin is False
    assert reset_context.source == "anonymous"


def test_tenant_context_from_user_defaults_org_and_normalizes_admin_role():
    user = type(
        "User",
        (),
        {
            "id": "user-789",
            "organization_id": None,
            "role": "analyst",
            "is_admin": True,
        },
    )()

    context = tenant_context_from_user(user, source="request")

    assert context.organization_id == "user-789"
    assert context.user_id == "user-789"
    assert context.role == "admin"
    assert context.is_admin is True
    assert context.source == "request"


def test_bind_user_tenant_context_uses_user_fields():
    user = type(
        "User",
        (),
        {
            "id": "user-111",
            "organization_id": "org-111",
            "role": "operator",
            "is_admin": False,
        },
    )()

    token = bind_user_tenant_context(user, source="websocket")
    try:
        context = get_tenant_context()
        assert context.organization_id == "org-111"
        assert context.user_id == "user-111"
        assert context.role == "operator"
        assert context.is_admin is False
        assert context.source == "websocket"
    finally:
        reset_tenant_context(token)


def test_apply_tenant_settings_uses_bound_context():
    token = bind_tenant_context(
        organization_id="org-456",
        user_id="tenant-456",
        role="analyst",
        is_admin=False,
        source="websocket",
    )
    try:
        connection = _FakeConnection()
        _apply_tenant_settings(_FakeSession(), connection)
    finally:
        reset_tenant_context(token)

    assert len(connection.calls) == 5
    assert connection.calls[0][1] == {
        "setting_name": "app.current_organization_id",
        "setting_value": "org-456",
    }
    assert connection.calls[1][1] == {
        "setting_name": "app.current_user_id",
        "setting_value": "tenant-456",
    }
    assert connection.calls[2][1] == {
        "setting_name": "app.current_role",
        "setting_value": "analyst",
    }
    assert connection.calls[3][1] == {
        "setting_name": "app.current_user_is_admin",
        "setting_value": "false",
    }
    assert connection.calls[4][1] == {
        "setting_name": "app.request_source",
        "setting_value": "websocket",
    }


def test_apply_tenant_settings_skips_non_postgres_connections():
    connection = _FakeConnection(dialect_name="sqlite")
    _apply_tenant_settings(_FakeSession(), connection)
    assert connection.calls == []


def test_rls_sql_covers_direct_and_session_bound_tables():
    statements = build_rls_sql()
    joined_sql = "\n".join(statements)

    assert "ALTER TABLE research_sessions ENABLE ROW LEVEL SECURITY" in joined_sql
    assert "ALTER TABLE research_sessions FORCE ROW LEVEL SECURITY" in joined_sql
    assert "CREATE POLICY research_sessions_tenant_isolation ON research_sessions" in joined_sql
    assert "current_setting('app.current_organization_id', true)" in joined_sql
    assert "current_setting('app.current_role', true) IN ('owner', 'admin', 'operator')" in joined_sql
    assert "coalesce(tenant_subject.organization_id::text, tenant_subject.id::text)" in joined_sql

    assert "ALTER TABLE knowledge_nodes ENABLE ROW LEVEL SECURITY" in joined_sql
    assert "ALTER TABLE knowledge_nodes FORCE ROW LEVEL SECURITY" in joined_sql
    assert "CREATE POLICY knowledge_nodes_tenant_isolation ON knowledge_nodes" in joined_sql
    assert "WHERE rs.id = knowledge_nodes.session_id" in joined_sql
    assert "JOIN users tenant_subject ON tenant_subject.id = rs.user_id" in joined_sql
    assert "current_setting('app.request_source', true) = 'system'" in joined_sql
