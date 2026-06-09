"""
Multi-Model Fallback Router (Arch Issue #7).

Provides a ModelRouter class that:
- Routes LLM calls through a primary model with automatic fallback chain
- Supports task-type routing (complex vs fast queries)
- Cost-aware routing: prefer cheaper models for simple queries
- Automatic failover using the existing CircuitBreaker pattern
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI as ChatLiteLLM

from backend.config import settings
from backend.core.logger import get_logger
from backend.core.retry import CircuitBreaker

logger = get_logger(__name__)


class ModelRouter:
    """Routes LLM requests through a fallback chain of models.

    Usage:
        router = ModelRouter()
        llm = router.get_llm(task_type="routing")
        response = await llm.ainvoke(messages)

    Task types:
        - "routing":   Deterministic supervisor routing (fast model, low temp)
        - "planning":  Research plan generation (orchestrator model, moderate temp)
        - "search":    Search agent tasks (orchestrator model)
        - "verify":    Verification tasks (orchestrator model)
        - "fast":      Quick classification / summarization (fast model)
        - "creative":  Report synthesis and creative output (orchestrator model, higher temp)
    """

    # Cost tiers (approx $/1M output tokens) — lower = cheaper
    _MODEL_COST_TIERS: dict[str, float] = {
        "groq/llama3-8b-8192": 0.10,
        "groq/llama3-70b-8192": 0.60,
        "mistral/mistral-large-latest": 6.0,
        "openai/gpt-4o-mini": 0.60,
        "openai/gpt-4o": 15.0,
    }

    def __init__(
        self,
        primary_model: str | None = None,
        fallback_models: list[str] | None = None,
    ):
        self.primary_model = primary_model or settings.ORCHESTRATOR_MODEL
        self.fallback_models = list(fallback_models or settings.FALLBACK_MODELS)
        self._model_chain = [self.primary_model] + self.fallback_models
        self._breakers: dict[str, CircuitBreaker] = {
            model: CircuitBreaker(threshold=settings.CIRCUIT_BREAKER_THRESHOLD, reset_timeout=60.0)
            for model in self._model_chain
        }
        logger.info(
            "model_router_initialized",
            primary=self.primary_model,
            fallbacks=self.fallback_models,
        )

    def _select_model(self, task_type: str) -> str:
        """Select the best model for the given task type, respecting circuit breaker state."""
        if task_type in ("routing", "fast"):
            # Prefer fast/cheap model for simple tasks
            candidates = [settings.FAST_MODEL] + self._model_chain
        else:
            candidates = list(self._model_chain)

        for model in candidates:
            breaker = self._breakers.get(model)
            if breaker:
                try:
                    breaker.check(model)
                    return model
                except ConnectionError:
                    logger.info("model_router_skip_open_circuit", model=model)
                    continue
        # All circuits open — return primary as last resort
        return self.primary_model

    def _temperature_for_task(self, task_type: str) -> float:
        """Return the appropriate temperature for the task type."""
        return {
            "routing": settings.SUPERVISOR_ROUTING_TEMP,
            "planning": settings.SUPERVISOR_PLANNING_TEMP,
            "creative": settings.SUPERVISOR_CREATIVE_TEMP,
            "search": settings.LLM_TEMPERATURE,
            "verify": 0.3,
            "fast": 0.0,
        }.get(task_type, settings.SUPERVISOR_ROUTING_TEMP)

    def get_llm(self, task_type: str = "routing") -> ChatLiteLLM:
        """Return an LLM instance configured for the selected model and task type."""
        model = self._select_model(task_type)
        temperature = self._temperature_for_task(task_type)
        logger.debug("model_router_selected", task_type=task_type, model=model, temperature=temperature)
        return ChatLiteLLM(model=model, temperature=temperature)

    def record_success(self, model: str | None = None):
        """Record a successful call to the given model (resets circuit breaker)."""
        target = model or self.primary_model
        breaker = self._breakers.get(target)
        if breaker:
            breaker.record_success()

    def record_failure(self, model: str | None = None):
        """Record a failed call to the given model (may trip circuit breaker)."""
        target = model or self.primary_model
        breaker = self._breakers.get(target)
        if breaker:
            breaker.record_failure(target)

    async def ainvoke_with_fallback(self, messages: list, task_type: str = "routing") -> Any:
        """Invoke the LLM with automatic fallback on failure.

        Tries each model in the chain until one succeeds.
        Returns the response from the first successful model.
        Raises the last exception if all models fail.
        """
        last_error: Exception | None = None

        for model in self._model_chain:
            breaker = self._breakers.get(model)
            if breaker:
                try:
                    breaker.check(model)
                except ConnectionError:
                    continue

            llm = ChatLiteLLM(
                model=model,
                temperature=self._temperature_for_task(task_type),
            )
            try:
                response = await llm.ainvoke(messages)
                self.record_success(model)
                return response
            except Exception as exc:
                last_error = exc
                self.record_failure(model)
                logger.warning(
                    "model_router_fallback",
                    failed_model=model,
                    error=str(exc),
                    task_type=task_type,
                )

        raise last_error or RuntimeError("All models in the chain failed")

    def get_model_status(self) -> dict[str, dict]:
        """Return circuit breaker status for all models in the chain."""
        return {
            model: {
                "is_open": breaker._is_open,
                "failure_count": breaker._failure_count,
                "cost_tier": self._MODEL_COST_TIERS.get(model, 0.0),
            }
            for model, breaker in self._breakers.items()
        }


# Module-level singleton
model_router = ModelRouter()
