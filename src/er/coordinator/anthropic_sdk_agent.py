"""
Equity Research Pipeline using Claude Agent SDK.

=============================================================================
ARCHITECTURE OVERVIEW (January 2026)
=============================================================================

This is the CANONICAL pipeline. All other implementations are legacy.

PIPELINE STAGES:
    Stage 1: FMPClient (Python, no AI)
        - Fetches REAL financial data from SEC filings via FMP API
        - Returns CompanyContext with quarterly income statements, balance sheets, etc.
        - This is ACTUAL REPORTED data, NOT analyst estimates

    Stage 2: Discovery (AnthropicDiscoveryAgent)
        - Uses Claude Agent SDK with 3 subagents running in parallel
        - Applies 7-Lens Framework to identify research threads
        - Subagents: segment-analyst, competitive-analyst, threat-analyst
        - Output: 5-8 research threads with hypotheses and questions
        - Code: src/er/agents/discovery_anthropic.py

    Stage 3: Deep Research (This file - orchestrator + N subagents)
        - Takes Discovery output and spawns one subagent per thread
        - Each subagent gets the RICH prompt with:
          * Full company context (quarterly financials from JSON)
          * Date grounding (TODAY IS, CURRENT MONTH, LATEST QUARTER)
          * Structured output template (Overview → Financial → Competitive → etc.)
          * Clear rules: JSON=financials, WebSearch=context
        - Output: Detailed markdown analysis per thread

    Stage 4: Synthesis
        - Combines all thread analyses into investment research report
        - Outputs: Executive Summary, Bull/Bear Case, Valuation, Risks

    Stage 5: Verification (optional)
        - Fact-checks claims against sources

DATA FLOW:
    FMP API → CompanyContext → Discovery → Threads → Deep Research → Report

KEY PRINCIPLE:
    - Quarterly data from FMP is GROUND TRUTH (actual SEC filings)
    - Models should NEVER search for financials (they have the JSON)
    - Models MUST search for CONTEXT: market share, competitive moves, analyst views

PROMPTS:
    - Discovery prompt: src/er/agents/discovery_anthropic.py
    - Deep Research prompt: THREAD_RESEARCH_PROMPT below (from docs/prompts/deep_research.md)
    - Synthesis prompt: SYNTHESIS_PROMPT below

=============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any

from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

from er.logging import get_logger
from er.evidence.store import EvidenceStore
from er.data.fmp_client import FMPClient
from er.data.transcript_loader import load_transcripts
from er.types import CompanyContext, DiscoveryOutput
from er.agents.discovery_anthropic import AnthropicDiscoveryAgent
from er.utils.dates import get_latest_quarter_from_data, format_quarter, format_quarters_for_prompt

logger = get_logger(__name__)


# =============================================================================
# STAGE 3: DEEP RESEARCH PROMPTS
#
# These prompts implement the rich analysis framework from docs/prompts/deep_research.md
# Each subagent receives:
#   - Full company context with quarterly financials
#   - Date grounding
#   - Structured output template
#   - Clear instructions on what to search vs what's in JSON
# =============================================================================

DEEP_RESEARCH_ORCHESTRATOR_PROMPT = """You are the Lead Research Orchestrator for institutional equity research.

## CRITICAL: DATE AND DATA GROUNDING

TODAY IS: {date}
CURRENT MONTH: {current_month} {current_year}
LATEST QUARTER WITH ACTUAL REPORTED EARNINGS: {latest_quarter}

Your training data is STALE. You MUST use web search for anything that may have changed.

## QUARTERLY DATA CONTEXT

{quarter_context}

**DO NOT USE** annual data as "current" state. Annual data is 12+ months old. Only use for historical comparison.

## COMPANY: {ticker} ({company_name})

## GROUND TRUTH DATA (ACTUAL FILED FINANCIALS - NOT ESTIMATES)

This is REAL DATA from SEC 10-Q/10-K filings via FMP API. These are ACTUAL REPORTED numbers, not analyst estimates.
The quarterly data below is from official filings - treat it as factual ground truth.

```json
{company_context}
```

## YOUR TASK

You coordinate deep research on specific threads identified during Discovery.
Each thread should be investigated by a specialized subagent.

For each research thread, spawn a subagent to investigate:
1. Use web search to gather comprehensive information about CONTEXT (competitive position, market share, analyst views)
2. Find bull and bear perspectives
3. Quantify impacts where possible
4. Cite sources with URLs and dates

**IMPORTANT**: Subagents have financial data from JSON. They should search for CONTEXT, not financials:
- GOOD searches: market share, competitive moves, analyst views, recent news
- BAD searches: revenue numbers, growth rates, margins (already in JSON)

## THREADS TO INVESTIGATE

{threads}

## INSTRUCTIONS

1. Spawn one subagent per thread using the Task tool
2. Each subagent should use 10-15 web searches for CONTEXT (not financials)
3. Collect all findings and synthesize into a unified research package

Output JSON:
```json
{{
  "findings": [
    {{
      "thread_name": "Name",
      "key_findings": [
        {{"finding": "...", "source_url": "...", "date": "YYYY-MM-DD"}}
      ],
      "bull_case": "...",
      "bear_case": "...",
      "data_points": [
        {{"metric": "...", "value": "...", "source": "..."}}
      ]
    }}
  ]
}}
```"""


# -----------------------------------------------------------------------------
# THREAD_RESEARCH_PROMPT - The Rich Deep Research Prompt
#
# This is the comprehensive prompt from docs/prompts/deep_research.md
# Each subagent researching a thread receives this with all variables filled in
# -----------------------------------------------------------------------------

THREAD_RESEARCH_PROMPT = """You are a Deep Research Analyst for an institutional equity research system.

