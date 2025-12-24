"""
5-Stage Pipeline Coordinator.

Orchestrates the complete equity research pipeline:
1. Data Orchestrator - Fetch FMP data, build CompanyContext
2. Discovery - Find value drivers with 7 lenses (Gemini Deep Research)
3. Vertical Analysis - Deep dive per vertical (o4-mini-deep-research, parallel)
4. Dual Synthesis - Claude + GPT synthesize in parallel
5. Final Judge - Compare, verify, produce final report
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from er.agents.base import AgentContext
from er.agents.data_orchestrator import DataOrchestratorAgent
from er.agents.discovery import DiscoveryAgent
from er.agents.judge import JudgeAgent
from er.agents.synthesizer import SynthesizerAgent
from er.agents.vertical_analyst import VerticalAnalystAgent
from er.budget import BudgetTracker
from er.config import Settings
from er.evidence.store import EvidenceStore
from er.llm.router import LLMRouter
from er.logging import get_logger
from er.types import (
    CompanyContext,
    DiscoveryOutput,
    JudgeVerdict,
    Phase,
    RunState,
    SynthesisOutput,
    VerticalAnalysis,
)

logger = get_logger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the research pipeline."""

    # Stage 1: Data
    include_transcripts: bool = True
    num_transcript_quarters: int = 4

    # Stage 2: Discovery
    use_deep_research_discovery: bool = True

    # Stage 3: Verticals
    max_parallel_verticals: int = 5
    use_deep_research_verticals: bool = True
    max_verticals: int | None = None  # None = use all discovered

    # Stage 4 & 5: Synthesis & Judge
    # (no config needed - always uses extended thinking)

    # Budget
    max_budget_usd: float | None = None  # None = no limit


@dataclass
class PipelineResult:
    """Complete result from the pipeline."""

    ticker: str
    company_name: str

    # Stage outputs
    company_context: CompanyContext
    discovery_output: DiscoveryOutput
    vertical_analyses: list[VerticalAnalysis]
    claude_synthesis: SynthesisOutput
    gpt_synthesis: SynthesisOutput
    final_verdict: JudgeVerdict

    # Run metadata
    run_state: RunState
    total_cost_usd: float
    duration_seconds: float
    started_at: datetime
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_report_markdown(self) -> str:
        """Generate the final equity research report as Markdown."""
        verdict = self.final_verdict
        ctx = self.company_context

        # Format scenarios
        scenario_sections = []
        for name in ["bull", "base", "bear"]:
            if name in self.claude_synthesis.scenarios:
                s = self.claude_synthesis.scenarios[name]
                scenario_sections.append(f"""### {name.title()} Case ({s.probability:.0%} probability)
{s.narrative}

Key Assumptions:
{chr(10).join(f"- {a}" for a in s.key_assumptions)}
""")

        # Format vertical summaries
        vertical_sections = []
        for v in self.vertical_analyses:
            vertical_sections.append(f"""### {v.vertical_name}

**Business Model:**
{v.business_understanding[:500]}...

**Competitive Position:**
{v.competitive_position[:300]}...

**Growth Drivers:** {", ".join(v.growth_drivers[:3])}

**Key Risks:** {", ".join(r.name for r in v.key_risks[:3])}

**Bull Case:** {v.bull_case.thesis[:200]}...

**Bear Case:** {v.bear_case.thesis[:200]}...

**Confidence:** {v.overall_confidence:.0%}
""")

        # Format key debates
        debate_sections = []
        for d in self.claude_synthesis.key_debates[:5]:
            debate_sections.append(f"""#### {d.topic}
- **Bull View:** {d.bull_view}
- **Bear View:** {d.bear_view}
- **Our View:** {d.our_view}
""")

        # Format risks
        risk_lines = [f"1. **{r}**" for r in verdict.key_risks[:5]]

        report = f"""# {self.ticker} Equity Research Report

**Generated:** {self.completed_at.strftime("%Y-%m-%d %H:%M UTC")}
**Investment View:** {verdict.final_investment_view} ({verdict.final_conviction} conviction)
**Confidence:** {verdict.final_confidence:.0%}

---

## Executive Summary

{verdict.final_thesis}

---

## Company Overview

**{ctx.company_name}** ({ctx.symbol})

**Industry:** {ctx.profile.get("industry", "N/A")}
**Sector:** {ctx.profile.get("sector", "N/A")}
**Market Cap:** ${ctx.profile.get("current_market_cap", ctx.profile.get("mktCap", 0)) / 1e9:.1f}B
**Latest Revenue:** ${ctx.latest_revenue / 1e9:.1f}B
**Latest Net Income:** ${ctx.latest_net_income / 1e9:.1f}B

---

## Segment Analysis

{chr(10).join(vertical_sections)}

---

## Investment Thesis

### Scenarios

{chr(10).join(scenario_sections)}

### Key Debates

{chr(10).join(debate_sections) if debate_sections else "No key debates identified."}

---

## Risk Assessment

{chr(10).join(risk_lines)}

---

## Key Catalysts

{chr(10).join(f"- {c}" for c in verdict.key_catalysts)}

---

## Key Uncertainties

{chr(10).join(f"- {u}" for u in verdict.key_uncertainties)}

---

## Analysis Metadata

| Metric | Value |
|--------|-------|
| Total Cost | ${self.total_cost_usd:.2f} |
| Duration | {self.duration_seconds:.0f}s |
| Verticals Analyzed | {len(self.vertical_analyses)} |
| Claude View | {self.claude_synthesis.investment_view} ({self.claude_synthesis.conviction}) |
| GPT View | {self.gpt_synthesis.investment_view} ({self.gpt_synthesis.conviction}) |
| Preferred Synthesis | {verdict.preferred_synthesis} |
| Inconsistencies Found | {len(verdict.inconsistencies)} |

---

*This report was generated by an AI-powered equity research system. All claims should be independently verified.*
"""
        return report


