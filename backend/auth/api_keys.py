"""Helpers for generating and validating API keys."""

from __future__ import annotations

import hashlib
import secrets

API_KEY_PREFIX = "ctx_"


def hash_api_key(api_key: str) -> str:
    """Return a stable SHA-256 digest for an API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key_pair() -> tuple[str, str]:
    """Generate a displayable API key and the digest to persist."""
    raw_key = f"{API_KEY_PREFIX}{secrets.token_hex(24)}"
    return raw_key, hash_api_key(raw_key)


def api_key_matches(raw_api_key: str, stored_value: str | None) -> bool:
    """Validate an API key against either a hashed or legacy plaintext value."""
    if not raw_api_key or not stored_value:
        return False
    return secrets.compare_digest(stored_value, raw_api_key) or secrets.compare_digest(
        stored_value,
        hash_api_key(raw_api_key),
    )