## CRITICAL: YOUR ROLE IS DEPTH, NOT DISCOVERY

Discovery Agent already did the wide scan. It found this thread, identified competitors, gathered analyst views, and searched the web.

YOUR JOB IS DIFFERENT:
- Discovery = Wide (find threads, identify what matters)
- Deep Research = Deep (validate claims, add nuance, fill gaps, challenge assumptions)

You are NOT re-discovering. You are INVESTIGATING what Discovery found.

Think of yourself as a fact-checker and investigative journalist:
- "Discovery says X - is that actually true?"
- "The bull case claims Y - what's the evidence?"
- "The bear concern is Z - how serious is it really?"
- "Discovery couldn't find W - let me dig deeper"

## CRITICAL: DATE AND DATA GROUNDING

TODAY IS: {date}
CURRENT MONTH: {current_month} {current_year}

Your training data is STALE. You MUST use web search for anything that may have changed.

## QUARTERLY DATA CONTEXT

{quarter_context}

**DO NOT USE** annual data as "current" state. Annual data is 12+ months old. Only use for historical comparison.

## GROUND TRUTH DATA (ACTUAL FILED FINANCIALS - NOT ESTIMATES)

This is REAL DATA from SEC 10-Q/10-K filings via FMP API. These are ACTUAL REPORTED numbers, not analyst estimates.
The quarterly data below is from official filings - treat it as factual ground truth.

The JSON also contains **earnings_transcripts** with the CEO/CFO's actual words from recent earnings calls.
Use these for Management Emphasis analysis:
- What did the CEO prioritize? How many times was it mentioned?
- What topics were deflected or minimized?
- What forward guidance was given?
- What competitive dynamics were acknowledged?

```json
{company_context}
```

## YOUR RESEARCH ASSIGNMENT

Company: {ticker} ({company_name})
Research Thread: **{thread_name}**
Type: {thread_type}, Priority: {thread_priority}

## HYPOTHESIS TO VALIDATE

{hypothesis}

## RESEARCH QUESTIONS TO ANSWER

{questions}

## WHAT DISCOVERY ALREADY FOUND

