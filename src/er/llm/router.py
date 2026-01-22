"""
LLM Router with policy-based model selection.

Routes requests to appropriate models based on agent role and escalation level.
Supports dry run mode for testing without API calls.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncIterator

from er.budget import BudgetTracker
from er.config import Settings
from er.llm.anthropic_client import AnthropicClient
from er.llm.base import (
    BudgetExceededError,
    DRY_RUN_RESPONSES,
    LLMRequest,
    LLMResponse,
    ToolCall,
)
from er.llm.gemini_client import GeminiClient
from er.llm.openai_client import OpenAIClient
from er.logging import get_logger

logger = get_logger(__name__)


class AgentRole(Enum):
    """Agent roles for model selection."""

    ORCHESTRATION = "orchestration"
    DISCOVERY = "discovery"
    DECOMPOSITION = "decomposition"
    RESEARCH = "research"
    SYNTHESIS = "synthesis"
    JUDGE = "judge"
    FACTCHECK = "factcheck"
    OUTPUT = "output"
    WORKHORSE = "workhorse"  # For quick, high-volume tasks (recency, coverage, entailment)


class EscalationLevel(Enum):
    """Escalation levels for model selection."""

    NORMAL = 0
    ELEVATED = 1
    CRITICAL = 2


# Default model mapping by role and escalation
# Uses 2025 models: GPT-5.2, Claude 4.5, Gemini 3
DEFAULT_MODEL_MAP: dict[AgentRole, dict[EscalationLevel, tuple[str, str]]] = {
    # (model, provider)
    AgentRole.ORCHESTRATION: {
        EscalationLevel.NORMAL: ("gpt-4o-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-4o", "openai"),
        EscalationLevel.CRITICAL: ("gpt-4o", "openai"),
    },
    AgentRole.DISCOVERY: {
        EscalationLevel.NORMAL: ("gpt-4o", "openai"),
        EscalationLevel.ELEVATED: ("gpt-4o", "openai"),
        EscalationLevel.CRITICAL: ("claude-sonnet-4-5-20250929", "anthropic"),
    },
    AgentRole.DECOMPOSITION: {
        EscalationLevel.NORMAL: ("gpt-4o", "openai"),
        EscalationLevel.ELEVATED: ("claude-sonnet-4-5-20250929", "anthropic"),
        EscalationLevel.CRITICAL: ("claude-opus-4-5-20251101", "anthropic"),
    },
    AgentRole.RESEARCH: {
        EscalationLevel.NORMAL: ("gemini-2.5-pro", "google"),
        EscalationLevel.ELEVATED: ("gpt-4o", "openai"),
        EscalationLevel.CRITICAL: ("claude-sonnet-4-5-20250929", "anthropic"),
    },
    AgentRole.SYNTHESIS: {
        EscalationLevel.NORMAL: ("claude-sonnet-4-5-20250929", "anthropic"),
        EscalationLevel.ELEVATED: ("claude-sonnet-4-5-20250929", "anthropic"),
        EscalationLevel.CRITICAL: ("claude-opus-4-5-20251101", "anthropic"),
    },
    AgentRole.JUDGE: {
        EscalationLevel.NORMAL: ("claude-opus-4-5-20251101", "anthropic"),
        EscalationLevel.ELEVATED: ("claude-opus-4-5-20251101", "anthropic"),
        EscalationLevel.CRITICAL: ("claude-opus-4-5-20251101", "anthropic"),
    },
    AgentRole.FACTCHECK: {
        EscalationLevel.NORMAL: ("gpt-4o-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-4o", "openai"),
        EscalationLevel.CRITICAL: ("gpt-4o", "openai"),
    },
    AgentRole.OUTPUT: {
        EscalationLevel.NORMAL: ("gpt-4o-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-4o", "openai"),
        EscalationLevel.CRITICAL: ("claude-sonnet-4-5-20250929", "anthropic"),
    },
    AgentRole.WORKHORSE: {
        EscalationLevel.NORMAL: ("gpt-4o-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-4o", "openai"),
        EscalationLevel.CRITICAL: ("gpt-4o", "openai"),
    },
}

PREFERRED_PROVIDER_MODELS: dict[str, dict[AgentRole, str]] = {
    "google": {
        AgentRole.ORCHESTRATION: "gemini-2.5-flash",
        AgentRole.DISCOVERY: "gemini-2.5-pro",
        AgentRole.DECOMPOSITION: "gemini-2.5-pro",
        AgentRole.RESEARCH: "gemini-2.5-pro",
        AgentRole.SYNTHESIS: "gemini-2.5-pro",
        AgentRole.JUDGE: "gemini-2.5-pro",
        AgentRole.FACTCHECK: "gemini-2.5-flash",
        AgentRole.OUTPUT: "gemini-2.5-flash",
        AgentRole.WORKHORSE: "gemini-2.5-flash",
    },
    "openai": {
        AgentRole.ORCHESTRATION: "gpt-4o-mini",
        AgentRole.DISCOVERY: "gpt-4o",
        AgentRole.DECOMPOSITION: "gpt-4o",
        AgentRole.RESEARCH: "gpt-4o",
        AgentRole.SYNTHESIS: "gpt-4o",
        AgentRole.JUDGE: "gpt-4o",
        AgentRole.FACTCHECK: "gpt-4o-mini",
        AgentRole.OUTPUT: "gpt-4o-mini",
        AgentRole.WORKHORSE: "gpt-4o-mini",
    },
    "anthropic": {
        AgentRole.ORCHESTRATION: "claude-sonnet-4-5-20250929",
        AgentRole.DISCOVERY: "claude-sonnet-4-5-20250929",
        AgentRole.DECOMPOSITION: "claude-sonnet-4-5-20250929",
        AgentRole.RESEARCH: "claude-sonnet-4-5-20250929",
        AgentRole.SYNTHESIS: "claude-sonnet-4-5-20250929",
        AgentRole.JUDGE: "claude-opus-4-5-20251101",
        AgentRole.FACTCHECK: "claude-sonnet-4-5-20250929",
        AgentRole.OUTPUT: "claude-sonnet-4-5-20250929",
        AgentRole.WORKHORSE: "claude-sonnet-4-5-20250929",
    },
}


class LLMRouter:
    """Routes LLM requests to appropriate providers/models.

    Features:
    - Policy-based model selection by role and escalation
    - Budget enforcement
    - Dry run mode for testing
    - Provider forcing via context manager
    """

    def __init__(
        self,
        settings: Settings | None = None,
        budget_tracker: BudgetTracker | None = None,
        dry_run: bool | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            settings: Application settings. If None, loads from env.
            budget_tracker: Budget tracker for cost management.
            dry_run: Force dry run mode. If None, uses DRY_RUN env var.
        """
        self._settings = settings or Settings()
        self._budget_tracker = budget_tracker
        self._forced_provider: str | None = None

        # Determine dry run mode
        if dry_run is not None:
            self._dry_run = dry_run
        else:
            self._dry_run = os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes")

        # Initialize clients lazily
        self._openai_client: OpenAIClient | None = None
        self._anthropic_client: AnthropicClient | None = None
        self._gemini_client: GeminiClient | None = None

        # Build model map from settings
        self._model_map = self._build_model_map()

    def _build_model_map(self) -> dict[AgentRole, dict[EscalationLevel, tuple[str, str]]]:
        """Build model mapping from settings.

        Returns:
            Model map with role -> escalation -> (model, provider).
        """
        # Start with defaults
        model_map = dict(DEFAULT_MODEL_MAP)

        # Override from settings if configured
        s = self._settings

        preferred = s.preferred_provider
        if preferred:
            model_map = {}
            provider_models = PREFERRED_PROVIDER_MODELS.get(preferred, {})
            for role in AgentRole:
                if provider_models:
                    model = provider_models.get(role, provider_models.get(AgentRole.WORKHORSE, s.model_workhorse))
                else:
                    model = s.model_workhorse
                model_map[role] = {
                    EscalationLevel.NORMAL: (model, preferred),
                    EscalationLevel.ELEVATED: (model, preferred),
                    EscalationLevel.CRITICAL: (model, preferred),
                }
            return model_map

        # Override workhorse model for orchestration/factcheck/output/workhorse
        if s.model_workhorse:
            provider = self._infer_provider(s.model_workhorse)
            for role in [AgentRole.ORCHESTRATION, AgentRole.FACTCHECK, AgentRole.OUTPUT, AgentRole.WORKHORSE]:
                model_map[role][EscalationLevel.NORMAL] = (s.model_workhorse, provider)

        # Override research model
        if s.model_research:
            provider = self._infer_provider(s.model_research)
            model_map[AgentRole.RESEARCH][EscalationLevel.NORMAL] = (s.model_research, provider)

        # Override judge model
        if s.model_judge:
            provider = self._infer_provider(s.model_judge)
            for level in EscalationLevel:
                model_map[AgentRole.JUDGE][level] = (s.model_judge, provider)

        # Override synthesis model
        if s.model_synthesis:
            provider = self._infer_provider(s.model_synthesis)
            model_map[AgentRole.SYNTHESIS][EscalationLevel.NORMAL] = (s.model_synthesis, provider)
            model_map[AgentRole.SYNTHESIS][EscalationLevel.ELEVATED] = (s.model_synthesis, provider)

        return model_map

    @property
    def preferred_provider(self) -> str | None:
        """Return preferred provider if configured."""
        return self._settings.preferred_provider

    def _infer_provider(self, model: str) -> str:
        """Infer provider from model name.

        Args:
            model: Model name.

        Returns:
            Provider name.
        """
        if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
            return "openai"
        elif model.startswith("claude-"):
            return "anthropic"
        elif model.startswith("gemini-"):
            return "google"
        else:
            # Default to OpenAI
            return "openai"

    def _has_provider_key(self, provider: str) -> bool:
        """Check if we have an API key for the provider.

        Args:
            provider: Provider name.

        Returns:
            True if API key is available.
        """
        if provider == "openai":
            return bool(self._settings.openai_api_key)
        elif provider == "anthropic":
            return bool(self._settings.anthropic_api_key)
        elif provider == "google":
            return bool(self._settings.gemini_api_key)
        return False

    def _get_fallback_provider(self, original_provider: str) -> str | None:
        """Get a fallback provider when the original is unavailable.

        Args:
            original_provider: The provider that's missing a key.

        Returns:
            Fallback provider name, or None if no fallback available.
        """
        # Fallback priority: OpenAI -> Anthropic -> Google
        fallback_order = ["openai", "anthropic", "google"]
        for provider in fallback_order:
            if provider != original_provider and self._has_provider_key(provider):
                logger.warning(
                    f"Provider {original_provider} unavailable, falling back to {provider}"
                )
                return provider
        return None

    def _get_client(self, provider: str) -> OpenAIClient | AnthropicClient | GeminiClient:
        """Get or create client for provider.

        Args:
            provider: Provider name.

        Returns:
            LLM client instance.

        Raises:
            ValueError: If provider is unknown or no API key is available.
        """
        # Check if we have the key for the requested provider
        if not self._has_provider_key(provider):
            fallback = self._get_fallback_provider(provider)
            if fallback:
                provider = fallback
            else:
                raise ValueError(
                    f"No API key for {provider} and no fallback provider available. "
                    f"Set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY"
                )

        if provider == "openai":
            if self._openai_client is None:
                self._openai_client = OpenAIClient(api_key=self._settings.openai_api_key)
            return self._openai_client
        elif provider == "anthropic":
            if self._anthropic_client is None:
                self._anthropic_client = AnthropicClient(api_key=self._settings.anthropic_api_key)
            return self._anthropic_client
        elif provider == "google":
            if self._gemini_client is None:
                self._gemini_client = GeminiClient(api_key=self._settings.gemini_api_key)
            return self._gemini_client
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def get_client_and_model(
        self,
        role: AgentRole,
        escalation: EscalationLevel = EscalationLevel.NORMAL,
    ) -> tuple[OpenAIClient | AnthropicClient | GeminiClient, str]:
        """Get client and model for a role/escalation combination.

        Args:
            role: Agent role.
            escalation: Escalation level.

        Returns:
            Tuple of (client, model_name).
        """
        model, provider = self._model_map[role][escalation]

        # Apply forced provider if set
        if self._forced_provider:
            provider = self._forced_provider
            # Adjust model for the forced provider
            if provider == "openai":
                model = self._settings.model_workhorse or "gpt-5.2"
            elif provider == "anthropic":
                model = self._settings.model_synthesis or "claude-sonnet-4-5-20250929"
            elif provider == "google":
                model = self._settings.model_research or "gemini-3-pro"

        client = self._get_client(provider)
        return client, model

    async def complete(
        self,
        role: AgentRole,
        messages: list[dict[str, Any]],
        escalation: EscalationLevel = EscalationLevel.NORMAL,
        agent_name: str | None = None,
        phase: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request with policy-based routing.

        Args:
            role: Agent role for model selection.
            messages: Chat messages.
            escalation: Escalation level.
            agent_name: Name of the calling agent (for tracking).
            phase: Current phase (for tracking).
            **kwargs: Additional request parameters.

        Returns:
            LLM response.

        Raises:
            BudgetExceededError: If budget is exceeded.
        """
        # Check budget before making the call
        if self._budget_tracker and self._budget_tracker.is_exceeded():
            raise BudgetExceededError("Budget limit exceeded")

        # Handle dry run mode BEFORE creating clients (avoid API key errors)
        if self._dry_run:
            model, provider = self._model_map[role][escalation]
            return self._get_dry_run_response(role, model, provider)

        # Get client and model (this may create clients that need API keys)
        client, model = self.get_client_and_model(role, escalation)

        # Build request
        request = LLMRequest(
            messages=messages,
            model=model,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens"),
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
            response_format=kwargs.get("response_format"),
            stop=kwargs.get("stop"),
        )

        # Make the call
        start_time = time.monotonic()

        if request.tools:
            response = await client.complete_with_tools(request)
        else:
            response = await client.complete(request)

        # Log the call
        logger.info(
            "LLM call completed",
            role=role.value,
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            agent=agent_name,
            phase=phase,
        )

        # Record usage for budget tracking
        if self._budget_tracker:
            cost = self._budget_tracker.record_usage(
                provider=response.provider,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=agent_name or role.value,
                phase=phase or "unknown",
            )
            logger.debug("Recorded cost", cost_usd=cost)

        return response

    async def complete_with_web_search(
        self,
        role: AgentRole,
        messages: list[dict[str, Any]],
        escalation: EscalationLevel = EscalationLevel.NORMAL,
        reasoning_effort: str | None = None,
        agent_name: str | None = None,
        phase: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request with provider-specific web search/grounding."""
        if self._budget_tracker and self._budget_tracker.is_exceeded():
            raise BudgetExceededError("Budget limit exceeded")

        if self._dry_run:
            model, provider = self._model_map[role][escalation]
            return self._get_dry_run_response(role, model, provider)

        client, model = self.get_client_and_model(role, escalation)

        request = LLMRequest(
            messages=messages,
            model=model,
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
            stop=kwargs.get("stop"),
            response_format=kwargs.get("response_format"),
        )

        if isinstance(client, OpenAIClient):
            response = await client.complete_with_web_search(
                request,
                reasoning_effort=reasoning_effort or "medium",
            )
        elif isinstance(client, AnthropicClient):
            response = await client.complete_with_web_search(request)
        elif isinstance(client, GeminiClient):
            response = await client.complete_with_grounding(request, enable_google_search=True)
        else:
            response = await client.complete(request)

        logger.info(
            "LLM web search completed",
            role=role.value,
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            agent=agent_name,
            phase=phase,
        )

        if self._budget_tracker:
            cost = self._budget_tracker.record_usage(
                provider=response.provider,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=agent_name or role.value,
                phase=phase or "unknown",
            )
            logger.debug("Recorded cost", cost_usd=cost)

        return response

    async def call(
        self,
        role: AgentRole,
        messages: list[dict[str, Any]],
        escalation: EscalationLevel = EscalationLevel.NORMAL,
        agent_name: str | None = None,
        phase: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Backward-compatible wrapper that returns a dict response.

        Some agents expect a dict-like response (response.get("content")).
        """
        response = await self.complete(
            role=role,
            messages=messages,
            escalation=escalation,
            agent_name=agent_name,
            phase=phase,
            **kwargs,
        )
        tool_calls = None
        if response.tool_calls:
            tool_calls = [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in response.tool_calls
            ]
        return {
            "content": response.content,
            "model": response.model,
            "provider": response.provider,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "tool_calls": tool_calls,
            "finish_reason": response.finish_reason,
            "latency_ms": response.latency_ms,
            "metadata": response.metadata,
        }

    def _get_dry_run_response(
        self,
        role: AgentRole,
        model: str,
        provider: str,
    ) -> LLMResponse:
        """Get a dry run response for testing.

        Args:
            role: Agent role.
            model: Model name.
            provider: Provider name.

        Returns:
            Fake LLM response.
        """
        # Get role-specific dry run config
        dry_config = DRY_RUN_RESPONSES.get(role.value, DRY_RUN_RESPONSES["default"])

        # Record fake usage if tracking
        if self._budget_tracker:
            self._budget_tracker.record_usage(
                provider=provider,
                model=model,
                input_tokens=dry_config.input_tokens,
                output_tokens=dry_config.output_tokens,
                agent=role.value,
                phase="dry_run",
            )

        return LLMResponse(
            content=dry_config.content,
            model=model,
            provider=provider,
            input_tokens=dry_config.input_tokens,
            output_tokens=dry_config.output_tokens,
            finish_reason="stop",
            latency_ms=50,  # Simulated latency
        )

    @asynccontextmanager
    async def force_provider(self, provider: str) -> AsyncIterator[None]:
        """Context manager to force a specific provider.

        Args:
            provider: Provider to force ("openai", "anthropic", "google").

        Yields:
            None
        """
        old_provider = self._forced_provider
        self._forced_provider = provider
        try:
            yield
        finally:
            self._forced_provider = old_provider

    def set_budget_tracker(self, tracker: BudgetTracker) -> None:
        """Set the budget tracker.

        Args:
            tracker: Budget tracker instance.
        """
        self._budget_tracker = tracker

    async def close(self) -> None:
        """Close all clients."""
        if self._openai_client:
            await self._openai_client.close()
        if self._anthropic_client:
            await self._anthropic_client.close()
        if self._gemini_client:
            await self._gemini_client.close()