class ResearchPipeline:
    """5-stage equity research pipeline coordinator."""

    def __init__(
        self,
        settings: Settings | None = None,
        config: PipelineConfig | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            settings: Application settings (loads from env if None).
            config: Pipeline configuration.
        """
        self.settings = settings or Settings()
        self.config = config or PipelineConfig()

        # Initialize shared resources
        self.evidence_store = EvidenceStore()
        self.budget_tracker = BudgetTracker(
            max_budget_usd=self.config.max_budget_usd,
        )
        self.llm_router = LLMRouter(settings=self.settings)

        # Create agent context
        self.agent_context = AgentContext(
            settings=self.settings,
            llm_router=self.llm_router,
            evidence_store=self.evidence_store,
            budget_tracker=self.budget_tracker,
        )

        # Initialize agents
        self._data_orchestrator: DataOrchestratorAgent | None = None
        self._discovery_agent: DiscoveryAgent | None = None
        self._synthesizer: SynthesizerAgent | None = None
        self._judge: JudgeAgent | None = None

    async def run(self, ticker: str) -> PipelineResult:
        """Run the complete 5-stage pipeline for a ticker.

        Args:
            ticker: Stock ticker symbol (e.g., "GOOGL").

        Returns:
            PipelineResult with all outputs.

        Raises:
            Exception: If any stage fails.
        """
        started_at = datetime.now(timezone.utc)
        start_time = asyncio.get_event_loop().time()

        logger.info("Starting research pipeline", ticker=ticker)

        # Create run state
        run_state = RunState(
            run_id=f"run_{ticker}_{started_at.strftime('%Y%m%d_%H%M%S')}",
            ticker=ticker,
            phase=Phase.FETCH_DATA,
            started_at=started_at,
        )

        try:
            # ============== STAGE 1: Data Orchestrator ==============
            logger.info("Stage 1: Data Orchestrator", ticker=ticker)
            company_context = await self._run_data_orchestrator(run_state)

            # ============== STAGE 2: Discovery ==============
            logger.info("Stage 2: Discovery", ticker=ticker)
            discovery_output = await self._run_discovery(run_state, company_context)

            # ============== STAGE 3: Vertical Analysis (Parallel) ==============
            logger.info("Stage 3: Vertical Analysis", ticker=ticker)
            vertical_analyses = await self._run_vertical_analysis(
                run_state,
                company_context,
                discovery_output,
            )

            # ============== STAGE 4: Dual Synthesis (Parallel) ==============
            logger.info("Stage 4: Dual Synthesis", ticker=ticker)
            claude_synthesis, gpt_synthesis = await self._run_synthesis(
                run_state,
                company_context,
                discovery_output,
                vertical_analyses,
            )

            # ============== STAGE 5: Final Judge ==============
            logger.info("Stage 5: Final Judge", ticker=ticker)
            final_verdict = await self._run_judge(
                run_state,
                company_context,
                claude_synthesis,
                gpt_synthesis,
            )

            # Calculate totals
            end_time = asyncio.get_event_loop().time()
            duration_seconds = end_time - start_time
            total_cost = self.budget_tracker.total_cost_usd

            run_state.phase = Phase.COMPLETE
            run_state.completed_at = datetime.now(timezone.utc)

            logger.info(
                "Pipeline completed",
                ticker=ticker,
                duration_seconds=duration_seconds,
                total_cost_usd=total_cost,
                final_view=final_verdict.final_investment_view,
            )

            return PipelineResult(
                ticker=ticker,
                company_name=company_context.company_name,
                company_context=company_context,
                discovery_output=discovery_output,
                vertical_analyses=vertical_analyses,
                claude_synthesis=claude_synthesis,
                gpt_synthesis=gpt_synthesis,
                final_verdict=final_verdict,
                run_state=run_state,
                total_cost_usd=total_cost,
                duration_seconds=duration_seconds,
                started_at=started_at,
            )

        except Exception as e:
            logger.error(
                "Pipeline failed",
                ticker=ticker,
                error=str(e),
                phase=run_state.phase.value if run_state.phase else "unknown",
            )
            raise

        finally:
            await self.close()

    async def _run_data_orchestrator(
        self,
        run_state: RunState,
    ) -> CompanyContext:
        """Stage 1: Fetch all data and build CompanyContext."""
        if self._data_orchestrator is None:
            self._data_orchestrator = DataOrchestratorAgent(self.agent_context)

        return await self._data_orchestrator.run(
            run_state,
            include_transcripts=self.config.include_transcripts,
            num_transcript_quarters=self.config.num_transcript_quarters,
        )

    async def _run_discovery(
        self,
        run_state: RunState,
        company_context: CompanyContext,
    ) -> DiscoveryOutput:
        """Stage 2: Discover all value drivers."""
        if self._discovery_agent is None:
            self._discovery_agent = DiscoveryAgent(self.agent_context)

        return await self._discovery_agent.run(
            run_state,
            company_context,
            use_deep_research=self.config.use_deep_research_discovery,
        )

    async def _run_vertical_analysis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
    ) -> list[VerticalAnalysis]:
        """Stage 3: Deep dive per vertical in parallel."""
        # Select threads to analyze
        threads = discovery_output.research_threads
        if self.config.max_verticals:
            threads = threads[: self.config.max_verticals]

        # Sort by priority
        threads = sorted(threads, key=lambda t: t.priority)

        logger.info(
            "Running vertical analyses",
            ticker=run_state.ticker,
            vertical_count=len(threads),
        )

        # Create tasks for parallel execution
        semaphore = asyncio.Semaphore(self.config.max_parallel_verticals)

        async def analyze_vertical(thread):
            async with semaphore:
                agent = VerticalAnalystAgent(self.agent_context)
                try:
                    return await agent.run(
                        run_state,
                        company_context,
                        thread,
                        use_deep_research=self.config.use_deep_research_verticals,
                    )
                finally:
                    await agent.close()

        # Run all in parallel (respecting semaphore limit)
        analyses = await asyncio.gather(
            *[analyze_vertical(t) for t in threads],
            return_exceptions=True,
        )

        # Filter out failures
        results = []
        for i, result in enumerate(analyses):
            if isinstance(result, Exception):
                logger.error(
                    "Vertical analysis failed",
                    vertical=threads[i].name,
                    error=str(result),
                )
            else:
                results.append(result)

        return results

    async def _run_synthesis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
        vertical_analyses: list[VerticalAnalysis],
    ) -> tuple[SynthesisOutput, SynthesisOutput]:
        """Stage 4: Dual synthesis with Claude and GPT."""
        if self._synthesizer is None:
            self._synthesizer = SynthesizerAgent(self.agent_context)

        return await self._synthesizer.run(
            run_state,
            company_context,
            discovery_output,
            vertical_analyses,
        )

    async def _run_judge(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        claude_synthesis: SynthesisOutput,
        gpt_synthesis: SynthesisOutput,
    ) -> JudgeVerdict:
        """Stage 5: Final judgment."""
        if self._judge is None:
            self._judge = JudgeAgent(self.agent_context)

        return await self._judge.run(
            run_state,
            company_context,
            claude_synthesis,
            gpt_synthesis,
        )

    async def close(self) -> None:
        """Close all agents and resources."""
        if self._data_orchestrator:
            await self._data_orchestrator.close()
            self._data_orchestrator = None
        if self._discovery_agent:
            await self._discovery_agent.close()
            self._discovery_agent = None
        if self._synthesizer:
            await self._synthesizer.close()
            self._synthesizer = None
        if self._judge:
            await self._judge.close()
            self._judge = None


async def run_research(
    ticker: str,
    config: PipelineConfig | None = None,
    settings: Settings | None = None,
) -> PipelineResult:
    """Convenience function to run the full pipeline.

    Args:
        ticker: Stock ticker symbol.
        config: Optional pipeline configuration.
        settings: Optional settings (loads from env if None).

    Returns:
        PipelineResult with all outputs.
    """
    pipeline = ResearchPipeline(settings=settings, config=config)
    return await pipeline.run(ticker)