**THIS IS CRITICAL**: Discovery Agent already searched and found the following.
DO NOT re-search for basic facts that are already here. Your job is to:
1. VALIDATE these claims (are they accurate?)
2. ADD NUANCE (what's the full story?)
3. GO DEEPER (what did Discovery miss?)
4. CHALLENGE (what's the counter-argument?)

### Discovery's Findings for This Thread:
{discovery_context}

### Searches Discovery Already Performed:
{searches_already_done}

### External Threats Relevant to This Thread:
{relevant_threats}

## YOUR DEEP RESEARCH METHODOLOGY

Since Discovery already did the initial scan, your searches should be:

### 1. VALIDATION SEARCHES (verify Discovery's claims)
- If Discovery said "competitor X is gaining share" → search for specific market share data
- If Discovery said "analysts are bullish" → search for actual analyst reports/targets
- Goal: Confirm or refute what Discovery claimed

### 2. DEPTH SEARCHES (go beyond Discovery)
- Discovery found a competitor → search for that competitor's specific recent moves
- Discovery identified a risk → search for how serious it actually is
- Discovery noted a trend → search for quantification and timeline

### 3. COUNTER-THESIS SEARCHES (challenge the narrative)
- If the bull case seems strong → actively search for bear arguments
- If a threat seems severe → search for company's defenses/responses
- Goal: Steel-man the opposing view

### 4. GAP-FILLING SEARCHES (what Discovery couldn't find)
- Discovery listed gaps → search specifically for those missing data points
- Discovery's confidence was low → find better sources

## WHAT NOT TO SEARCH FOR

**DO NOT WASTE SEARCHES ON:**
- Basic facts Discovery already found (see above)
- Revenue/growth/margin numbers (in JSON)
- Generic company overviews
- Things that haven't changed recently

**DO SEARCH FOR:**
- Specific evidence to validate Discovery's claims
- Recent developments (last 30 days) Discovery might have missed
- Quantification of claims Discovery made qualitatively
- Counter-arguments to Discovery's thesis

## OUTPUT STRUCTURE

Write tight, information-dense prose. Output your analysis as a structured research report in markdown.

### CRITICAL: BE AGNOSTIC

You are a RESEARCHER, not an investment analyst. Your job is to gather and present facts objectively.

DO NOT:
- Form investment conclusions (that's the Synthesizer's job)
- Say things like "this is bullish" or "this is bearish"
- Recommend or suggest investment views
- Use language like "verdict", "thesis", or "view"

DO:
- Present facts and data objectively
- Identify both positive and negative dynamics
- Highlight uncertainties and what could change
- Let the evidence speak for itself

### Required Sections:

---

## {thread_name}

### Overview
3-4 sentences. What is this thread and why does it matter? (Factual, no opinion)

### Financial Performance (FROM JSON ONLY)
- {latest_quarter} revenue: $X (+Y% YoY)
- Quarterly trajectory (accelerating/stable/decelerating)
- Margin: X% or "not disclosed"
- Source: Cite which JSON field you used

### Discovery Validation
What Discovery claimed vs what you found:
- **Claim**: [what Discovery said]
- **Validation**: CONFIRMED / NUANCED / REFUTED
- **Evidence**: [your sources]
- **Additional Context**: [what Discovery missed]

### Competitive Landscape (DEPTH BEYOND DISCOVERY)
Discovery already identified competitors. Go deeper:
- Specific market share numbers with sources
- Recent competitive moves Discovery might have missed (last 30 days)
- Competitive dynamics: What's changing RIGHT NOW?
- Moat assessment: Is it strengthening or weakening? Evidence?

### Threat Assessment (VALIDATE DISCOVERY'S THREATS)
For threats Discovery identified affecting this thread:
- **Threat**: [name from Discovery]
- **Discovery's Assessment**: [what Discovery said]
- **Your Validation**: How serious is this actually?
- **Timeline**: When could this impact the business?
- **Company Response**: What is {ticker} doing about it?

### Growth Dynamics
**Tailwinds** (factors that could accelerate growth):
- Tailwind 1: [magnitude: high/med/low] - evidence (with source, date)
- Tailwind 2: [magnitude: high/med/low] - evidence (with source, date)

**Headwinds** (factors that could slow growth):
- Headwind 1: [magnitude: high/med/low] - evidence (with source, date)
- Headwind 2: [magnitude: high/med/low] - evidence (with source, date)

### Key Uncertainties
What questions remain unanswered that could materially affect this thread?
- Uncertainty 1: [what we don't know and why it matters]
- Uncertainty 2: [what we don't know and why it matters]

What to watch:
- If [X happens], it would suggest [positive/negative for growth]
- If [Y happens], it would suggest [positive/negative for growth]

### Research Quality
- Discovery's claims validated: X of Y
- New information found: [list]
- Gaps remaining: [what we still couldn't find or verify]
- Confidence: [0.0-1.0] with justification

---

## Web Searches Performed
List all searches with: query, source found, date of source, key finding
Note which were VALIDATION vs DEPTH vs COUNTER-THESIS searches.

## CONFIDENCE CALIBRATION

Your confidence score MUST reflect evidence quality:

| Evidence Quality | Max Confidence |
|------------------|----------------|
| Multiple recent sources (< 60 days) agreeing | 0.9 |
| Single authoritative source (SEC, company IR) | 0.8 |
| Multiple news sources, some conflicting | 0.6 |
| Single news source | 0.5 |
| Analyst estimates only | 0.4 |
| Training data / memory (no search) | 0.2 |
| Speculation | 0.1 |

If you claim confidence > 0.7, you must cite:
- At least 2 sources
- At least 1 source from last 60 days
- Sources must agree on the key claim

If your sources are thin, LOWER YOUR CONFIDENCE. Do not pretend certainty.

## HARD RULES

1. **BUILD ON DISCOVERY** - Don't re-discover. Validate, nuance, and deepen what Discovery found.

2. **JSON = FINANCIALS** - All revenue, growth, margin numbers come from JSON. Never use web search numbers for financials.

3. **SEARCH FOR DEPTH** - Your searches should go BEYOND Discovery, not repeat it.

4. **VALIDATE CLAIMS** - Every claim Discovery made should be checked. Mark as CONFIRMED/NUANCED/REFUTED.

5. **CHALLENGE THE THESIS** - Actively search for counter-arguments. Steel-man the opposing view.

6. **CITE DATES** - Every non-JSON claim needs a date. "Market share is 25%" means nothing without "as of {latest_quarter} per [source]."

7. **ADMIT GAPS** - If you can't find something, say so. List it in gaps. Don't fabricate.
"""


# -----------------------------------------------------------------------------
# SYNTHESIS AND VERIFICATION PROMPTS
# -----------------------------------------------------------------------------

SYNTHESIS_PROMPT = """You are a Senior Equity Research Analyst at a top-tier investment bank.

Synthesize the following research into a professional equity research report.

## COMPANY: {ticker}
{company_context}

## RESEARCH FINDINGS
{research_findings}

## REPORT STRUCTURE

1. **EXECUTIVE SUMMARY**
   - Investment rating (BUY/HOLD/SELL)
   - Price target with methodology
   - Top 3 thesis points

2. **INVESTMENT THESIS**
   - Core value drivers
   - Competitive moats
   - Growth trajectory

3. **BULL CASE**
   - Upside catalysts
   - Probability-weighted target

4. **BEAR CASE**
   - Key risks
   - Downside target

5. **VALUATION**
   - DCF with explicit assumptions
   - Trading comps

6. **FINANCIAL PROJECTIONS**
   - 3-year revenue/earnings model

7. **RISKS & CATALYSTS**
   - Top 5 each with timing

8. **SOURCES**
   - All citations from research

Write in professional sell-side research style.
Be specific with numbers, dates, and sources.
Every claim must be traced to research findings."""


VERIFIER_PROMPT = """You are a Fact-Checking Agent for equity research.

Verify claims in this research report against their sources.

## REPORT
{report}

## INSTRUCTIONS

For each major claim:
1. Identify the cited source
2. Use web search to verify the claim
3. Check for outdated information
4. Identify any misrepresentations

Assign confidence scores:
- 5: Fully verified with primary source
- 4: Verified with reliable secondary source
- 3: Plausible but source unclear
- 2: Cannot verify
- 1: Appears incorrect

Return JSON:
```json
{{
  "verified_claims": [
    {{"claim": "...", "source": "...", "score": 5}}
  ],
  "uncertain_claims": [
    {{"claim": "...", "issue": "..."}}
  ],
  "corrections": [
    {{"original": "...", "correction": "...", "reason": "..."}}
  ],
  "overall_confidence": 4.2
}}
```"""


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DiscoveredThread:
    """A research thread identified by Discovery.

    Created from Discovery Agent output and passed to Deep Research.
    """
    thread_name: str
    priority: int
    thread_type: str
    value_driver_hypothesis: str
    research_questions: list[str] = field(default_factory=list)


@dataclass
class ResearchFinding:
    """Research results for a single thread.

    Output from a Deep Research subagent.
    """
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

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "threads": [
                {
                    "thread_name": t.thread_name,
                    "priority": t.priority,
                    "thread_type": t.thread_type,
                    "value_driver_hypothesis": t.value_driver_hypothesis,
                }
                for t in self.threads
            ],
            "research_findings": [
                {
                    "thread_name": f.thread.thread_name,
                    "findings_count": len(f.key_findings),
                    "sources_count": len(f.sources),
                }
                for f in self.research_findings
            ],
            "report_length": len(self.report),
            "verification": self.verification,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# PIPELINE
# =============================================================================

class ResearchPipeline:
    """Equity research pipeline using Claude Agent SDK.

    THIS IS THE CANONICAL IMPLEMENTATION.

    All AI stages use the Claude Agent SDK:
    - Stage 1: FMPClient (Python, no AI) - fetches real SEC filing data
    - Stage 2: AnthropicDiscoveryAgent (orchestrator + 3 subagents)
    - Stage 3: Deep Research (orchestrator + N subagents with rich prompts)
    - Stage 4: Synthesis
    - Stage 5: Verification

    Data Flow:
        FMP API → CompanyContext → Discovery → Threads → Deep Research → Report

    Key Files:
        - Discovery: src/er/agents/discovery_anthropic.py
        - Deep Research prompts: This file (THREAD_RESEARCH_PROMPT)
        - Prompt templates: docs/prompts/deep_research.md
    """

    def __init__(
        self,
        output_dir: Path,
        max_threads: int = 8,
        enable_verification: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_threads = max_threads
        self.enable_verification = enable_verification

        # Evidence store and FMP client for Stage 1
        self._evidence_store: EvidenceStore | None = None
        self._fmp_client: FMPClient | None = None

        # Store discovery output for cross-stage access
        self._discovery_output: DiscoveryOutput | None = None

        # Store company context for cross-stage access
        self._company_context: dict | None = None

    async def run(self, ticker: str) -> PipelineResult:
        """Run the full research pipeline.

        Args:
            ticker: Stock ticker symbol (e.g., "GOOGL", "AAPL")

        Returns:
            PipelineResult with threads, findings, and final report
        """
        logger.info(f"[PIPELINE] Starting for {ticker}")
        result = PipelineResult(ticker=ticker)

        try:
            # Stage 1: Data (FMPClient - no AI)
            # Fetches REAL financial data from SEC filings
            logger.info(f"[STAGE 1] Fetching data from FMP API...")
            result.company_context = await self._stage_data(ticker)
            self._company_context = result.company_context

            # Stage 2: Discovery (AnthropicDiscoveryAgent with subagents)
            # Uses 7-Lens Framework to identify research threads
            logger.info(f"[STAGE 2] Running Discovery (7-Lens Framework)...")
            result.threads = await self._stage_discovery(ticker, result.company_context)
            logger.info(f"[STAGE 2] Found {len(result.threads)} threads")

            # Stage 3: Deep Research (orchestrator + N subagents)
            # Each subagent gets the RICH prompt with full context
            logger.info(f"[STAGE 3] Deep research on {len(result.threads)} threads...")
            result.research_findings = await self._stage_research(
                ticker, result.threads, company_context=result.company_context
            )

            # Stage 4: Synthesis
            # Combines all findings into investment research report
            logger.info(f"[STAGE 4] Synthesizing report...")
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

            # Save result
            result_path = self.output_dir / "pipeline_result.json"
            result_path.write_text(json.dumps(result.to_dict(), indent=2))

            logger.info(f"[PIPELINE] Complete!")
            return result

        except Exception as e:
            logger.error(f"[PIPELINE] Failed: {e}")
            raise

    async def _stage_data(self, ticker: str) -> dict:
        """Stage 1: Fetch data from FMP (no AI) + load local transcripts.

        Returns CompanyContext with ACTUAL REPORTED financials from SEC filings.
        This is GROUND TRUTH data, not analyst estimates.

        Also loads earnings call transcripts from local files if available.
        Transcripts are critical for Lens 6 (Management Emphasis).
        """
        if self._evidence_store is None:
            self._evidence_store = EvidenceStore(self.output_dir / "evidence")
            await self._evidence_store.init()

        if self._fmp_client is None:
            self._fmp_client = FMPClient(self._evidence_store)

        full_context = await self._fmp_client.get_full_context(ticker)

        # Load local transcripts if available (FMP API requires higher tier)
        # Transcripts are essential for Management Emphasis (Lens 6)
        local_transcripts = load_transcripts(ticker)
        if local_transcripts:
            logger.info(
                f"[STAGE 1] Loaded {len(local_transcripts)} local transcripts",
                quarters=[f"Q{t['quarter']} {t['year']}" for t in local_transcripts],
            )
            # Merge with any FMP transcripts (local takes precedence for same quarter)
            existing = {(t.get("quarter"), t.get("year")): t for t in full_context.get("transcripts", [])}
            for t in local_transcripts:
                key = (t["quarter"], t["year"])
                existing[key] = t  # Local overwrites FMP if same quarter
            full_context["transcripts"] = list(existing.values())
            # Sort by date (most recent first)
            full_context["transcripts"].sort(
                key=lambda x: (x.get("year", 0), x.get("quarter", 0)),
                reverse=True,
            )

        # Save checkpoint
        checkpoint = self.output_dir / "stage1_data.json"
        checkpoint.write_text(json.dumps({
            "ticker": ticker,
            "profile": full_context.get("profile", {}),
            "evidence_ids": len(full_context.get("evidence_ids", [])),
            "transcripts_loaded": len(full_context.get("transcripts", [])),
        }, indent=2, default=str))

        return full_context

    async def _stage_discovery(
        self, ticker: str, company_context: dict
    ) -> list[DiscoveredThread]:
        """Stage 2: Discovery using AnthropicDiscoveryAgent.

        Uses Claude Agent SDK with 3 subagents:
        - segment-analyst: Official business segments
        - competitive-analyst: Competitor analysis
        - threat-analyst: External threats (NEW)

        Applies 7-Lens Framework to identify 5-8 research threads.
        """
        typed_context = CompanyContext.from_fmp_data(company_context)

        discovery_agent = AnthropicDiscoveryAgent(
            evidence_store=self._evidence_store,
            max_searches_per_subagent=5,
        )

        discovery_output = await discovery_agent.run(typed_context)
        self._discovery_output = discovery_output

        # Convert to local DiscoveredThread
        threads = []
        for t in discovery_output.research_threads:
            threads.append(DiscoveredThread(
                thread_name=t.name,
                priority=t.priority,
                thread_type=t.thread_type.value if hasattr(t.thread_type, 'value') else str(t.thread_type),
                value_driver_hypothesis=t.value_driver_hypothesis,
                research_questions=list(t.research_questions),
            ))

        threads.sort(key=lambda x: x.priority)

        # Save checkpoint
        checkpoint = self.output_dir / "stage2_discovery.json"
        checkpoint.write_text(json.dumps({
            "ticker": ticker,
            "threads": [{"name": t.thread_name, "priority": t.priority} for t in threads],
            "searches_performed": discovery_output.searches_performed,
        }, indent=2))

        return threads[:self.max_threads]

    async def _stage_research(
        self, ticker: str, threads: list[DiscoveredThread], company_context: dict | None = None
    ) -> list[ResearchFinding]:
        """Stage 3: Deep research using Claude Agent SDK with subagents.

        ARCHITECTURE (Jan 2026):
        ========================
        Discovery (Stage 2) already did the WIDE scan:
        - Identified threads and hypotheses
        - Gathered competitor analysis, analyst views, recent developments
        - Identified external threats mapped to verticals
        - Performed web searches (tracked in searches_performed)

        Deep Research (Stage 3) does the DEEP dive:
        - Validates Discovery's claims (are they accurate?)
        - Adds nuance (what's the full story?)
        - Goes deeper (what did Discovery miss?)
        - Challenges (what's the counter-argument?)

        Each subagent receives:
        - Full company context (quarterly financials from JSON)
        - Date grounding (TODAY IS, CURRENT MONTH, LATEST QUARTER)
        - DISCOVERY'S FINDINGS for this thread (so they don't re-discover)
        - Threats relevant to this thread
        - Searches Discovery already performed

        This implements the BUILD-ON-DISCOVERY philosophy.
        """

        # Get date grounding
        now = datetime.now(tz.utc)
        date_str = now.strftime("%B %d, %Y")
        current_month = now.strftime("%B")
        current_year = str(now.year)

        # Get latest quarter from data if available
        if company_context:
            typed_context = CompanyContext.from_fmp_data(company_context)
            year, quarter = get_latest_quarter_from_data(typed_context)
        else:
            from er.utils.dates import get_latest_quarter
            year, quarter = get_latest_quarter()

        latest_quarter = format_quarter(year, quarter)
        quarter_context = format_quarters_for_prompt(year, quarter)

        # Get company name from profile
        profile = company_context.get("profile", {}) if company_context else {}
        company_name = profile.get("companyName", ticker)

        # Prepare company context JSON for prompts (key financial data)
        # This is the GROUND TRUTH data that subagents should use for financials
        context_for_prompt = {}
        if company_context:
            context_for_prompt = {
                "profile": {k: v for k, v in profile.items() if k in [
                    "companyName", "sector", "industry", "mktCap", "price", "beta"
                ]},
                "income_statement_quarterly": company_context.get("income_statement_quarterly", [])[:4],
                "revenue_product_segmentation": company_context.get("revenue_product_segmentation", [])[:4],
            }

            # Add transcripts for Management Emphasis analysis
            # Include latest quarter full text, truncate older quarters
            transcripts = company_context.get("transcripts", [])
            if transcripts:
                # Sort by date (most recent first)
                sorted_transcripts = sorted(
                    transcripts,
                    key=lambda t: (t.get("year", 0), t.get("quarter", 0)),
                    reverse=True,
                )
                transcript_data = []
                for i, t in enumerate(sorted_transcripts[:2]):  # Latest 2 quarters
                    entry = {
                        "quarter": f"Q{t.get('quarter')} {t.get('year')}",
                        "date": t.get("date"),
                    }
                    if i == 0:
                        # Latest quarter: include full text
                        entry["full_text"] = t.get("text") or t.get("content", "")
                    else:
                        # Older quarters: truncated
                        text = t.get("text") or t.get("content", "")
                        entry["summary"] = text[:3000] + "..." if len(text) > 3000 else text
                    transcript_data.append(entry)
                context_for_prompt["earnings_transcripts"] = transcript_data
                logger.info(f"[STAGE 3] Added {len(transcript_data)} transcripts to research context")

        company_context_json = json.dumps(context_for_prompt, indent=2, default=str)[:80000]  # Allow larger context for transcripts

        # =======================================================================
        # EXTRACT DISCOVERY'S RICH OUTPUT
        # =======================================================================
        # This is the key change: we pass Discovery's findings to Deep Research
        # so subagents VALIDATE and GO DEEPER rather than re-discover.

        discovery_lens_outputs = {}
        discovery_threats = []
        discovery_searches = []
        discovery_groups = []

        if self._discovery_output:
            # Extract lens outputs (competitor analysis, analyst views, etc.)
            # These come from Discovery's subagents
            if hasattr(self._discovery_output, 'lens_outputs'):
                discovery_lens_outputs = self._discovery_output.lens_outputs or {}

            # Extract external threats
            if hasattr(self._discovery_output, 'external_threats'):
                discovery_threats = self._discovery_output.external_threats or []

            # Extract searches already performed (audit trail)
            if hasattr(self._discovery_output, 'searches_performed'):
                discovery_searches = self._discovery_output.searches_performed or []

            # Extract research groups (contain shared_context)
            if hasattr(self._discovery_output, 'research_groups'):
                discovery_groups = self._discovery_output.research_groups or []

        # Format searches already done for the prompt
        searches_already_done_text = "Discovery has not logged any searches yet."
        if discovery_searches:
            search_lines = []
            for s in discovery_searches[:15]:  # Limit to 15 to avoid prompt bloat
                if isinstance(s, dict):
                    search_query = s.get('query', 'unknown query')
                    finding = s.get('key_finding', s.get('finding', 'no finding logged'))
                    search_lines.append(f"- Query: \"{search_query}\" → {finding}")
                else:
                    search_lines.append(f"- {s}")
            searches_already_done_text = "\n".join(search_lines)
            searches_already_done_text += f"\n\n(Total searches logged: {len(discovery_searches)})"

        # Build thread descriptions for orchestrator
        thread_descriptions = []
        for t in threads:
            questions = "\n".join(f"  - {q}" for q in t.research_questions)
            thread_descriptions.append(
                f"### {t.thread_name} (P{t.priority}, {t.thread_type})\n"
                f"Hypothesis: {t.value_driver_hypothesis}\n"
                f"Questions:\n{questions}"
            )

        # Define subagents - one per thread
        # Each gets the RICH THREAD_RESEARCH_PROMPT with Discovery context
        agents = {}
        for i, t in enumerate(threads):
            agent_name = f"research-{i+1}"
            questions = "\n".join(f"- {q}" for q in t.research_questions)

            # Build thread-specific Discovery context
            # Include relevant lens outputs for this thread
            discovery_context_for_thread = self._build_discovery_context_for_thread(
                thread=t,
                lens_outputs=discovery_lens_outputs,
                research_groups=discovery_groups,
            )

            # Find threats relevant to this thread
            relevant_threats_text = self._build_threats_for_thread(
                thread=t,
                threats=discovery_threats,
            )

            agents[agent_name] = AgentDefinition(
                description=f"Deep research on: {t.thread_name}",
                prompt=THREAD_RESEARCH_PROMPT.format(
                    thread_name=t.thread_name,
                    ticker=ticker,
                    company_name=company_name,
                    date=date_str,
                    current_month=current_month,
                    current_year=current_year,
                    latest_quarter=latest_quarter,
                    quarter_context=quarter_context,
                    company_context=company_context_json,
                    thread_type=t.thread_type,
                    thread_priority=t.priority,
                    hypothesis=t.value_driver_hypothesis,
                    questions=questions,
                    discovery_context=discovery_context_for_thread,
                    searches_already_done=searches_already_done_text,
                    relevant_threats=relevant_threats_text,
                ),
                tools=["WebSearch"],  # Claude Agent SDK web search
            )

        # Run orchestrator with subagents
        orchestrator_prompt = DEEP_RESEARCH_ORCHESTRATOR_PROMPT.format(
            threads="\n\n".join(thread_descriptions),
            ticker=ticker,
            company_name=company_name,
            date=date_str,
            current_month=current_month,
            current_year=current_year,
            latest_quarter=latest_quarter,
            quarter_context=quarter_context,
            company_context=company_context_json,
        )

        result_text = ""
        subagent_count = 0

        try:
            async for message in query(
                prompt=orchestrator_prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=["WebSearch", "Task"],
                    agents=agents,
                    permission_mode="bypassPermissions",
                )
            ):
                if hasattr(message, 'parent_tool_use_id') and message.parent_tool_use_id:
                    subagent_count += 1
                if hasattr(message, "result"):
                    result_text = str(message.result)

        except Exception as e:
            logger.error(f"Deep research failed: {e}")
            raise

        logger.info(f"[STAGE 3] Subagents spawned: {subagent_count}")

        # Parse results
        findings = []
        try:
            if "```json" in result_text:
                json_start = result_text.find("```json") + 7
                json_end = result_text.find("```", json_start)
                json_str = result_text[json_start:json_end].strip()
            else:
                start = result_text.find("{")
                end = result_text.rfind("}") + 1
                json_str = result_text[start:end]

            data = json.loads(json_str)

            for f_data in data.get("findings", []):
                # Find matching thread
                thread_name = f_data.get("thread_name", "")
                matching_thread = next(
                    (t for t in threads if t.thread_name == thread_name),
                    threads[0] if threads else None
                )

                if matching_thread:
                    finding = ResearchFinding(
                        thread=matching_thread,
                        key_findings=f_data.get("key_findings", []),
                        bull_case=f_data.get("bull_case", ""),
                        bear_case=f_data.get("bear_case", ""),
                        data_points=f_data.get("data_points", []),
                    )
                    findings.append(finding)

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse research results: {e}")
            # Create empty findings for each thread
            for t in threads:
                findings.append(ResearchFinding(thread=t, raw_content=result_text))

        # Save checkpoint
        checkpoint = self.output_dir / "stage3_research.json"
        checkpoint.write_text(json.dumps([
            {
                "thread": f.thread.thread_name,
                "findings": len(f.key_findings),
                "sources": len(f.sources),
            }
            for f in findings
        ], indent=2))

        return findings

    def _build_discovery_context_for_thread(
        self,
        thread: DiscoveredThread,
        lens_outputs: dict,
        research_groups: list,
    ) -> str:
        """Build Discovery context relevant to a specific thread.

        Extracts relevant findings from Discovery's lens outputs and research groups
        so the Deep Research subagent knows what was already found.
        """
        context_parts = []
        thread_name_lower = thread.thread_name.lower()

        # 1. Find the research group this thread belongs to
        for group in research_groups:
            if hasattr(group, 'vertical_ids'):
                # Check if this thread's ID is in the group
                # Also check by name matching as fallback
                group_verticals = getattr(group, 'vertical_ids', [])
                if thread.thread_name in group_verticals or any(
                    thread_name_lower in str(v).lower() for v in group_verticals
                ):
                    context_parts.append(f"**Research Group**: {getattr(group, 'name', 'Unknown')}")
                    if hasattr(group, 'shared_context') and group.shared_context:
                        context_parts.append(f"**Group Context**: {group.shared_context}")
                    if hasattr(group, 'key_questions') and group.key_questions:
                        context_parts.append("**Group Questions**:")
                        for q in group.key_questions[:5]:
                            context_parts.append(f"- {q}")
                    break

        # 2. Extract relevant lens outputs
        if lens_outputs:
            # Competitive analysis - always relevant
            competitive = lens_outputs.get('competitive_cross_reference', {})
            if competitive:
                context_parts.append("\n**Competitive Analysis (from Discovery)**:")
                competitors = competitive.get('competitors_analyzed', [])
                for c in competitors[:5]:
                    if isinstance(c, dict):
                        name = c.get('name', 'Unknown')
                        driver = c.get('valuation_driver', 'N/A')
                        context_parts.append(f"- {name}: valued for {driver}")

            # Analyst attention - always relevant
            analyst = lens_outputs.get('analyst_attention', {})
            if analyst:
                context_parts.append("\n**Analyst Views (from Discovery)**:")
                if analyst.get('consensus'):
                    context_parts.append(f"- Consensus: {analyst['consensus']}")
                if analyst.get('bull_thesis'):
                    context_parts.append(f"- Bull thesis: {analyst['bull_thesis'][:200]}...")
                if analyst.get('bear_thesis'):
                    context_parts.append(f"- Bear thesis: {analyst['bear_thesis'][:200]}...")
                if analyst.get('key_debate'):
                    context_parts.append(f"- Key debate: {analyst['key_debate'][:200]}...")

            # Recent developments - always relevant
            recent = lens_outputs.get('recent_developments', {})
            if recent:
                events = recent.get('events', [])
                if events:
                    context_parts.append("\n**Recent Developments (from Discovery)**:")
                    for e in events[:5]:
                        if isinstance(e, dict):
                            desc = e.get('description', str(e))
                            date = e.get('date', 'recent')
                            context_parts.append(f"- [{date}] {desc[:150]}")

            # Management emphasis
            mgmt = lens_outputs.get('management_emphasis', {})
            if mgmt:
                context_parts.append("\n**Management Emphasis (from Discovery)**:")
                if mgmt.get('top_priority_quote'):
                    context_parts.append(f"- Priority: {mgmt['top_priority_quote'][:200]}...")
                if mgmt.get('new_initiatives'):
                    for init in mgmt['new_initiatives'][:3]:
                        context_parts.append(f"- Initiative: {init}")

        if not context_parts:
            return "Discovery did not log detailed findings for this thread. Proceed with your own research."

        return "\n".join(context_parts)

    def _build_threats_for_thread(
        self,
        thread: DiscoveredThread,
        threats: list,
    ) -> str:
        """Build threat context relevant to a specific thread.

        Filters Discovery's external threats to those affecting this thread's vertical.
        """
        if not threats:
            return "No external threats were identified by Discovery for this thread."

        thread_name_lower = thread.thread_name.lower()
        relevant_threats = []

        for threat in threats:
            # Check if threat affects this thread's vertical
            affected = []
            if hasattr(threat, 'affected_verticals'):
                affected = threat.affected_verticals or []
            elif isinstance(threat, dict):
                affected = threat.get('affected_verticals', [])

            # Match by vertical name
            is_relevant = any(
                thread_name_lower in str(v).lower() or str(v).lower() in thread_name_lower
                for v in affected
            )

            # Also include high-impact threats that might be company-wide
            if not is_relevant and hasattr(threat, 'current_impact'):
                if threat.current_impact in ('material', 'severe'):
                    is_relevant = True
            elif not is_relevant and isinstance(threat, dict):
                if threat.get('current_impact') in ('material', 'severe'):
                    is_relevant = True

            if is_relevant:
                relevant_threats.append(threat)

        if not relevant_threats:
            return "No specific threats were mapped to this thread by Discovery."

        threat_lines = ["**Threats Discovery Identified**:"]
        for t in relevant_threats[:5]:
            if hasattr(t, 'threat_name'):
                name = t.threat_name
                ttype = getattr(t, 'threat_type', 'unknown')
                impact = getattr(t, 'current_impact', 'unknown')
                trajectory = getattr(t, 'trajectory', 'unknown')
                desc = getattr(t, 'description', '')[:200]
            elif isinstance(t, dict):
                name = t.get('threat_name', 'Unknown')
                ttype = t.get('threat_type', 'unknown')
                impact = t.get('current_impact', 'unknown')
                trajectory = t.get('trajectory', 'unknown')
                desc = t.get('description', '')[:200]
            else:
                continue

            threat_lines.append(f"\n**{name}** ({ttype})")
            threat_lines.append(f"- Impact: {impact}, Trajectory: {trajectory}")
            threat_lines.append(f"- {desc}")

        return "\n".join(threat_lines)

    async def _stage_synthesis(
        self,
        ticker: str,
        company_context: dict,
        findings: list[ResearchFinding],
    ) -> str:
        """Stage 4: Synthesis using Claude Agent SDK.

        Combines all thread analyses into a professional investment research report.
        """

        # Build research content
        sections = []
        for f in sorted(findings, key=lambda x: x.thread.priority):
            section = f"""
## [P{f.thread.priority}] {f.thread.thread_name} ({f.thread.thread_type})

**Core Question:** {f.thread.value_driver_hypothesis}

### Key Findings
"""
            for kf in f.key_findings[:10]:
                if isinstance(kf, dict):
                    section += f"- {kf.get('finding', str(kf))} [Source: {kf.get('source_url', 'N/A')}]\n"
                else:
                    section += f"- {kf}\n"

            if f.bull_case:
                section += f"\n**Bull Case:** {f.bull_case}\n"
            if f.bear_case:
                section += f"\n**Bear Case:** {f.bear_case}\n"

            sections.append(section)

        research_content = "\n---\n".join(sections)
        context_summary = json.dumps(company_context.get("profile", {}), indent=2)[:2000]

        prompt = SYNTHESIS_PROMPT.format(
            ticker=ticker,
            company_context=context_summary,
            research_findings=research_content,
        )

        # Run synthesis (no subagents needed)
        result_text = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                permission_mode="bypassPermissions",
            )
        ):
            if hasattr(message, "result"):
                result_text = str(message.result)

        return result_text

    async def _stage_verification(self, report: str) -> dict:
        """Stage 5: Verify claims using Claude Agent SDK."""

        prompt = VERIFIER_PROMPT.format(report=report[:10000])

        result_text = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["WebSearch"],
                permission_mode="bypassPermissions",
            )
        ):
            if hasattr(message, "result"):
                result_text = str(message.result)

        # Parse response
        try:
            if "```json" in result_text:
                json_start = result_text.find("```json") + 7
                json_end = result_text.find("```", json_start)
                json_str = result_text[json_start:json_end].strip()
            else:
                start = result_text.find("{")
                end = result_text.rfind("}") + 1
                json_str = result_text[start:end]
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return {"raw_result": result_text}


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entrypoint.

    Usage:
        python -m er.coordinator.anthropic_sdk_agent TICKER

    Example:
        python -m er.coordinator.anthropic_sdk_agent GOOGL
    """
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    if len(sys.argv) < 2:
        print("Usage: python -m er.coordinator.anthropic_sdk_agent TICKER")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    output_dir = Path(f"./output/{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY required")
        sys.exit(1)

    pipeline = ResearchPipeline(output_dir=output_dir)

    print(f"\n{'='*60}")
    print(f"EQUITY RESEARCH PIPELINE - Claude Agent SDK")
    print(f"{'='*60}")
    print(f"Ticker: {ticker}")
    print(f"Output: {output_dir}")
    print(f"{'='*60}\n")

    result = await pipeline.run(ticker)

    print(f"\n{'='*60}")
    print(f"COMPLETE")
    print(f"{'='*60}")
    print(f"Threads: {len(result.threads)}")
    print(f"Report: {len(result.report)} chars")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
