"""
Tests for the budget tracker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from er.budget import BudgetTracker, calculate_cost, get_model_cost


class TestCostCalculation:
    """Test cost calculation functions."""

    def test_get_model_cost_known_model(self) -> None:
        """Test getting cost for known models."""
        # GPT-5.2
        cost = get_model_cost("gpt-5.2-2025-12-11")
        assert cost == (1.75, 14.00)

        # Claude Opus 4.5
        cost = get_model_cost("claude-opus-4-5-20251101")
        assert cost == (15.00, 75.00)

        # Gemini 3 Pro
        cost = get_model_cost("gemini-3-pro")
        assert cost == (1.25, 5.00)

    def test_get_model_cost_unknown_model(self) -> None:
        """Test getting cost for unknown model returns default."""
        cost = get_model_cost("unknown-model-xyz")
        assert cost == (2.00, 10.00)  # Default

    def test_calculate_cost(self) -> None:
        """Test cost calculation."""
        # 1M tokens each at gpt-5.2 rates ($1.75 input, $14 output)
        cost = calculate_cost("gpt-5.2-2025-12-11", 1_000_000, 1_000_000)
        assert cost == pytest.approx(15.75)  # 1.75 + 14.00

        # 100k tokens
        cost = calculate_cost("gpt-5.2-2025-12-11", 100_000, 100_000)
        assert cost == pytest.approx(1.575)  # (0.175 + 1.40)

    def test_calculate_cost_small_usage(self) -> None:
        """Test cost calculation for small token counts."""
        # 1000 input, 500 output at gpt-5.2
        cost = calculate_cost("gpt-5.2-2025-12-11", 1000, 500)
        # Input: 1000/1M * 1.75 = 0.00175
        # Output: 500/1M * 14.00 = 0.007
        assert cost == pytest.approx(0.00875)


class TestBudgetTracker:
    """Test BudgetTracker class."""

    def test_record_usage(self) -> None:
        """Test recording usage."""
        tracker = BudgetTracker(budget_limit=100.0)

        cost = tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="researcher_1",
            phase="research",
        )

        assert cost > 0
        assert tracker.total_cost_usd == cost
        assert tracker.total_input_tokens == 100_000
        assert tracker.total_output_tokens == 50_000

    def test_record_multiple_usage(self) -> None:
        """Test recording multiple usage calls."""
        tracker = BudgetTracker(budget_limit=100.0)

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="researcher_1",
            phase="research",
        )

        tracker.record_usage(
            provider="anthropic",
            model="claude-opus-4-5-20251101",
            input_tokens=50_000,
            output_tokens=25_000,
            agent="judge",
            phase="deliberate",
        )

        assert tracker.total_input_tokens == 150_000
        assert tracker.total_output_tokens == 75_000
        assert len(tracker.records) == 2

    def test_get_remaining(self) -> None:
        """Test getting remaining budget."""
        tracker = BudgetTracker(budget_limit=10.0)

        # Record some usage
        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=1_000_000,
            output_tokens=100_000,
            agent="test",
            phase="test",
        )

        remaining = tracker.get_remaining()
        assert remaining < 10.0
        assert remaining == 10.0 - tracker.total_cost_usd

    def test_is_exceeded(self) -> None:
        """Test budget exceeded check."""
        tracker = BudgetTracker(budget_limit=0.01)  # Very small budget

        assert not tracker.is_exceeded()

        # Record usage that exceeds budget
        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=100_000,
            agent="test",
            phase="test",
        )

        assert tracker.is_exceeded()

    def test_breakdown_by_provider(self) -> None:
        """Test breakdown by provider."""
        tracker = BudgetTracker(budget_limit=100.0)

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="test",
        )

        tracker.record_usage(
            provider="anthropic",
            model="claude-opus-4-5-20251101",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="test",
        )

        breakdown = tracker.get_breakdown()

        assert "openai" in breakdown["by_provider"]
        assert "anthropic" in breakdown["by_provider"]
        assert breakdown["by_provider"]["anthropic"] > breakdown["by_provider"]["openai"]

    def test_breakdown_by_agent(self) -> None:
        """Test breakdown by agent."""
        tracker = BudgetTracker(budget_limit=100.0)

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="researcher_1",
            phase="research",
        )

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=200_000,
            output_tokens=100_000,
            agent="researcher_2",
            phase="research",
        )

        breakdown = tracker.get_breakdown()

        assert "researcher_1" in breakdown["by_agent"]
        assert "researcher_2" in breakdown["by_agent"]
        assert breakdown["by_agent"]["researcher_2"] > breakdown["by_agent"]["researcher_1"]

    def test_breakdown_by_phase(self) -> None:
        """Test breakdown by phase."""
        tracker = BudgetTracker(budget_limit=100.0)

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="discovery",
        )

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="research",
        )

        breakdown = tracker.get_breakdown()

        assert "discovery" in breakdown["by_phase"]
        assert "research" in breakdown["by_phase"]

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        tracker = BudgetTracker(budget_limit=100.0)

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="test",
        )

        data = tracker.to_dict()

        assert data["budget_limit"] == 100.0
        assert data["total_cost_usd"] > 0
        assert data["total_input_tokens"] == 100_000
        assert data["total_output_tokens"] == 50_000
        assert len(data["records"]) == 1

    def test_from_dict(self) -> None:
        """Test loading from dict."""
        original = BudgetTracker(budget_limit=100.0)

        original.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="test",
        )

        data = original.to_dict()
        loaded = BudgetTracker.from_dict(data)

        assert loaded.budget_limit == original.budget_limit
        assert loaded.total_cost_usd == original.total_cost_usd
        assert loaded.total_input_tokens == original.total_input_tokens
        assert len(loaded.records) == len(original.records)

    def test_save_to_file(self, temp_dir: Path) -> None:
        """Test saving to file."""
        tracker = BudgetTracker(budget_limit=100.0, output_dir=temp_dir)

        tracker.record_usage(
            provider="openai",
            model="gpt-5.2-2025-12-11",
            input_tokens=100_000,
            output_tokens=50_000,
            agent="test",
            phase="test",
        )

        costs_path = temp_dir / "costs.json"
        assert costs_path.exists()

        import orjson

        with open(costs_path, "rb") as f:
            data = orjson.loads(f.read())

        assert data["budget_limit"] == 100.0
        assert data["total_cost_usd"] > 0
