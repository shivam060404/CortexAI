"""
Organization & Multi-Tenant Model (Feature Gap #1).

Provides Organization and OrganizationMember SQLAlchemy models,
plus helpers for org-scoped queries and membership management.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, func, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.db.postgres import Base


class OrganizationRole:
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    ALL_ROLES = {OWNER, ADMIN, MEMBER, VIEWER}


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan_type = Column(String(50), default="free")  # free, pro, enterprise
    billing_email = Column(String(255), nullable=True)
    member_count = Column(Integer, default=1)
    max_members = Column(Integer, default=5)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), default=OrganizationRole.MEMBER, nullable=False)
    invited_by = Column(UUID(as_uuid=True), nullable=True)
    joined_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    organization = relationship("Organization", back_populates="members")

    class Config:
        unique_together = [("organization_id", "user_id")]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

async def create_organization(name: str, owner_user_id: str, plan_type: str = "free") -> dict:
    """Create a new organization and add the user as owner."""
    from backend.db.postgres import async_session

    slug = _slugify(name)

    async with async_session() as db:
        org = Organization(
            name=name,
            slug=slug,
            plan_type=plan_type,
            member_count=1,
        )
        db.add(org)
        await db.flush()

        membership = OrganizationMember(
            organization_id=org.id,
            user_id=uuid.UUID(owner_user_id),
            role=OrganizationRole.OWNER,
        )
        db.add(membership)

        # Link user to org
        from backend.auth.models import User
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(User).where(User.id == uuid.UUID(owner_user_id)).values(organization_id=org.id, role="owner")
        )

        await db.commit()
        await db.refresh(org)

        return {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "plan_type": org.plan_type,
            "member_count": org.member_count,
            "created_at": org.created_at.isoformat() if org.created_at else None,
        }


async def get_user_organizations(user_id: str) -> list[dict]:
    """List all organizations a user belongs to."""
    from backend.db.postgres import async_session
    from sqlalchemy import select

    user_uuid = uuid.UUID(user_id)
    async with async_session() as db:
        result = await db.execute(
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_uuid)
        )
        orgs = []
        for org, role in result.all():
            orgs.append({
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "plan_type": org.plan_type,
                "member_count": org.member_count,
                "role": role,
                "created_at": org.created_at.isoformat() if org.created_at else None,
            })
        return orgs


async def add_member(org_id: str, user_id: str, role: str = "member", invited_by: str | None = None) -> dict:
    """Add a user to an organization."""
    from backend.db.postgres import async_session
    from backend.auth.models import User
    from sqlalchemy import update as sa_update

    if role not in OrganizationRole.ALL_ROLES:
        raise ValueError(f"Invalid role: {role}")

    async with async_session() as db:
        membership = OrganizationMember(
            organization_id=uuid.UUID(org_id),
            user_id=uuid.UUID(user_id),
            role=role,
            invited_by=uuid.UUID(invited_by) if invited_by else None,
        )
        db.add(membership)

        # Link user to org
        await db.execute(
            sa_update(User).where(User.id == uuid.UUID(user_id)).values(organization_id=uuid.UUID(org_id), role=role)
        )

        # Update member count
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(Organization)
            .where(Organization.id == uuid.UUID(org_id))
            .values(member_count=Organization.member_count + 1)
        )

        await db.commit()
        return {"organization_id": org_id, "user_id": user_id, "role": role}


async def list_members(org_id: str) -> list[dict]:
    """List all members of an organization."""
    from backend.db.postgres import async_session
    from backend.auth.models import User
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(OrganizationMember, User.email, User.full_name)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == uuid.UUID(org_id))
        )
        members = []
        for membership, email, full_name in result.all():
            members.append({
                "user_id": str(membership.user_id),
                "email": email,
                "full_name": full_name,
                "role": membership.role,
                "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
            })
        return members


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from an organization name."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:100] or f"org-{uuid.uuid4().hex[:6]}"
