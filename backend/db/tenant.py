"""Tenant context helpers for request-scoped database isolation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Generator


@dataclass(frozen=True)
class TenantContext:
    """Identity propagated into database sessions for RLS enforcement."""

    organization_id: str | None = None
    user_id: str | None = None
    role: str = "viewer"
    is_admin: bool = False
    source: str = "anonymous"


_tenant_context: ContextVar[TenantContext] = ContextVar(
    "tenant_context",
    default=TenantContext(),
)


def get_tenant_context() -> TenantContext:
    """Return the active request-scoped tenant context."""
    return _tenant_context.get()


def bind_tenant_context(
    organization_id: str | None = None,
    user_id: str | None = None,
    *,
    role: str = "viewer",
    is_admin: bool = False,
    source: str = "anonymous",
) -> Token:
    """Bind tenant context for the current task and return the reset token."""
    return _tenant_context.set(
        TenantContext(
            organization_id=str(organization_id) if organization_id else None,
            user_id=str(user_id) if user_id else None,
            role=str(role or "viewer"),
            is_admin=bool(is_admin),
            source=source,
        )
    )


def tenant_context_from_user(user: Any, *, source: str) -> TenantContext:
    """Normalize an authenticated user object into a tenant context."""
    user_id = getattr(user, "id", None)
    organization_id = getattr(user, "organization_id", None) or user_id
    is_admin = bool(getattr(user, "is_admin", False))
    role = "admin" if is_admin else str(getattr(user, "role", "owner") or "owner")
    return TenantContext(
        organization_id=str(organization_id) if organization_id else None,
        user_id=str(user_id) if user_id else None,
        role=role,
        is_admin=is_admin,
        source=source,
    )


def bind_user_tenant_context(user: Any, *, source: str) -> Token:
    """Bind tenant context directly from an authenticated user object."""
    context = tenant_context_from_user(user, source=source)
    return _tenant_context.set(context)


def reset_tenant_context(token: Token) -> None:
    """Reset tenant context using a token returned by `bind_tenant_context()`."""
    _tenant_context.reset(token)


@contextmanager
def tenant_context(
    organization_id: str | None = None,
    user_id: str | None = None,
    *,
    role: str = "viewer",
    is_admin: bool = False,
    source: str = "anonymous",
) -> Generator[TenantContext, None, None]:
    """Temporarily bind tenant context within a code block."""
    token = bind_tenant_context(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        is_admin=is_admin,
        source=source,
    )
    try:
        yield get_tenant_context()
    finally:
        reset_tenant_context(token)
