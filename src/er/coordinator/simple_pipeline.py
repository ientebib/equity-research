"""
Simplified 3-Stage Research Pipeline.

This is the pipeline that ACTUALLY WORKS:
1. DATA: Fetch financials, build CompanyContext
2. RESEARCH: Anthropic deep research with real citations
3. SYNTHESIS: Generate report with valuation

No over-engineering. No broken handoffs. Just works.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic

from er.config import Settings, get_settings
from er.data.fmp_client import FMPClient
from er.evidence.store import EvidenceStore
from er.logging import get_logger, setup_logging
from er.retrieval.anthropic_research import AnthropicResearcher, ResearchResult
from er.types import CompanyContext, SourceTier, ToSRisk
from er.valuation.assumption_builder import AssumptionBuilder
from er.valuation.dcf import DCFEngine

logger = get_logger(__name__)


@dataclass
class SimpleConfig:
    """Configuration for simple pipeline."""
    output_dir: Path
    max_searches_per_vertical: int = 5
    verticals: list[str] = field(default_factory=lambda: [
        "Business Model & Revenue Drivers",
        "Competitive Landscape",
        "Growth Catalysts & Risks",
        "Recent Developments (last 90 days)",
        "Management & Capital Allocation",
    ])


@dataclass
class ResearchBundle:
    """Output of Stage 2: Research."""
    ticker: str
    verticals: dict[str, ResearchResult]  # vertical_name -> research
    all_evidence_ids: list[str]
    total_citations: int
    total_searches: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize for checkpoint."""
        return {
            "ticker": self.ticker,
            "verticals": {
                name: {
                    "content": r.content,
                    "evidence_ids": r.evidence_ids,
                    "citation_count": len(r.citations),
                    "citations": [
                        {"url": c.url, "title": c.title, "cited_text": c.cited_text}
                        for c in r.citations
                    ],
                }
                for name, r in self.verticals.items()
            },
            "all_evidence_ids": self.all_evidence_ids,
            "total_citations": self.total_citations,
            "total_searches": self.total_searches,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SynthesisResult:
    """Output of Stage 3: Synthesis."""
    ticker: str
    executive_summary: str
    thesis: str
    bull_case: str
    bear_case: str
    key_metrics: dict[str, Any]
    risks: list[str]
    catalysts: list[str]
    evidence_ids: list[str]
    valuation_summary: str | None = None
    intrinsic_value: float | None = None
    current_price: float | None = None
    upside_downside: float | None = None


@dataclass
class PipelineResult:
    """Final output of the pipeline."""
    ticker: str
    company_context: CompanyContext
    research_bundle: ResearchBundle
    synthesis: SynthesisResult
    report_markdown: str
    output_dir: Path
    started_at: datetime
    completed_at: datetime
    total_cost_usd: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()


class SimplePipeline:
    """The pipeline that actually works.

    3 stages:
    1. DATA - Fetch FMP data, build CompanyContext
    2. RESEARCH - Anthropic deep research with citations
    3. SYNTHESIS - Generate report with valuation
    """

    def __init__(
        self,
        settings: Settings | None = None,
        config: SimpleConfig | None = None,
        progress_callback: Callable[[str, str, float], None] | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            settings: Application settings.
            config: Pipeline configuration.
            progress_callback: Optional callback(stage, message, progress).
        """
        self.settings = settings or get_settings()
        self.config = config or SimpleConfig(output_dir=Path("output"))
        self.progress_callback = progress_callback

        # Initialize clients (evidence_store and fmp_client initialized in run())
        self.anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or self.settings.ANTHROPIC_API_KEY)
        self.evidence_store: EvidenceStore | None = None
        self.fmp_client: FMPClient | None = None
        self.researcher: AnthropicResearcher | None = None

    def _progress(self, stage: str, message: str, progress: float = 0.0) -> None:
        """Report progress."""
        logger.info(f"[{stage}] {message}")
        if self.progress_callback:
            self.progress_callback(stage, message, progress)

    async def run(self, ticker: str) -> PipelineResult:
        """Run the complete pipeline.

        Args:
            ticker: Stock ticker to analyze.

        Returns:
            PipelineResult with all outputs.
        """
        started_at = datetime.now(timezone.utc)
        ticker = ticker.upper().strip()

        # Setup output directory
        run_id = f"run_{ticker}_{started_at.strftime('%Y%m%d_%H%M%S')}"
        output_dir = self.config.output_dir / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        self._progress("INIT", f"Starting analysis for {ticker}", 0.0)

        # Initialize evidence store
        db_path = output_dir / "evidence.db"
        self.evidence_store = EvidenceStore(db_path)
        await self.evidence_store.init()

        # Initialize FMP client with evidence store
        self.fmp_client = FMPClient(
            evidence_store=self.evidence_store,
            api_key=self.settings.FMP_API_KEY,
        )

        # Initialize researcher with evidence store
        import os
        self.researcher = AnthropicResearcher(
            evidence_store=self.evidence_store,
            max_searches=self.config.max_searches_per_vertical,
            api_key=os.environ.get("ANTHROPIC_API_KEY") or self.settings.ANTHROPIC_API_KEY,
        )

        try:
            # Stage 1: DATA
            self._progress("DATA", "Fetching financial data...", 0.1)
            company_context = await self._stage_data(ticker, output_dir)
            self._progress("DATA", "Financial data complete", 0.3)

            # Stage 2: RESEARCH
            self._progress("RESEARCH", "Starting deep research...", 0.35)
            research_bundle = await self._stage_research(ticker, company_context, output_dir)
            self._progress("RESEARCH", f"Research complete: {research_bundle.total_citations} citations", 0.7)

            # Stage 3: SYNTHESIS
            self._progress("SYNTHESIS", "Synthesizing research...", 0.75)
            synthesis = await self._stage_synthesis(ticker, company_context, research_bundle, output_dir)
            self._progress("SYNTHESIS", "Synthesis complete", 0.9)

            # Generate final report
            self._progress("REPORT", "Generating report...", 0.95)
            report_markdown = self._generate_report(ticker, company_context, research_bundle, synthesis)

            # Save report
            report_path = output_dir / "report.md"
            report_path.write_text(report_markdown)

            completed_at = datetime.now(timezone.utc)

            result = PipelineResult(
                ticker=ticker,
                company_context=company_context,
                research_bundle=research_bundle,
                synthesis=synthesis,
                report_markdown=report_markdown,
                output_dir=output_dir,
                started_at=started_at,
                completed_at=completed_at,
            )

            self._progress("COMPLETE", f"Analysis complete in {result.duration_seconds:.0f}s", 1.0)

            return result

        finally:
            if self.fmp_client:
                await self.fmp_client.close()
            if self.evidence_store:
                await self.evidence_store.close()

    async def _stage_data(self, ticker: str, output_dir: Path) -> CompanyContext:
        """Stage 1: Fetch financial data and build CompanyContext."""

        # Use FMP's full context method which fetches everything
        context_data = await self.fmp_client.get_full_context(ticker)

        # Extract data from context
        profile = context_data.get("profile", {})
        evidence_ids = context_data.get("evidence_ids", [])

        # Build CompanyContext
        from datetime import datetime, timezone as tz
        company_context = CompanyContext(
            symbol=ticker,
            fetched_at=datetime.now(tz.utc),
            profile=profile,
            income_statement_annual=context_data.get("income_statement_annual", []),
            balance_sheet_annual=context_data.get("balance_sheet_annual", []),
            cash_flow_annual=context_data.get("cash_flow_annual", []),
            analyst_estimates=context_data.get("analyst_estimates", []),
            quant_metrics=context_data.get("quant_metrics", {}),
            market_data=context_data.get("market_data", {}),
            evidence_ids=evidence_ids,
        )

        # Save checkpoint
        checkpoint_path = output_dir / "stage1_data.json"
        checkpoint_path.write_text(json.dumps({
            "ticker": ticker,
            "company_name": company_context.company_name,
            "profile": profile,
            "evidence_ids": evidence_ids,
        }, indent=2, default=str))

        logger.info(
            "Stage 1 complete",
            ticker=ticker,
            company_name=company_context.company_name,
            evidence_ids=len(evidence_ids),
        )

        return company_context

    async def _stage_research(
        self,
        ticker: str,
        company_context: CompanyContext,
        output_dir: Path,
    ) -> ResearchBundle:
        """Stage 2: Deep research using Anthropic."""

        # Build context for research
        context = f"""
Company: {company_context.company_name} ({ticker})
Sector: {company_context.profile.get('sector', 'Unknown') if company_context.profile else 'Unknown'}
Industry: {company_context.profile.get('industry', 'Unknown') if company_context.profile else 'Unknown'}
Market Cap: ${company_context.profile.get('mktCap', 0) / 1e9:.1f}B
"""

        # Research all verticals
        verticals: dict[str, ResearchResult] = {}
        all_evidence_ids: list[str] = []
        total_citations = 0
        total_searches = 0

        for i, vertical in enumerate(self.config.verticals):
            self._progress(
                "RESEARCH",
                f"Researching: {vertical}",
                0.35 + (i / len(self.config.verticals)) * 0.3,
            )

            try:
                result = await self.researcher.research_vertical(
                    ticker=ticker,
                    vertical=vertical,
                    context=context,
                    recency_days=90 if "recent" in vertical.lower() else None,
                )

                verticals[vertical] = result
                all_evidence_ids.extend(result.evidence_ids)
                total_citations += len(result.citations)
                total_searches += result.search_count

                logger.info(
                    f"Vertical complete: {vertical}",
                    citations=len(result.citations),
                    evidence_ids=len(result.evidence_ids),
                )

            except Exception as e:
                logger.error(f"Research failed for {vertical}: {e}")
                # Continue with other verticals

        bundle = ResearchBundle(
            ticker=ticker,
            verticals=verticals,
            all_evidence_ids=list(set(all_evidence_ids)),  # Dedupe
            total_citations=total_citations,
            total_searches=total_searches,
        )

        # Save checkpoint
        checkpoint_path = output_dir / "stage2_research.json"
        checkpoint_path.write_text(json.dumps(bundle.to_dict(), indent=2))

        logger.info(
            "Stage 2 complete",
            ticker=ticker,
            verticals=len(verticals),
            total_citations=total_citations,
            evidence_ids=len(bundle.all_evidence_ids),
        )

        return bundle

    async def _stage_synthesis(
        self,
        ticker: str,
        company_context: CompanyContext,
        research_bundle: ResearchBundle,
        output_dir: Path,
    ) -> SynthesisResult:
        """Stage 3: Synthesize research into investment thesis."""

        # Compile all research content
        research_content = ""
        for vertical, result in research_bundle.verticals.items():
            research_content += f"\n## {vertical}\n\n{result.content}\n"

        # Build synthesis prompt
        prompt = f"""You are a senior equity research analyst synthesizing research on {ticker} ({company_context.company_name}).

Based on the following research, provide:
1. Executive Summary (2-3 paragraphs)
2. Investment Thesis (bull case)
3. Bull Case (key drivers)
4. Bear Case (key risks)
5. Key Metrics to watch
6. Top 3 Risks
7. Top 3 Catalysts

Be specific and cite evidence from the research. Format as JSON.

---
RESEARCH:
{research_content}
---

Output JSON format:
{{
    "executive_summary": "...",
    "thesis": "...",
    "bull_case": "...",
    "bear_case": "...",
    "key_metrics": {{"metric_name": "value"}},
    "risks": ["risk1", "risk2", "risk3"],
    "catalysts": ["catalyst1", "catalyst2", "catalyst3"]
}}"""

        # Call Claude for synthesis
        response = self.anthropic.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        response_text = response.content[0].text

        # Extract JSON from response
        try:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                synthesis_data = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse synthesis JSON: {e}")
            synthesis_data = {
                "executive_summary": response_text,
                "thesis": "",
                "bull_case": "",
                "bear_case": "",
                "key_metrics": {},
                "risks": [],
                "catalysts": [],
            }

        # Run valuation
        valuation_summary = None
        intrinsic_value = None
        current_price = company_context.quote.get("price") if company_context.quote else None

        try:
            assumption_builder = AssumptionBuilder()
            dcf_inputs = assumption_builder.build_dcf_inputs(company_context)

            dcf_engine = DCFEngine()
            dcf_result = dcf_engine.run(dcf_inputs)

            intrinsic_value = dcf_result.intrinsic_value_per_share
            valuation_summary = f"DCF Value: ${intrinsic_value:.2f} | WACC: {dcf_inputs.wacc:.1%} | Terminal Growth: {dcf_inputs.terminal_growth:.1%}"

        except Exception as e:
            logger.warning(f"Valuation failed: {e}")
            valuation_summary = f"Valuation unavailable: {e}"

        # Calculate upside/downside
        upside_downside = None
        if intrinsic_value and current_price:
            upside_downside = (intrinsic_value - current_price) / current_price

        synthesis = SynthesisResult(
            ticker=ticker,
            executive_summary=synthesis_data.get("executive_summary", ""),
            thesis=synthesis_data.get("thesis", ""),
            bull_case=synthesis_data.get("bull_case", ""),
            bear_case=synthesis_data.get("bear_case", ""),
            key_metrics=synthesis_data.get("key_metrics", {}),
            risks=synthesis_data.get("risks", []),
            catalysts=synthesis_data.get("catalysts", []),
            evidence_ids=research_bundle.all_evidence_ids,
            valuation_summary=valuation_summary,
            intrinsic_value=intrinsic_value,
            current_price=current_price,
            upside_downside=upside_downside,
        )

        # Save checkpoint
        checkpoint_path = output_dir / "stage3_synthesis.json"
        checkpoint_path.write_text(json.dumps({
            "executive_summary": synthesis.executive_summary,
            "thesis": synthesis.thesis,
            "bull_case": synthesis.bull_case,
            "bear_case": synthesis.bear_case,
            "key_metrics": synthesis.key_metrics,
            "risks": synthesis.risks,
            "catalysts": synthesis.catalysts,
            "valuation_summary": synthesis.valuation_summary,
            "intrinsic_value": synthesis.intrinsic_value,
            "current_price": synthesis.current_price,
            "upside_downside": synthesis.upside_downside,
        }, indent=2))

        logger.info("Stage 3 complete", ticker=ticker)

        return synthesis

    def _generate_report(
        self,
        ticker: str,
        company_context: CompanyContext,
        research_bundle: ResearchBundle,
        synthesis: SynthesisResult,
    ) -> str:
        """Generate final Markdown report."""

        # Build citations section
        citations_md = "\n## Sources\n\n"
        citation_num = 1
        for vertical, result in research_bundle.verticals.items():
            for cite in result.citations:
                citations_md += f"{citation_num}. [{cite.title}]({cite.url})\n"
                citation_num += 1

        # Build report
        report = f"""# {company_context.company_name} ({ticker}) - Equity Research Report

*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*

---

## Executive Summary

{synthesis.executive_summary}

---

## Investment Thesis

{synthesis.thesis}

---

## Bull Case

{synthesis.bull_case}

---

## Bear Case

{synthesis.bear_case}

---

## Key Metrics

| Metric | Value |
|--------|-------|
"""
        for metric, value in synthesis.key_metrics.items():
            report += f"| {metric} | {value} |\n"

        report += f"""
---

## Valuation

{synthesis.valuation_summary or 'N/A'}

| Metric | Value |
|--------|-------|
| Current Price | ${synthesis.current_price:.2f if synthesis.current_price else 'N/A'} |
| Intrinsic Value | ${synthesis.intrinsic_value:.2f if synthesis.intrinsic_value else 'N/A'} |
| Upside/Downside | {synthesis.upside_downside:.1%} if synthesis.upside_downside else 'N/A' |

---

## Risks

"""
        for i, risk in enumerate(synthesis.risks, 1):
            report += f"{i}. {risk}\n"

        report += "\n---\n\n## Catalysts\n\n"
        for i, catalyst in enumerate(synthesis.catalysts, 1):
            report += f"{i}. {catalyst}\n"

        report += f"""
---

## Research Details

"""
        for vertical, result in research_bundle.verticals.items():
            report += f"### {vertical}\n\n{result.content}\n\n"

        report += citations_md

        report += f"""
---

*Research conducted using {research_bundle.total_searches} web searches across {len(research_bundle.verticals)} research verticals.*
*{research_bundle.total_citations} sources cited.*
*Evidence IDs: {len(research_bundle.all_evidence_ids)} stored in evidence database.*
"""

        return report


async def run_simple_pipeline(ticker: str, output_dir: Path | None = None) -> PipelineResult:
    """Convenience function to run the simple pipeline.

    Args:
        ticker: Stock ticker to analyze.
        output_dir: Output directory (default: ./output).

    Returns:
        PipelineResult with all outputs.
    """
    config = SimpleConfig(output_dir=output_dir or Path("output"))
    pipeline = SimplePipeline(config=config)
    return await pipeline.run(ticker)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m er.coordinator.simple_pipeline TICKER")
        sys.exit(1)

    ticker = sys.argv[1].upper()

    setup_logging(log_level="INFO")

    result = asyncio.run(run_simple_pipeline(ticker))

    print(f"\n{'='*60}")
    print(f"Analysis complete for {ticker}")
    print(f"Report: {result.output_dir / 'report.md'}")
    print(f"Duration: {result.duration_seconds:.0f}s")
    print(f"Citations: {result.research_bundle.total_citations}")
    print(f"Evidence IDs: {len(result.research_bundle.all_evidence_ids)}")
    print(f"{'='*60}")
