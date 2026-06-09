"""
Secrets Manager — unified secret retrieval with pluggable backends.

Supports:
  - HashiCorp Vault (via hvac)
  - AWS Secrets Manager (via boto3)
  - Local .env file (default fallback)

Configuration via settings:
  SECRETS_BACKEND=env | vault | aws
  VAULT_ADDR, VAULT_TOKEN, VAULT_SECRET_PATH
  AWS_REGION, AWS_SECRET_NAME
"""

from __future__ import annotations

import os
from typing import Any, Optional

from backend.core.logger import get_logger

logger = get_logger(__name__)


class SecretsManager:
    """Unified secrets manager with pluggable backends.

    Usage:
        manager = SecretsManager()
        await manager.initialize()
        api_key = await manager.get_secret("MISTRAL_API_KEY")
    """

    def __init__(self):
        self._backend: str = "env"
        self._vault_client: Any = None
        self._aws_client: Any = None
        self._cache: dict[str, str] = {}
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Initialize the secrets backend based on configuration."""
        if self._initialized:
            return

        from backend.config import settings

        self._backend = getattr(settings, "SECRETS_BACKEND", "env")

        if self._backend == "vault":
            await self._init_vault(settings)
        elif self._backend == "aws":
            await self._init_aws(settings)
        else:
            logger.info("secrets_backend_env", note="Using environment variables for secrets")

        self._initialized = True

    # ------------------------------------------------------------------
    # HashiCorp Vault Backend
    # ------------------------------------------------------------------
    async def _init_vault(self, settings: Any) -> None:
        """Initialize HashiCorp Vault client."""
        try:
            import hvac

            vault_addr = getattr(settings, "VAULT_ADDR", "http://localhost:8200")
            vault_token = getattr(settings, "VAULT_TOKEN", "")

            if not vault_token:
                # Try reading token from file (K8s service account)
                token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
                if os.path.exists(token_path):
                    with open(token_path) as f:
                        vault_token = f.read().strip()
                    logger.info("vault_k8s_token_loaded")

            self._vault_client = hvac.Client(url=vault_addr, token=vault_token)

            if self._vault_client.is_authenticated():
                logger.info("vault_connected", addr=vault_addr)
            else:
                logger.error("vault_auth_failed", addr=vault_addr)
                self._vault_client = None
                self._backend = "env"

        except ImportError:
            logger.warning("hvac_not_installed", note="Install with: pip install hvac")
            self._backend = "env"
        except Exception as e:
            logger.error("vault_init_error", error=str(e))
            self._backend = "env"

    async def _get_vault_secret(self, key: str, settings: Any) -> Optional[str]:
        """Retrieve a single secret from Vault KV v2."""
        if not self._vault_client:
            return None

        try:
            secret_path = getattr(settings, "VAULT_SECRET_PATH", "secret/data/cortexai")
            # KV v2: secret/data/<path> -> response["data"]["data"][key]
            mount_point = "secret"
            path = secret_path.replace("secret/data/", "")

            response = self._vault_client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=mount_point,
            )
            secrets_data = response.get("data", {}).get("data", {})
            return secrets_data.get(key)

        except Exception as e:
            logger.warning("vault_read_error", key=key, error=str(e))
            return None

    # ------------------------------------------------------------------
    # AWS Secrets Manager Backend
    # ------------------------------------------------------------------
    async def _init_aws(self, settings: Any) -> None:
        """Initialize AWS Secrets Manager client."""
        try:
            import boto3

            region = getattr(settings, "AWS_REGION", "us-east-1")
            self._aws_client = boto3.client("secretsmanager", region_name=region)
            logger.info("aws_secrets_connected", region=region)

        except ImportError:
            logger.warning("boto3_not_installed", note="Install with: pip install boto3")
            self._backend = "env"
        except Exception as e:
            logger.error("aws_secrets_init_error", error=str(e))
            self._backend = "env"

    async def _get_aws_secret(self, key: str, settings: Any) -> Optional[str]:
        """Retrieve a secret from AWS Secrets Manager."""
        if not self._aws_client:
            return None

        try:
            import json

            secret_name = getattr(settings, "AWS_SECRET_NAME", "cortexai/secrets")
            response = self._aws_client.get_secret_value(SecretId=secret_name)
            secret_string = response.get("SecretString", "{}")
            secrets_data = json.loads(secret_string)
            return secrets_data.get(key)

        except Exception as e:
            logger.warning("aws_secret_read_error", key=key, error=str(e))
            return None

    # ------------------------------------------------------------------
    # Unified API
    # ------------------------------------------------------------------
    async def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a secret by key.

        Lookup order:
        1. In-memory cache
        2. Configured backend (Vault / AWS)
        3. Environment variable (fallback)
        4. Provided default

        Args:
            key: The secret key name (e.g., "MISTRAL_API_KEY").
            default: Default value if not found anywhere.

        Returns:
            The secret value or default.
        """
        await self.initialize()

        # Check cache first
        if key in self._cache:
            return self._cache[key]

        value: Optional[str] = None

        # Try configured backend
        if self._backend == "vault":
            from backend.config import settings
            value = await self._get_vault_secret(key, settings)
        elif self._backend == "aws":
            from backend.config import settings
            value = await self._get_aws_secret(key, settings)

        # Fallback to environment variable
        if value is None:
            value = os.environ.get(key)

        # Fallback to provided default
        if value is None:
            value = default

        # Cache successful lookups
        if value is not None:
            self._cache[key] = value

        return value

    async def get_required_secret(self, key: str) -> str:
        """Retrieve a required secret. Raises ValueError if not found."""
        value = await self.get_secret(key)
        if value is None:
            raise ValueError(
                f"Required secret '{key}' not found. "
                f"Checked: {self._backend} backend, environment variables."
            )
        return value

    async def get_all_api_keys(self) -> dict[str, str]:
        """Retrieve all API keys used by CortexAI."""
        api_key_names = [
            "MISTRAL_API_KEY",
            "GROQ_API_KEY",
            "TAVILY_API_KEY",
            "EXA_API_KEY",
            "FIRECRAWL_API_KEY",
        ]
        result = {}
        for key_name in api_key_names:
            value = await self.get_secret(key_name)
            if value:
                result[key_name] = value
        return result

    def clear_cache(self) -> None:
        """Clear the in-memory secrets cache (e.g., on rotation)."""
        self._cache.clear()
        logger.info("secrets_cache_cleared")

    @property
    def backend_name(self) -> str:
        """Return the active backend name."""
        return self._backend


# Module-level singleton
secrets_manager = SecretsManager()
