"""
Equity Research Pipeline using Claude Agent SDK.

This implements Anthropic's multi-agent research architecture:
- Lead orchestrator coordinates specialized subagents
- Parallel research subagents for each thread
- Opus synthesis for final report
- Context isolation per subagent (200K each)

Based on: https://www.anthropic.com/engineering/multi-agent-research-system
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    ResultMessage,
)

from er.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# SYSTEM PROMPTS FOR SUBAGENTS
# =============================================================================

DATA_FETCHER_PROMPT = """You are a financial data specialist.

Your job is to fetch comprehensive company data for equity research:
1. Use FMP API (Financial Modeling Prep) for financial data
2. Parse 10-K/10-Q filings for segment information
3. Get analyst estimates and consensus data

Always return structured JSON with:
- profile: Company basics (name, sector, industry, market_cap)
- financials: Revenue, earnings, margins for 5 years
- segments: Business unit breakdown
- metrics: Key ratios (P/E, EV/EBITDA, ROE, etc.)
- estimates: Analyst consensus

Be thorough but efficient. Fetch all relevant data in minimal API calls."""


DISCOVERY_PROMPT = """You are a Discovery Agent for equity research.

Your mission is to identify the most important research threads for a company
using the 7-Lens Framework:

1. OFFICIAL STRUCTURE: What are the reported business segments?
2. COMPETITIVE CROSS-REFERENCE: What do competitors emphasize that this company doesn't?
3. ANALYST ATTENTION: What are sell-side analysts focused on?
4. RECENT DEVELOPMENTS: What happened in the last 90 days?
5. ASSET INVENTORY: What hidden assets or optionalities exist?
6. MANAGEMENT EMPHASIS: What does the CEO keep talking about?
7. BLIND SPOTS: What's being ignored by the market?

Use web search to gather current information for each lens.

Output 3-8 research threads, prioritized by investment relevance.
Each thread should have:
- thread_name: Clear descriptive name
- priority: 1-8 (1 = highest)
- thread_type: SEGMENT (core business), OPTIONALITY (hidden value), or CROSS_CUTTING (themes)
- value_driver_hypothesis: The core investment question
- research_questions: 3-5 specific questions to investigate

Return as JSON array."""


RESEARCH_PROMPT = """You are a Deep Research Agent for equity research.

Your mission is to conduct thorough web-based research on a specific investment topic.

Research methodology:
1. Start with broad searches to understand the landscape
2. Drill into specifics with targeted queries
3. Cross-reference multiple sources
4. Prioritize recent sources (last 90 days for developments)
5. Include primary sources (company filings, press releases)
6. Balance bull and bear perspectives

For every claim:
- CITE THE SOURCE with URL
- Note the date of the source
- Quantify impacts where possible

Structure your findings as:
- key_findings: Major discoveries with citations
- bull_case: Positive implications
- bear_case: Risks and concerns
- data_points: Specific metrics discovered
- sources: All URLs used

Be thorough. Use 10+ web searches to cover the topic comprehensively."""


SYNTHESIS_PROMPT = """You are a Senior Equity Research Analyst at a top-tier investment bank.

Your mission is to synthesize research findings into a professional equity research report.

Report structure:
1. EXECUTIVE SUMMARY
   - Investment rating (BUY/HOLD/SELL) with confidence level
   - 12-month price target with methodology
   - Top 3 investment thesis points

2. INVESTMENT THESIS
   - Core value drivers
   - Competitive moats
   - Growth trajectory

3. BULL CASE SCENARIO
   - Upside catalysts
   - Probability-weighted target
   - Focus on OPTIONALITY threads

4. BEAR CASE SCENARIO
   - Key risks
   - Downside target
   - Focus on structural concerns

5. VALUATION
   - DCF analysis with explicit assumptions
   - Trading comparables
   - Sum-of-the-parts if applicable

6. FINANCIAL PROJECTIONS
   - 3-year revenue/earnings model
   - Margin trajectory
   - FCF generation

7. RISKS & CATALYSTS
   - Top 5 risks with probability and impact
   - Top 5 catalysts with timeline

8. APPENDIX
   - Detailed source citations
   - Data tables

