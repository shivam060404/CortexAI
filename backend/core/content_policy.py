"""
Content Policy Engine (Pillar 4 Enhancement / Task 15).

Configurable per-organization content policies with tiered approval modes:
- ``auto``: no approval needed; all actions execute immediately
- ``supervised``: sensitive actions (web scraping, code exec) require HITL approval
- ``locked``: all agent actions require explicit approval before execution

Integrates with existing guardrails (scan_user_input, scan_llm_output).
"""

from __future__ import annotations

import re
from typing import Optional
from dataclasses import dataclass, field

from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ContentPolicyResult:
    """Result of a content policy check."""
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    policy_mode: str = "auto"


@dataclass
class ContentPolicy:
    """Per-organization content policy configuration."""
    mode: str = "auto"  # auto | supervised | locked
    allowed_topics: list[str] = field(default_factory=list)
    prohibited_topics: list[str] = field(default_factory=list)
    sensitive_tool_names: set[str] = field(default_factory=lambda: {
        "execute_code_agent_task",
        "web_search",
        "academic_search",
        "news_search",
    })


# Default global policy (overridable per-org)
_global_policy = ContentPolicy(mode=settings.CONTENT_POLICY_MODE)

# Per-organization policies
_org_policies: dict[str, ContentPolicy] = {}


def get_org_policy(org_id: str | None = None) -> ContentPolicy:
    """Get the content policy for an organization, falling back to global."""
    if org_id and org_id in _org_policies:
        return _org_policies[org_id]
    return _global_policy


def set_org_policy(org_id: str, policy: ContentPolicy) -> None:
    """Set a custom content policy for an organization."""
    _org_policies[org_id] = policy
    logger.info("org_content_policy_set", org_id=org_id, mode=policy.mode)


def check_content_policy(
    query: str,
    tool_name: str | None = None,
    org_id: str | None = None,
) -> ContentPolicyResult:
    """Evaluate a query or tool invocation against the content policy.

    Returns ContentPolicyResult indicating whether the action is allowed,
    requires approval, or is blocked.
    """
    policy = get_org_policy(org_id)

    # Locked mode: everything requires approval
    if policy.mode == "locked":
        return ContentPolicyResult(
            allowed=True,
            requires_approval=True,
            reason="Organization policy requires approval for all actions",
            policy_mode="locked",
        )

    # Check prohibited topics
    query_lower = query.lower() if query else ""
    for topic in policy.prohibited_topics:
        if topic.lower() in query_lower:
            logger.warning("content_policy_blocked", topic=topic, query=query[:80])
            return ContentPolicyResult(
                allowed=False,
                reason=f"Topic '{topic}' is prohibited by organization policy",
                policy_mode=policy.mode,
            )

    # Supervised mode: sensitive tools require approval
    if policy.mode == "supervised" and tool_name:
        if tool_name in policy.sensitive_tool_names:
            return ContentPolicyResult(
                allowed=True,
                requires_approval=True,
                reason=f"Tool '{tool_name}' requires supervisor approval",
                policy_mode="supervised",
            )

    # Allowed topics filter (if configured, only allow these)
    if policy.allowed_topics:
        matched = any(t.lower() in query_lower for t in policy.allowed_topics)
        if not matched:
            return ContentPolicyResult(
                allowed=False,
                reason="Query does not match any allowed topic",
                policy_mode=policy.mode,
            )

    return ContentPolicyResult(
        allowed=True,
        policy_mode=policy.mode,
    )


def check_tool_approval_required(tool_name: str, org_id: str | None = None) -> bool:
    """Quick check if a tool requires approval under the current policy."""
    policy = get_org_policy(org_id)
    if policy.mode == "locked":
        return True
    if policy.mode == "supervised" and tool_name in policy.sensitive_tool_names:
        return True
    return False
