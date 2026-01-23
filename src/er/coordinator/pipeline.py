"""
DEPRECATED: Legacy 6-Stage Pipeline Coordinator.

This file has been deprecated as part of the Anthropic-only migration.
All multi-provider (OpenAI, Gemini) code has been removed from this codebase.

Use the following instead:
- For CLI: Use the --simple flag with `er analyze TICKER --simple`
- For programmatic use: Use AnthropicSDKPipeline from anthropic_sdk_agent.py

Example:
    from er.coordinator.anthropic_sdk_agent import AnthropicSDKPipeline

    async def run_research(ticker: str):
        pipeline = AnthropicSDKPipeline()
        result = await pipeline.run(ticker)
        return result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


class ProgressCallback(Protocol):
    """Protocol for progress callbacks."""

    def __call__(
        self,
        stage: int,
        stage_name: str,
        status: str,
        detail: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """Called when pipeline progress changes."""
        ...


@dataclass
class PipelineConfig:
    """Configuration for the research pipeline.

    DEPRECATED: This class is kept for backwards compatibility.
    Use AnthropicSDKPipeline from anthropic_sdk_agent.py instead.
    """
    output_dir: Path = field(default_factory=lambda: Path("output"))
    resume_from_run_dir: Path | None = None
    max_budget_usd: float = 50.0
    include_transcripts: bool = False
    num_transcript_quarters: int = 4
    use_web_search_discovery: bool = True
    use_deep_research_verticals: bool = True
    max_parallel_verticals: int = 5
    manual_transcripts: list[dict[str, Any]] | None = None
    pause_after_stage: int | None = None
    external_discovery_overrides: dict[str, list[str]] | None = None


class ResearchPipeline:
    """DEPRECATED: Multi-provider research pipeline.

    This pipeline has been deprecated. The codebase is now Anthropic-only.

    Migration guide:
    - For CLI usage: Use `er analyze TICKER --simple`
    - For programmatic usage: Use AnthropicSDKPipeline from anthropic_sdk_agent.py

    Example:
        from er.coordinator.anthropic_sdk_agent import AnthropicSDKPipeline

        pipeline = AnthropicSDKPipeline()
        result = await pipeline.run("GOOGL")
    """

    def __init__(
        self,
        settings: Any = None,
        config: PipelineConfig | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize the deprecated pipeline.

        Raises:
            NotImplementedError: Always raised - this pipeline is deprecated.
        """
        raise NotImplementedError(
            "ResearchPipeline is deprecated. "
            "The codebase has been migrated to Anthropic-only operation.\n\n"
            "For CLI usage:\n"
            "  er analyze TICKER --simple\n\n"
            "For programmatic usage:\n"
            "  from er.coordinator.anthropic_sdk_agent import AnthropicSDKPipeline\n"
            "  pipeline = AnthropicSDKPipeline()\n"
            "  result = await pipeline.run('GOOGL')"
        )

    async def run(self, ticker: str) -> Any:
        """Run the pipeline (deprecated).

        Raises:
            NotImplementedError: Always raised - this pipeline is deprecated.
        """
        raise NotImplementedError("ResearchPipeline is deprecated.")

    @property
    def budget_tracker(self) -> Any:
        """Get budget tracker (deprecated)."""
        raise NotImplementedError("ResearchPipeline is deprecated.")
