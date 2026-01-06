"""
Token Flow Observability Dashboard.

Tracks and visualizes what tokens flow between pipeline stages:
- What context each agent receives (input breakdown)
- What each agent produces (output breakdown)
- How outputs cascade to downstream agents
- Time and cost per stage
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from er.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ContextComponent:
    """A component of context passed to an agent."""
    name: str
    tokens: int
    source: str  # "fmp", "discovery", "user", "prompt_template", etc.
    description: str = ""


@dataclass
class AgentCall:
    """Record of a single agent LLM call with full context breakdown."""

    # Identity
    agent: str
    stage: int
    phase: str
    model: str
    provider: str

    # Timing
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # Input breakdown
    input_tokens: int = 0
    input_components: list[ContextComponent] = field(default_factory=list)

    # Output
    output_tokens: int = 0
    output_description: str = ""

    # Cost
    cost_usd: float = 0.0

    # Status
    status: str = "running"  # "running", "completed", "failed", "timeout"
    error: str | None = None

    def add_input_component(self, name: str, tokens: int, source: str, description: str = "") -> None:
        """Add a context component to input breakdown."""
        self.input_components.append(ContextComponent(
            name=name,
            tokens=tokens,
            source=source,
            description=description,
        ))

    def complete(self, output_tokens: int, cost: float, description: str = "") -> None:
        """Mark call as completed."""
        self.completed_at = datetime.now()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.output_tokens = output_tokens
        self.cost_usd = cost
        self.output_description = description
        self.status = "completed"

    def fail(self, error: str) -> None:
        """Mark call as failed."""
        self.completed_at = datetime.now()
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.status = "failed"
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "agent": self.agent,
            "stage": self.stage,
            "phase": self.phase,
            "model": self.model,
            "provider": self.provider,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "input_tokens": self.input_tokens,
            "input_components": [
                {"name": c.name, "tokens": c.tokens, "source": c.source, "description": c.description}
                for c in self.input_components
            ],
            "output_tokens": self.output_tokens,
            "output_description": self.output_description,
            "cost_usd": self.cost_usd,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class TokenFlowTracker:
    """Tracks token flow across entire pipeline."""

    run_id: str
    ticker: str
    output_dir: Path | None = None

    # All agent calls in order
    calls: list[AgentCall] = field(default_factory=list)

    # Current call being tracked
    _current_call: AgentCall | None = None

    def start_call(
        self,
        agent: str,
        stage: int,
        phase: str,
        model: str,
        provider: str,
    ) -> AgentCall:
        """Start tracking a new agent call."""
        call = AgentCall(
            agent=agent,
            stage=stage,
            phase=phase,
            model=model,
            provider=provider,
            started_at=datetime.now(),
        )
        self._current_call = call
        self.calls.append(call)
        return call

    def add_context_component(
        self,
        name: str,
        tokens: int,
        source: str,
        description: str = "",
    ) -> None:
        """Add a context component to current call."""
        if self._current_call:
            self._current_call.add_input_component(name, tokens, source, description)
            self._current_call.input_tokens += tokens

    def complete_call(self, output_tokens: int, cost: float, description: str = "") -> None:
        """Complete the current call."""
        if self._current_call:
            self._current_call.complete(output_tokens, cost, description)
            self._current_call = None
            self._save()

    def fail_call(self, error: str) -> None:
        """Mark current call as failed."""
        if self._current_call:
            self._current_call.fail(error)
            self._current_call = None
            self._save()

    def get_stage_summary(self) -> list[dict[str, Any]]:
        """Get summary by stage."""
        stages: dict[int, dict[str, Any]] = {}

        for call in self.calls:
            if call.stage not in stages:
                stages[call.stage] = {
                    "stage": call.stage,
                    "agents": [],
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost_usd": 0.0,
                    "total_duration_seconds": 0.0,
                }

            s = stages[call.stage]
            s["agents"].append(call.agent)
            s["total_input_tokens"] += call.input_tokens
            s["total_output_tokens"] += call.output_tokens
            s["total_cost_usd"] += call.cost_usd
            s["total_duration_seconds"] += call.duration_seconds

        return sorted(stages.values(), key=lambda x: x["stage"])

    def get_flow_diagram(self) -> str:
        """Generate ASCII flow diagram of token flow."""
        lines = []
        lines.append(f"\n{'='*80}")
        lines.append(f"TOKEN FLOW DIAGRAM - {self.ticker} ({self.run_id})")
        lines.append(f"{'='*80}\n")

        current_stage = -1
        for call in self.calls:
            if call.stage != current_stage:
                current_stage = call.stage
                lines.append(f"\n--- STAGE {current_stage}: {call.phase.upper()} ---\n")

            # Agent box
            status_icon = {"completed": "✓", "failed": "✗", "timeout": "⏱", "running": "..."}
            icon = status_icon.get(call.status, "?")

            lines.append(f"┌─ {call.agent} ({call.model}) [{icon}]")
            lines.append(f"│  Duration: {call.duration_seconds:.1f}s | Cost: ${call.cost_usd:.4f}")
            lines.append(f"│")
            lines.append(f"│  INPUT ({call.input_tokens:,} tokens):")

            for comp in call.input_components:
                lines.append(f"│    • {comp.name}: {comp.tokens:,} tokens ({comp.source})")
                if comp.description:
                    lines.append(f"│      └─ {comp.description[:60]}...")

            lines.append(f"│")
            lines.append(f"│  OUTPUT ({call.output_tokens:,} tokens):")
            if call.output_description:
                lines.append(f"│    └─ {call.output_description[:70]}...")

            if call.error:
                lines.append(f"│")
                lines.append(f"│  ERROR: {call.error[:60]}...")

            lines.append(f"└{'─'*50}")
            lines.append("")

        # Summary
        lines.append(f"\n{'='*80}")
        lines.append("SUMMARY")
        lines.append(f"{'='*80}\n")

        total_input = sum(c.input_tokens for c in self.calls)
        total_output = sum(c.output_tokens for c in self.calls)
        total_cost = sum(c.cost_usd for c in self.calls)
        total_time = sum(c.duration_seconds for c in self.calls)

        lines.append(f"Total Input Tokens:  {total_input:>12,}")
        lines.append(f"Total Output Tokens: {total_output:>12,}")
        lines.append(f"Total Cost:          ${total_cost:>11.4f}")
        lines.append(f"Total Time:          {total_time:>11.1f}s")
        lines.append("")

        # Per-stage breakdown
        lines.append("Per-Stage Breakdown:")
        lines.append(f"{'Stage':<8} {'Input':>12} {'Output':>12} {'Cost':>12} {'Time':>10}")
        lines.append("-" * 60)

        for stage in self.get_stage_summary():
            lines.append(
                f"Stage {stage['stage']:<2} "
                f"{stage['total_input_tokens']:>12,} "
                f"{stage['total_output_tokens']:>12,} "
                f"${stage['total_cost_usd']:>10.4f} "
                f"{stage['total_duration_seconds']:>9.1f}s"
            )

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "run_id": self.run_id,
            "ticker": self.ticker,
            "calls": [c.to_dict() for c in self.calls],
            "summary": {
                "total_calls": len(self.calls),
                "total_input_tokens": sum(c.input_tokens for c in self.calls),
                "total_output_tokens": sum(c.output_tokens for c in self.calls),
                "total_cost_usd": sum(c.cost_usd for c in self.calls),
                "total_duration_seconds": sum(c.duration_seconds for c in self.calls),
                "stages": self.get_stage_summary(),
            },
        }

    def _save(self) -> None:
        """Save to file."""
        if not self.output_dir:
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "token_flow.json"

        with open(path, "wb") as f:
            f.write(orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2))

    def print_dashboard(self) -> None:
        """Print the flow diagram to console."""
        print(self.get_flow_diagram())


def count_tokens_approx(text: str) -> int:
    """Approximate token count (1 token ≈ 4 chars for English text)."""
    return len(text) // 4


def analyze_run_directory(run_dir: Path) -> TokenFlowTracker | None:
    """Analyze a completed run directory and build token flow."""

    # Load costs.json for actual token counts
    costs_path = run_dir / "costs.json"
    if not costs_path.exists():
        logger.warning(f"No costs.json found in {run_dir}")
        return None

    with open(costs_path) as f:
        costs = json.load(f)

    # Load manifest for run info
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
        ticker = manifest.get("ticker", "UNKNOWN")
        run_id = manifest.get("run_id", run_dir.name)
    else:
        ticker = "UNKNOWN"
        run_id = run_dir.name

    tracker = TokenFlowTracker(
        run_id=run_id,
        ticker=ticker,
        output_dir=run_dir,
    )

    # Convert cost records to AgentCalls
    stage_map = {
        "data_collection": 1,
        "discovery": 2,
        "external_discovery": 2,
        "deep_research": 3,
        "synthesis": 4,
        "claude_synthesis": 4,
        "gpt_synthesis": 4,
        "judge_editorial": 5,
        "revision": 6,
        "resynthesis": 6,
    }

    for record in costs.get("records", []):
        stage = stage_map.get(record["phase"], 0)

        call = tracker.start_call(
            agent=record["agent"],
            stage=stage,
            phase=record["phase"],
            model=record["model"],
            provider=record["provider"],
        )

        # Add input as single component (we don't have breakdown in basic costs.json)
        call.add_input_component(
            name="prompt",
            tokens=record["input_tokens"],
            source="context",
            description="Full prompt (breakdown not available in costs.json)",
        )
        call.input_tokens = record["input_tokens"]

        call.complete(
            output_tokens=record["output_tokens"],
            cost=record["cost_usd"],
            description=f"Output from {record['agent']}",
        )

    return tracker


# CLI for analyzing runs
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m er.observability.token_flow <run_directory>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Directory not found: {run_dir}")
        sys.exit(1)

    tracker = analyze_run_directory(run_dir)
    if tracker:
        tracker.print_dashboard()
    else:
        print("Could not analyze run directory")