Write in professional equity research style.
Be specific with numbers, dates, and timeframes.
Every claim must be traced to research findings."""


VERIFIER_PROMPT = """You are a Fact-Checking Agent for equity research.

Your mission is to verify claims in research reports against their sources.

For each major claim in the report:
1. Identify the cited source
2. Fetch the source content
3. Verify the claim matches the source
4. Check for outdated information
5. Identify any misrepresentations

Assign confidence scores:
- 5: Fully verified with primary source
- 4: Verified with reliable secondary source
- 3: Plausible but source unclear
- 2: Cannot verify, source inaccessible
- 1: Appears incorrect or misleading

Output:
- verified_claims: Claims with score 4-5
- uncertain_claims: Claims with score 2-3
- corrections: Any needed fixes
- overall_confidence: Weighted average score"""


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DiscoveredThread:
    """A research thread identified by Discovery."""
    thread_name: str
    priority: int
    thread_type: str  # SEGMENT, OPTIONALITY, CROSS_CUTTING
    value_driver_hypothesis: str
    research_questions: list[str] = field(default_factory=list)


@dataclass
class ResearchFinding:
    """Research results for a single thread."""
    thread: DiscoveredThread
    key_findings: list[dict] = field(default_factory=list)
    bull_case: str = ""
    bear_case: str = ""
    data_points: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_content: str = ""


@dataclass
class PipelineResult:
    """Complete pipeline output."""
    ticker: str
    company_context: dict = field(default_factory=dict)
    threads: list[DiscoveredThread] = field(default_factory=list)
    research_findings: list[ResearchFinding] = field(default_factory=list)
    report: str = ""
    verification: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz.utc))

    # Token tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company_context": self.company_context,
            "threads": [
                {
                    "thread_name": t.thread_name,
                    "priority": t.priority,
                    "thread_type": t.thread_type,
                    "value_driver_hypothesis": t.value_driver_hypothesis,
                    "research_questions": t.research_questions,
                }
                for t in self.threads
            ],
            "research_findings": [
                {
                    "thread": {
                        "thread_name": f.thread.thread_name,
                        "priority": f.thread.priority,
                    },
                    "key_findings": f.key_findings,
                    "sources_count": len(f.sources),
                }
                for f in self.research_findings
            ],
            "report_length": len(self.report),
            "verification": self.verification,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# AGENT PIPELINE
# =============================================================================

class AgentResearchPipeline:
    """Equity research pipeline using Claude Agent SDK.

    Implements multi-agent architecture like Anthropic's deep research:
    - Lead orchestrator (this class)
    - Parallel research subagents per thread
    - Opus synthesis subagent
    - Verifier subagent

    Each subagent has isolated 200K context window.
    Total effective context = N × 200K tokens.
    """

    def __init__(
        self,
        output_dir: Path,
        max_threads: int = 8,
        enable_verification: bool = True,
    ) -> None:
        """Initialize the pipeline.

        Args:
            output_dir: Where to save checkpoints and final report.
            max_threads: Maximum research threads to investigate.
            enable_verification: Whether to run verification stage.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_threads = max_threads
        self.enable_verification = enable_verification

        # Define specialized subagents
        self.agents: dict[str, AgentDefinition] = {
            "data-fetcher": AgentDefinition(
                description="Fetches company financial data from APIs and parses SEC filings",
                tools=["Bash", "WebFetch", "Read", "Write"],
                prompt=DATA_FETCHER_PROMPT,
                model="haiku",  # Fast and cheap for data fetching
            ),
            "discovery": AgentDefinition(
                description="Analyzes company to identify key research threads using 7-lens framework",
                tools=["WebSearch", "Read"],
                prompt=DISCOVERY_PROMPT,
                model="sonnet",
            ),
            "deep-researcher": AgentDefinition(
                description="Conducts deep web research on a specific investment topic",
                tools=["WebSearch", "WebFetch", "Read"],
                prompt=RESEARCH_PROMPT,
                model="sonnet",
            ),
            "synthesizer": AgentDefinition(
                description="Synthesizes research findings into professional equity research report",
                tools=["Read", "Write"],
                prompt=SYNTHESIS_PROMPT,
                model="opus",  # Best model for synthesis
            ),
            "verifier": AgentDefinition(
                description="Fact-checks claims against cited sources",
                tools=["WebFetch", "Read"],
                prompt=VERIFIER_PROMPT,
                model="sonnet",
            ),
        }

    async def run(self, ticker: str) -> PipelineResult:
        """Run the full multi-agent research pipeline.

        Stages:
        1. DATA: Fetch company financials and context
        2. DISCOVERY: Identify research threads (3-8)
        3. RESEARCH: Parallel deep research per thread
        4. SYNTHESIS: Opus synthesizes into report
        5. VERIFY: Fact-check the report (optional)

        Args:
            ticker: Stock ticker symbol.

        Returns:
            PipelineResult with complete research.
        """
        logger.info(f"[PIPELINE] Starting Agent SDK pipeline for {ticker}")
        result = PipelineResult(ticker=ticker)

        try:
            # Stage 1: Data
            logger.info(f"[STAGE 1] Fetching data for {ticker}...")
            result.company_context = await self._stage_data(ticker)

            # Stage 2: Discovery
            logger.info(f"[STAGE 2] Running Discovery for {ticker}...")
            result.threads = await self._stage_discovery(ticker, result.company_context)
            logger.info(f"[STAGE 2] Found {len(result.threads)} research threads")

            # Stage 3: Parallel Research
            logger.info(f"[STAGE 3] Deep research on {len(result.threads)} threads...")
            result.research_findings = await self._stage_research_parallel(
                ticker, result.threads
            )

            # Stage 4: Synthesis
            logger.info(f"[STAGE 4] Synthesizing with Opus 4.5...")
            result.report = await self._stage_synthesis(
                ticker, result.company_context, result.research_findings
            )

            # Save report
            report_path = self.output_dir / "report.md"
            report_path.write_text(result.report)
            logger.info(f"[STAGE 4] Report saved to {report_path}")

            # Stage 5: Verification (optional)
            if self.enable_verification:
                logger.info(f"[STAGE 5] Verifying claims...")
                result.verification = await self._stage_verification(result.report)

            # Save full result
            result_path = self.output_dir / "pipeline_result.json"
            result_path.write_text(json.dumps(result.to_dict(), indent=2))

            logger.info(f"[PIPELINE] Complete! Report: {report_path}")
            return result

        except Exception as e:
            logger.error(f"[PIPELINE] Failed: {e}")
            raise

    async def _stage_data(self, ticker: str) -> dict:
        """Stage 1: Fetch company data using data-fetcher subagent."""

        prompt = f"""Fetch comprehensive financial data for {ticker}:

1. Company profile (name, sector, industry, description, market cap, employees)
2. Income statement for last 5 years (revenue, operating income, net income)
3. Balance sheet (assets, liabilities, equity, cash, debt)
4. Key financial ratios (P/E, EV/EBITDA, P/S, ROE, ROIC, debt/equity)
5. Analyst estimates (revenue and EPS for next 2 years)
6. Business segments if available

Use the FMP API: https://financialmodelingprep.com/api/v3/
API key is in ANTHROPIC_API_KEY environment (or use free tier).

Return all data as a single structured JSON object with clear section names.
"""

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                agents={"data-fetcher": self.agents["data-fetcher"]},
                permission_mode="acceptEdits",
                cwd=str(self.output_dir),
            )
        ):
            if isinstance(message, ResultMessage):
                # Parse the result
                try:
                    data = json.loads(message.result) if isinstance(message.result, str) else message.result
                except json.JSONDecodeError:
                    # If not JSON, wrap as content
                    data = {"raw_content": message.result}

                # Save checkpoint
                checkpoint_path = self.output_dir / "stage1_data.json"
                checkpoint_path.write_text(json.dumps(data, indent=2))

                return data

        return {}

    async def _stage_discovery(self, ticker: str, company_context: dict) -> list[DiscoveredThread]:
        """Stage 2: Identify research threads using discovery subagent."""

        # Summarize company context for the prompt
        context_summary = json.dumps(company_context, indent=2)[:5000]  # Limit size

        prompt = f"""Analyze {ticker} using the 7-lens Discovery framework.

Company Context:
{context_summary}

Apply each lens with web searches to find current information:

1. OFFICIAL STRUCTURE: Review their reported segments
2. COMPETITIVE CROSS-REFERENCE: What are competitors like {self._get_competitors(ticker)} emphasizing?
3. ANALYST ATTENTION: What are analysts focused on right now?
4. RECENT DEVELOPMENTS: Major news in last 90 days
5. ASSET INVENTORY: Hidden assets, IP, real estate, data moats
6. MANAGEMENT EMPHASIS: CEO's recent statements and priorities
7. BLIND SPOTS: What's the market ignoring?

Synthesize into 3-8 research threads, each with:
- thread_name: Clear name (e.g., "Cloud Revenue Acceleration")
- priority: 1-8 (1 = highest priority)
- thread_type: SEGMENT, OPTIONALITY, or CROSS_CUTTING
- value_driver_hypothesis: Core investment question
- research_questions: 3-5 specific questions

Return as JSON array like:
[
  {{
    "thread_name": "Example Thread",
    "priority": 1,
    "thread_type": "SEGMENT",
    "value_driver_hypothesis": "Is X driving growth?",
    "research_questions": ["Q1?", "Q2?", "Q3?"]
  }}
]
"""

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                agents={"discovery": self.agents["discovery"]},
                permission_mode="acceptEdits",
            )
        ):
            if isinstance(message, ResultMessage):
                # Parse threads from response
                threads = self._parse_threads(message.result)

                # Save checkpoint
                checkpoint_path = self.output_dir / "stage2_discovery.json"
                checkpoint_path.write_text(json.dumps(
                    [{"thread_name": t.thread_name, "priority": t.priority,
                      "thread_type": t.thread_type, "research_questions": t.research_questions}
                     for t in threads],
                    indent=2
                ))

                return threads[:self.max_threads]

        return []

    async def _stage_research_parallel(
        self,
        ticker: str,
        threads: list[DiscoveredThread],
    ) -> list[ResearchFinding]:
        """Stage 3: Parallel deep research on each thread.

        This is where multi-agent architecture shines:
        - Each thread gets its own subagent with isolated context
        - All run in parallel for speed
        - Each can do 10+ web searches without polluting others
        """

        async def research_single_thread(thread: DiscoveredThread) -> ResearchFinding:
            """Research one thread with dedicated subagent."""

            research_questions = "\n".join(f"- {q}" for q in thread.research_questions)

            prompt = f"""Deep research on "{thread.thread_name}" for {ticker}.

Priority: P{thread.priority}
Type: {thread.thread_type}

Core Question: {thread.value_driver_hypothesis}

Specific Research Questions:
{research_questions}

Instructions:
1. Use web search extensively (aim for 10+ queries)
2. Prioritize recent sources (last 90 days for news/developments)
3. Include primary sources (SEC filings, press releases, earnings calls)
4. Get both bull and bear perspectives
5. Quantify impacts with specific numbers where possible
6. Cite EVERY claim with the source URL

Structure your response as JSON:
{{
  "key_findings": [
    {{"finding": "...", "source_url": "...", "date": "..."}},
    ...
  ],
  "bull_case": "...",
  "bear_case": "...",
  "data_points": [
    {{"metric": "...", "value": "...", "source": "..."}},
    ...
  ],
  "sources": ["url1", "url2", ...]
}}
"""

            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    agents={"deep-researcher": self.agents["deep-researcher"]},
                    permission_mode="acceptEdits",
                )
            ):
                if isinstance(message, ResultMessage):
                    finding = ResearchFinding(thread=thread, raw_content=str(message.result))

                    # Try to parse structured response
                    try:
                        data = json.loads(message.result) if isinstance(message.result, str) else message.result
                        finding.key_findings = data.get("key_findings", [])
                        finding.bull_case = data.get("bull_case", "")
                        finding.bear_case = data.get("bear_case", "")
                        finding.data_points = data.get("data_points", [])
                        finding.sources = data.get("sources", [])
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        # Keep raw content if parsing fails
                        pass

                    return finding

            return ResearchFinding(thread=thread)

        # Run ALL thread research in parallel
        logger.info(f"[STAGE 3] Launching {len(threads)} parallel research subagents")
        tasks = [research_single_thread(thread) for thread in threads]
        findings = await asyncio.gather(*tasks)

        # Save checkpoint
        checkpoint_path = self.output_dir / "stage3_research.json"
        checkpoint_data = [
            {
                "thread_name": f.thread.thread_name,
                "priority": f.thread.priority,
                "findings_count": len(f.key_findings),
                "sources_count": len(f.sources),
                "bull_case": f.bull_case[:500] if f.bull_case else "",
                "bear_case": f.bear_case[:500] if f.bear_case else "",
            }
            for f in findings
        ]
        checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2))

        return findings

    async def _stage_synthesis(
        self,
        ticker: str,
        company_context: dict,
        findings: list[ResearchFinding],
    ) -> str:
        """Stage 4: Synthesize with Opus 4.5.

        The synthesizer gets distilled results from all research subagents,
        not the raw web search data. This is efficient context usage.
        """

        # Sort findings by priority
        sorted_findings = sorted(findings, key=lambda f: f.thread.priority)

        # Build research content
        research_sections = []
        for f in sorted_findings:
            section = f"""
## [P{f.thread.priority}] {f.thread.thread_name} ({f.thread.thread_type})

**Core Question:** {f.thread.value_driver_hypothesis}

### Key Findings
"""
            # Add key findings
            for kf in f.key_findings[:10]:  # Limit to avoid context overflow
                if isinstance(kf, dict):
                    section += f"- {kf.get('finding', str(kf))} [Source: {kf.get('source_url', 'N/A')}]\n"
                else:
                    section += f"- {kf}\n"

            # Add bull/bear
            if f.bull_case:
                section += f"\n**Bull Case:** {f.bull_case}\n"
            if f.bear_case:
                section += f"\n**Bear Case:** {f.bear_case}\n"

            # Add data points
            if f.data_points:
                section += "\n**Key Metrics:**\n"
                for dp in f.data_points[:5]:
                    if isinstance(dp, dict):
                        section += f"- {dp.get('metric', '?')}: {dp.get('value', '?')}\n"

            # Add source count
            section += f"\n*Sources: {len(f.sources)} references*\n"

            research_sections.append(section)

        research_content = "\n---\n".join(research_sections)

        # Summarize company context
        context_summary = json.dumps(company_context, indent=2)[:3000]

        prompt = f"""Synthesize this research into a professional equity research report for {ticker}.

## Company Context
{context_summary}

## Research Findings (by priority)
{research_content}

---

Create a comprehensive equity research report with:

1. **EXECUTIVE SUMMARY** (1 page)
   - Investment rating (BUY/HOLD/SELL) with confidence
   - 12-month price target with methodology
   - Top 3 investment thesis points

2. **INVESTMENT THESIS**
   - Core value drivers from P1-P2 research
   - Competitive moats and advantages
   - Growth trajectory with evidence

3. **BULL CASE** (20% probability weight)
   - Focus on OPTIONALITY threads
   - Quantify upside potential
   - Key catalysts needed

4. **BEAR CASE** (20% probability weight)
   - Focus on SEGMENT risks
   - Quantify downside
   - What would break the thesis

5. **VALUATION**
   - DCF with explicit assumptions (WACC, growth rate, terminal multiple)
   - Trading comparables if data available
   - Sum-of-parts if applicable

6. **FINANCIAL PROJECTIONS**
   - Revenue forecast 3 years
   - Margin trajectory
   - FCF projections

7. **RISKS & CATALYSTS**
   - Top 5 risks with probability and impact
   - Top 5 catalysts with expected timing

8. **APPENDIX**
   - All source citations organized by section
   - Supporting data tables

Write in professional sell-side research style.
Be specific with numbers, dates, and sources.
Every major claim should reference the research findings above.
"""

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                agents={"synthesizer": self.agents["synthesizer"]},
                permission_mode="acceptEdits",
            )
        ):
            if isinstance(message, ResultMessage):
                return str(message.result)

        return ""

    async def _stage_verification(self, report: str) -> dict:
        """Stage 5: Verify claims against sources."""

        # Take first 10K chars of report to avoid context overflow
        report_excerpt = report[:10000]

        prompt = f"""Verify the major claims in this equity research report:

{report_excerpt}

For each significant claim with a citation:
1. Check if the source URL is provided
2. Attempt to verify the claim matches the source
3. Note any outdated information (sources > 90 days old)
4. Flag any unsupported claims

Rate each claim:
- 5: Fully verified with primary source
- 4: Verified with reliable secondary source
- 3: Plausible but source unclear
- 2: Cannot verify
- 1: Appears incorrect

Return as JSON:
{{
  "verified_claims": [
    {{"claim": "...", "source": "...", "score": 5, "note": "..."}}
  ],
  "uncertain_claims": [
    {{"claim": "...", "issue": "..."}}
  ],
  "corrections": [
    {{"original": "...", "correction": "...", "reason": "..."}}
  ],
  "overall_confidence": 4.2
}}
"""

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                agents={"verifier": self.agents["verifier"]},
                permission_mode="acceptEdits",
            )
        ):
            if isinstance(message, ResultMessage):
                try:
                    result = message.result
                    if isinstance(result, str):
                        result = json.loads(result)

                    # Save checkpoint
                    checkpoint_path = self.output_dir / "stage5_verification.json"
                    checkpoint_path.write_text(json.dumps(result, indent=2))

                    return result
                except (json.JSONDecodeError, TypeError):
                    return {"raw_result": str(message.result)}

        return {}

    def _get_competitors(self, ticker: str) -> str:
        """Get competitor tickers for cross-reference."""
        # Simple mapping for major stocks
        competitors = {
            "AAPL": "MSFT, GOOGL, SAMSUNG",
            "GOOGL": "MSFT, META, AMZN",
            "MSFT": "GOOGL, AMZN, AAPL",
            "AMZN": "WMT, MSFT, GOOGL",
            "META": "GOOGL, SNAP, PINS",
            "NVDA": "AMD, INTC, QCOM",
            "TSLA": "F, GM, RIVN",
        }
        return competitors.get(ticker, "top industry peers")

    def _parse_threads(self, result: Any) -> list[DiscoveredThread]:
        """Parse threads from discovery result."""
        threads = []

        try:
            # Try to parse as JSON
            if isinstance(result, str):
                data = json.loads(result)
            else:
                data = result

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        threads.append(DiscoveredThread(
                            thread_name=item.get("thread_name", "Unknown"),
                            priority=int(item.get("priority", 99)),
                            thread_type=item.get("thread_type", "CROSS_CUTTING"),
                            value_driver_hypothesis=item.get("value_driver_hypothesis", ""),
                            research_questions=item.get("research_questions", []),
                        ))
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse threads: {e}")
            # Create a default thread
            threads.append(DiscoveredThread(
                thread_name="General Research",
                priority=1,
                thread_type="CROSS_CUTTING",
                value_driver_hypothesis="Understand the company",
                research_questions=["What is the business model?", "What are the key risks?"],
            ))

        return threads


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

