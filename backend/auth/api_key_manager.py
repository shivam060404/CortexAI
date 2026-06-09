"""
API Key Management — multi-key support with scopes, rotation, and tracking (Feature Gap #2).
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, update as sa_update, delete as sa_delete
from backend.db.postgres import async_session, APIKey
from backend.auth.api_keys import generate_api_key_pair, hash_api_key, api_key_matches
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Default key expiry: 90 days
DEFAULT_KEY_EXPIRY_DAYS = 90
# Grace period for key rotation: 24 hours
ROTATION_GRACE_PERIOD_HOURS = 24


async def create_api_key(
    user_id: str,
    name: str = "default",
    scopes: list[str] | None = None,
    rate_limit: int = 60,
    expires_days: int | None = DEFAULT_KEY_EXPIRY_DAYS,
) -> dict:
    """Create a new API key for a user.

    Returns the raw key (only shown once) and the stored metadata.
    """
    raw_key, stored_hash = generate_api_key_pair()
    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    async with async_session() as db:
        key_record = APIKey(
            user_id=uuid.UUID(user_id),
            name=name,
            key_hash=stored_hash,
            scopes=scopes or ["research:read", "research:write"],
            rate_limit=rate_limit,
            expires_at=expires_at,
        )
        db.add(key_record)
        await db.commit()
        await db.refresh(key_record)

    logger.info("api_key_created", user_id=user_id, name=name)
    return {
        "id": str(key_record.id),
        "name": name,
        "api_key": raw_key,  # Only returned once
        "scopes": key_record.scopes,
        "rate_limit": rate_limit,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": key_record.created_at.isoformat() if key_record.created_at else None,
    }


async def list_api_keys(user_id: str) -> list[dict]:
    """List all API keys for a user (without revealing the raw key)."""
    async with async_session() as db:
        result = await db.execute(
            select(APIKey)
            .where(APIKey.user_id == uuid.UUID(user_id))
            .order_by(APIKey.created_at.desc())
        )
        keys = result.scalars().all()
        return [
            {
                "id": str(k.id),
                "name": k.name,
                "scopes": k.scopes or [],
                "rate_limit": k.rate_limit,
                "is_active": k.is_active,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ]


async def revoke_api_key(user_id: str, key_id: str) -> dict:
    """Deactivate an API key."""
    async with async_session() as db:
        await db.execute(
            sa_update(APIKey)
            .where(APIKey.id == uuid.UUID(key_id), APIKey.user_id == uuid.UUID(user_id))
            .values(is_active=False)
        )
        await db.commit()
    logger.info("api_key_revoked", user_id=user_id, key_id=key_id)
    return {"id": key_id, "status": "revoked"}


async def delete_api_key(user_id: str, key_id: str) -> dict:
    """Permanently delete an API key."""
    async with async_session() as db:
        await db.execute(
            sa_delete(APIKey)
            .where(APIKey.id == uuid.UUID(key_id), APIKey.user_id == uuid.UUID(user_id))
        )
        await db.commit()
    logger.info("api_key_deleted", user_id=user_id, key_id=key_id)
    return {"id": key_id, "status": "deleted"}


async def rotate_api_key(user_id: str, key_id: str) -> dict:
    """Rotate an API key: create a new one, mark old for expiry after grace period."""
    # Get old key info
    async with async_session() as db:
        result = await db.execute(
            select(APIKey).where(APIKey.id == uuid.UUID(key_id), APIKey.user_id == uuid.UUID(user_id))
        )
        old_key = result.scalar_one_or_none()
        if not old_key:
            raise ValueError("API key not found")

        # Set old key to expire after grace period
        grace_expiry = datetime.now(timezone.utc) + timedelta(hours=ROTATION_GRACE_PERIOD_HOURS)
        await db.execute(
            sa_update(APIKey)
            .where(APIKey.id == uuid.UUID(key_id))
            .values(expires_at=grace_expiry)
        )
        await db.commit()

    # Create replacement key with same settings
    new_key = await create_api_key(
        user_id=user_id,
        name=f"{old_key.name}-rotated",
        scopes=old_key.scopes,
        rate_limit=old_key.rate_limit,
    )

    logger.info("api_key_rotated", user_id=user_id, old_key_id=key_id, new_key_id=new_key["id"])
    return {
        "old_key_id": key_id,
        "old_key_expires_at": grace_expiry.isoformat(),
        "new_key": new_key,
    }


async def validate_api_key(raw_key: str) -> Optional[dict]:
    """Validate an API key and return the associated user info.

    Checks: hash match, active status, expiry.
    Updates last_used_at on success.
    """
    key_hash = hash_api_key(raw_key)
    async with async_session() as db:
        result = await db.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        key_record = result.scalar_one_or_none()

        if not key_record:
            return None
        if not key_record.is_active:
            return None
        if key_record.expires_at and key_record.expires_at < datetime.now(timezone.utc):
            return None

        # Update last used
        await db.execute(
            sa_update(APIKey)
            .where(APIKey.id == key_record.id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await db.commit()

        return {
            "user_id": str(key_record.user_id),
            "key_id": str(key_record.id),
            "scopes": key_record.scopes or [],
            "rate_limit": key_record.rate_limit,
        }
