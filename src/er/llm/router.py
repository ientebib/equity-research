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
        EscalationLevel.NORMAL: ("gpt-5.2-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-5.2", "openai"),
        EscalationLevel.CRITICAL: ("gpt-5.2", "openai"),
    },
    AgentRole.DISCOVERY: {
        EscalationLevel.NORMAL: ("gpt-5.2", "openai"),
        EscalationLevel.ELEVATED: ("gpt-5.2", "openai"),
        EscalationLevel.CRITICAL: ("claude-sonnet-4-5-20250929", "anthropic"),
    },
    AgentRole.DECOMPOSITION: {
        EscalationLevel.NORMAL: ("gpt-5.2", "openai"),
        EscalationLevel.ELEVATED: ("claude-sonnet-4-5-20250929", "anthropic"),
        EscalationLevel.CRITICAL: ("claude-opus-4-5-20251101", "anthropic"),
    },
    AgentRole.RESEARCH: {
        EscalationLevel.NORMAL: ("gemini-3-pro", "google"),
        EscalationLevel.ELEVATED: ("gpt-5.2", "openai"),
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
        EscalationLevel.NORMAL: ("gpt-5.2-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-5.2", "openai"),
        EscalationLevel.CRITICAL: ("gpt-5.2", "openai"),
    },
    AgentRole.OUTPUT: {
        EscalationLevel.NORMAL: ("gpt-5.2-mini", "openai"),
        EscalationLevel.ELEVATED: ("gpt-5.2", "openai"),
        EscalationLevel.CRITICAL: ("claude-sonnet-4-5-20250929", "anthropic"),
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

        # Override workhorse model for orchestration/factcheck/output
        if s.model_workhorse:
            provider = self._infer_provider(s.model_workhorse)
            for role in [AgentRole.ORCHESTRATION, AgentRole.FACTCHECK, AgentRole.OUTPUT]:
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

    def _get_client(self, provider: str) -> OpenAIClient | AnthropicClient | GeminiClient:
        """Get or create client for provider.

        Args:
            provider: Provider name.

        Returns:
            LLM client instance.
        """
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

        # Get client and model
        client, model = self.get_client_and_model(role, escalation)

        # Handle dry run mode
        if self._dry_run:
            return self._get_dry_run_response(role, model, client.provider)

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
