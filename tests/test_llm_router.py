"""
Tests for the LLM router.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from er.budget import BudgetTracker
from er.llm.base import BudgetExceededError, LLMRequest, LLMResponse
from er.config import Settings
from er.llm.router import AgentRole, EscalationLevel, LLMRouter


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        SEC_USER_AGENT="Test User test@example.com",
        OPENAI_API_KEY="sk-test-openai",
        ANTHROPIC_API_KEY="sk-test-anthropic",
        GEMINI_API_KEY="test-gemini",
        PREFERRED_PROVIDER="",
    )


class TestRouterModelSelection:
    """Test model selection based on role and escalation."""

    def test_get_client_and_model_default_orchestration(self) -> None:
        """Test default model for orchestration role uses OpenAI."""
        router = LLMRouter(settings=make_settings(), dry_run=True)
        client, model = router.get_client_and_model(AgentRole.ORCHESTRATION)

        # Model may vary based on config, but should be OpenAI
        assert client.provider == "openai"
        assert model.startswith("gpt-")

    def test_get_client_and_model_judge_uses_opus(self) -> None:
        """Test judge role uses Claude Opus 4.5."""
        router = LLMRouter(settings=make_settings(), dry_run=True)
        client, model = router.get_client_and_model(AgentRole.JUDGE)

        assert model == "claude-opus-4-5-20251101"
        assert client.provider == "anthropic"

    def test_get_client_and_model_research_normal(self) -> None:
        """Test research role at normal escalation uses Gemini."""
        router = LLMRouter(settings=make_settings(), dry_run=True)
        client, model = router.get_client_and_model(
            AgentRole.RESEARCH, EscalationLevel.NORMAL
        )

        assert model == "gemini-2.5-pro"
        assert client.provider == "google"

    def test_get_client_and_model_research_elevated(self) -> None:
        """Test research role at elevated escalation uses GPT-5.2."""
        router = LLMRouter(settings=make_settings(), dry_run=True)
        client, model = router.get_client_and_model(
            AgentRole.RESEARCH, EscalationLevel.ELEVATED
        )

        assert model == "gpt-4o"
        assert client.provider == "openai"

    def test_get_client_and_model_synthesis(self) -> None:
        """Test synthesis role uses Claude Sonnet."""
        router = LLMRouter(settings=make_settings(), dry_run=True)
        client, model = router.get_client_and_model(AgentRole.SYNTHESIS)

        assert model == "claude-sonnet-4-5-20250929"
        assert client.provider == "anthropic"

    def test_escalation_changes_model(self) -> None:
        """Test that escalation level changes model selection."""
        router = LLMRouter(settings=make_settings(), dry_run=True)

        # Decomposition at normal
        _, model_normal = router.get_client_and_model(
            AgentRole.DECOMPOSITION, EscalationLevel.NORMAL
        )

        # Decomposition at critical
        _, model_critical = router.get_client_and_model(
            AgentRole.DECOMPOSITION, EscalationLevel.CRITICAL
        )

        assert model_normal != model_critical
        assert "opus" in model_critical.lower()


class TestRouterDryRun:
    """Test dry run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_response(self) -> None:
        """Test dry run mode returns a valid response."""
        router = LLMRouter(settings=make_settings(), dry_run=True)

        response = await router.complete(
            role=AgentRole.RESEARCH,
            messages=[{"role": "user", "content": "Test message"}],
        )

        assert isinstance(response, LLMResponse)
        assert response.content != ""
        assert response.input_tokens > 0
        assert response.output_tokens > 0

    @pytest.mark.asyncio
    async def test_dry_run_response_is_valid_json(self) -> None:
        """Test dry run response is valid JSON when structured output expected."""
        import orjson

        router = LLMRouter(settings=make_settings(), dry_run=True)

        response = await router.complete(
            role=AgentRole.RESEARCH,
            messages=[{"role": "user", "content": "Test"}],
        )

        # Should be parseable as JSON
        data = orjson.loads(response.content)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_dry_run_tracks_budget(self) -> None:
        """Test dry run mode still tracks budget."""
        tracker = BudgetTracker(budget_limit=100.0)
        router = LLMRouter(settings=make_settings(), dry_run=True, budget_tracker=tracker)

        await router.complete(
            role=AgentRole.RESEARCH,
            messages=[{"role": "user", "content": "Test"}],
        )

        assert tracker.total_cost_usd > 0
        assert tracker.total_input_tokens > 0

    @pytest.mark.asyncio
    async def test_dry_run_different_responses_by_role(self) -> None:
        """Test dry run gives different responses for different roles."""
        router = LLMRouter(settings=make_settings(), dry_run=True)

        research_response = await router.complete(
            role=AgentRole.RESEARCH,
            messages=[{"role": "user", "content": "Test"}],
        )

        judge_response = await router.complete(
            role=AgentRole.JUDGE,
            messages=[{"role": "user", "content": "Test"}],
        )

        assert research_response.content != judge_response.content


class TestRouterBudgetEnforcement:
    """Test budget enforcement."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises_error(self) -> None:
        """Test that exceeding budget raises BudgetExceededError."""
        tracker = BudgetTracker(budget_limit=0.001)  # Very small budget

        # Record some usage to exceed budget
        tracker.record_usage(
            provider="openai",
            model="gpt-5.2",
            input_tokens=1_000_000,
            output_tokens=500_000,
            agent="test",
            phase="test",
        )

        router = LLMRouter(settings=make_settings(), dry_run=True, budget_tracker=tracker)

        with pytest.raises(BudgetExceededError):
            await router.complete(
                role=AgentRole.RESEARCH,
                messages=[{"role": "user", "content": "Test"}],
            )

    @pytest.mark.asyncio
    async def test_within_budget_succeeds(self) -> None:
        """Test that requests within budget succeed."""
        tracker = BudgetTracker(budget_limit=100.0)
        router = LLMRouter(settings=make_settings(), dry_run=True, budget_tracker=tracker)

        # Should not raise
        response = await router.complete(
            role=AgentRole.RESEARCH,
            messages=[{"role": "user", "content": "Test"}],
        )

        assert response is not None


class TestRouterForceProvider:
    """Test force_provider context manager."""

    @pytest.mark.asyncio
    async def test_force_provider(self) -> None:
        """Test forcing a specific provider."""
        router = LLMRouter(settings=make_settings(), dry_run=True)

        async with router.force_provider("anthropic"):
            client, model = router.get_client_and_model(AgentRole.ORCHESTRATION)
            assert client.provider == "anthropic"

        # After context, should revert
        client, model = router.get_client_and_model(AgentRole.ORCHESTRATION)
        assert client.provider == "openai"


class TestAgentRole:
    """Test AgentRole enum."""

    def test_all_roles_have_mapping(self) -> None:
        """Test that all agent roles have model mappings."""
        router = LLMRouter(settings=make_settings(), dry_run=True)

        for role in AgentRole:
            for level in EscalationLevel:
                client, model = router.get_client_and_model(role, level)
                assert client is not None
                assert model != ""


class TestEscalationLevel:
    """Test EscalationLevel enum."""

    def test_escalation_levels_ordered(self) -> None:
        """Test escalation levels are properly ordered."""
        assert EscalationLevel.NORMAL.value < EscalationLevel.ELEVATED.value
        assert EscalationLevel.ELEVATED.value < EscalationLevel.CRITICAL.value
