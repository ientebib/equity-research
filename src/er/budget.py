"""
Budget tracking for the equity research system.

Tracks token usage and costs for Anthropic Claude models.
This is an Anthropic-only system using Claude via the Agent SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from er.logging import get_logger

logger = get_logger(__name__)


# Cost per million tokens (as of January 2026)
# Format: (input_cost_per_million, output_cost_per_million)
# Source: Anthropic Pricing docs
MODEL_COSTS: dict[str, tuple[float, float]] = {
    # Anthropic Claude 4.5
    "claude-opus-4-5-20251101": (15.00, 75.00),
    "claude-opus-4.5": (15.00, 75.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-sonnet-4.5": (3.00, 15.00),
    # Anthropic Claude 4 (Sonnet 4 and Opus 4)
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    # Anthropic legacy
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
}


def get_model_cost(model: str) -> tuple[float, float]:
    """Get cost per million tokens for a model.

    Args:
        model: Model name/ID.

    Returns:
        Tuple of (input_cost_per_million, output_cost_per_million).
    """
    # Try exact match
    if model in MODEL_COSTS:
        return MODEL_COSTS[model]

    # Try prefix match
    for key, costs in MODEL_COSTS.items():
        if model.startswith(key) or key.startswith(model):
            return costs

    # Default to moderate cost estimate
    logger.warning("Unknown model cost, using default", model=model)
    return (2.00, 10.00)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate cost for token usage.

    Args:
        model: Model name/ID.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Cost in USD.
    """
    input_cost_per_m, output_cost_per_m = get_model_cost(model)

    input_cost = (input_tokens / 1_000_000) * input_cost_per_m
    output_cost = (output_tokens / 1_000_000) * output_cost_per_m

    return input_cost + output_cost


@dataclass
class UsageRecord:
    """Record of a single LLM call usage."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    agent: str
    phase: str


@dataclass
class BudgetTracker:
    """Tracks token usage and costs across the run.

    Tracks by:
    - Provider (anthropic)
    - Agent
    - Phase
    - Model
    """

    budget_limit: float
    output_dir: Path | None = None

    # Usage tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    # Breakdown tracking
    by_provider: dict[str, float] = field(default_factory=dict)
    by_agent: dict[str, float] = field(default_factory=dict)
    by_phase: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)

    # Detailed records
    records: list[UsageRecord] = field(default_factory=list)

    def record_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent: str,
        phase: str,
    ) -> float:
        """Record token usage and calculate cost.

        Args:
            provider: LLM provider (anthropic).
            model: Model name/ID (e.g., claude-opus-4-5-20251101).
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            agent: Agent name that made the call.
            phase: Current phase.

        Returns:
            Cost in USD for this call.
        """
        cost = calculate_cost(model, input_tokens, output_tokens)

        # Update totals
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost

        # Update breakdowns
        self.by_provider[provider] = self.by_provider.get(provider, 0.0) + cost
        self.by_agent[agent] = self.by_agent.get(agent, 0.0) + cost
        self.by_phase[phase] = self.by_phase.get(phase, 0.0) + cost
        self.by_model[model] = self.by_model.get(model, 0.0) + cost

        # Store record
        self.records.append(
            UsageRecord(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                agent=agent,
                phase=phase,
            )
        )

        logger.debug(
            "Recorded usage",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=f"${cost:.4f}",
            total=f"${self.total_cost_usd:.4f}",
        )

        # Save to file if output_dir set
        if self.output_dir:
            self._save()

        return cost

    def get_remaining(self) -> float:
        """Get remaining budget.

        Returns:
            Remaining budget in USD.
        """
        return self.budget_limit - self.total_cost_usd

    def get_breakdown(self) -> dict[str, Any]:
        """Get cost breakdown.

        Returns:
            Dict with per-agent, per-phase, per-provider, per-model costs.
        """
        return {
            "total_cost_usd": self.total_cost_usd,
            "budget_limit": self.budget_limit,
            "remaining": self.get_remaining(),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "by_provider": dict(self.by_provider),
            "by_agent": dict(self.by_agent),
            "by_phase": dict(self.by_phase),
            "by_model": dict(self.by_model),
        }

    def is_exceeded(self) -> bool:
        """Check if budget is exceeded.

        Returns:
            True if exceeded, False otherwise.
        """
        return self.total_cost_usd > self.budget_limit

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON.

        Returns:
            Dict representation.
        """
        return {
            "budget_limit": self.budget_limit,
            "total_cost_usd": self.total_cost_usd,
            "remaining": self.get_remaining(),
            "exceeded": self.is_exceeded(),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "by_provider": dict(self.by_provider),
            "by_agent": dict(self.by_agent),
            "by_phase": dict(self.by_phase),
            "by_model": dict(self.by_model),
            "records": [
                {
                    "provider": r.provider,
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "cost_usd": r.cost_usd,
                    "agent": r.agent,
                    "phase": r.phase,
                }
                for r in self.records
            ],
        }

    def _save(self) -> None:
        """Save costs to file."""
        if not self.output_dir:
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        costs_path = self.output_dir / "costs.json"

        with open(costs_path, "wb") as f:
            f.write(orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetTracker:
        """Load from dict.

        Args:
            data: Dict representation.

        Returns:
            BudgetTracker instance.
        """
        tracker = cls(budget_limit=data["budget_limit"])
        tracker.total_cost_usd = data.get("total_cost_usd", 0.0)
        tracker.total_input_tokens = data.get("total_input_tokens", 0)
        tracker.total_output_tokens = data.get("total_output_tokens", 0)
        tracker.by_provider = data.get("by_provider", {})
        tracker.by_agent = data.get("by_agent", {})
        tracker.by_phase = data.get("by_phase", {})
        tracker.by_model = data.get("by_model", {})

        for r in data.get("records", []):
            tracker.records.append(
                UsageRecord(
                    provider=r["provider"],
                    model=r["model"],
                    input_tokens=r["input_tokens"],
                    output_tokens=r["output_tokens"],
                    cost_usd=r["cost_usd"],
                    agent=r["agent"],
                    phase=r["phase"],
                )
            )

        return tracker