async def main():
    """CLI entrypoint for agent pipeline."""
    import sys
    import os
    from pathlib import Path

    # Get ticker from args
    if len(sys.argv) < 2:
        print("Usage: python -m er.coordinator.agent_pipeline TICKER [--output-dir DIR]")
        print("Example: python -m er.coordinator.agent_pipeline GOOGL")
        sys.exit(1)

    ticker = sys.argv[1].upper()

    # Parse output dir
    output_dir = Path(f"./output/{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    for i, arg in enumerate(sys.argv):
        if arg == "--output-dir" and i + 1 < len(sys.argv):
            output_dir = Path(sys.argv[i + 1])

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable required")
        sys.exit(1)

    # Run pipeline
    pipeline = AgentResearchPipeline(output_dir=output_dir)

    print(f"\n{'='*60}")
    print(f"EQUITY RESEARCH PIPELINE - Claude Agent SDK")
    print(f"{'='*60}")
    print(f"Ticker: {ticker}")
    print(f"Output: {output_dir}")
    print(f"{'='*60}\n")

    result = await pipeline.run(ticker)

    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"Threads researched: {len(result.threads)}")
    print(f"Report length: {len(result.report)} chars")
    print(f"Report saved to: {output_dir}/report.md")
    if result.verification:
        confidence = result.verification.get("overall_confidence", "N/A")
        print(f"Verification confidence: {confidence}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
