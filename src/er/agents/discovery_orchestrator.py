"""
Discovery Orchestrator (Stage 2) - Opus 4.5 with Sonnet subagents.

Architecture (LEAN profile):
- Opus 4.5 orchestrator analyzes CompanyContext (Lenses 1-3, 7)
- Spawns 2-3 Sonnet subagents for web search (Lenses 4-6)
- Each subagent: max 5 web searches
- Total token budget: ~50K
- Time: 1-2 minutes
- Output: 5-8 research threads with grounded_in evidence
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from er.logging import get_logger
from er.types import CompanyContext

logger = get_logger(__name__)


# =============================================================================
# Output Types (shared with discovery_sdk.py)
# =============================================================================

@dataclass
class WebSearchEvidence:
    """Evidence from a web search."""
    query: str
    finding: str
    source_date: str | None = None


@dataclass
class GroundedEvidence:
    """Evidence grounding for a research thread."""
    from_company_context: str | None = None
    from_transcript: str | None = None
    from_web_search: WebSearchEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {}
        if self.from_company_context:
            result["from_company_context"] = self.from_company_context
        if self.from_transcript:
            result["from_transcript"] = self.from_transcript
        if self.from_web_search:
            result["from_web_search"] = {
                "query": self.from_web_search.query,
                "finding": self.from_web_search.finding,
                "source_date": self.from_web_search.source_date,
            }
        return result


@dataclass
class ResearchThread:
    """A research thread identified by Discovery."""
    name: str
    thread_type: str  # SEGMENT, OPTIONALITY, CROSS_CUTTING
    priority: int  # 1 = highest
    hypothesis: str
    grounded_in: GroundedEvidence
    questions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.thread_type,
            "priority": self.priority,
            "hypothesis": self.hypothesis,
            "grounded_in": self.grounded_in.to_dict(),
            "questions": self.questions,
        }


@dataclass
class DiscoveryOutput:
    """Output from the Discovery Orchestrator."""
    threads: list[ResearchThread]
    data_gaps: list[str] = field(default_factory=list)
    searches_performed: list[dict[str, str]] = field(default_factory=list)
    subagent_results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threads": [t.to_dict() for t in self.threads],
            "data_gaps": self.data_gaps,
            "searches_performed": self.searches_performed,
        }


# =============================================================================
# Subagent Prompts
# =============================================================================

ANALYST_SENTIMENT_PROMPT = """You are a research subagent focused on ANALYST SENTIMENT.

Search the web to understand:
1. What is the current analyst consensus on {ticker}?
2. What are the bull and bear cases being debated?
3. Any recent rating changes or price target revisions?

Use these exact search queries (substitute actual values):
- "{ticker} analyst rating {current_month} {current_year}"
- "{ticker} price target {current_year}"
- "{ticker} bull bear case"

You have a maximum of 5 web searches. Be targeted.

Output JSON with:
```json
{{
  "consensus": "Overweight/Hold/etc",
  "bull_case": "Key bull thesis",
  "bear_case": "Key bear thesis",
  "recent_changes": ["List of notable rating changes"],
  "searches": [
    {{"query": "actual query used", "finding": "what you found", "source_date": "2026-01-10"}}
  ]
}}
```

Output ONLY the JSON."""

COMPETITOR_POSITION_PROMPT = """You are a research subagent focused on COMPETITIVE POSITIONING.

Search the web to understand:
1. How are {ticker}'s main competitors being valued?
2. What are competitors emphasizing that {ticker} isn't?
3. Any competitive threats or advantages emerging?

Use these search queries:
- "{ticker} vs {competitor} {current_year}"
- "{competitor} valuation thesis"
- "{ticker} market share {segment}"

You have a maximum of 5 web searches. Be targeted.

Output JSON with:
```json
{{
  "main_competitors": ["List"],
  "competitive_dynamics": "Key insight",
  "valuation_comparison": "How peers are valued",
  "emerging_threats": ["Any new threats"],
  "searches": [
    {{"query": "actual query used", "finding": "what you found", "source_date": "2026-01-10"}}
  ]
}}
```

Output ONLY the JSON."""

RECENT_DEVELOPMENTS_PROMPT = """You are a research subagent focused on RECENT DEVELOPMENTS.

Search for anything mentioned in the company context that needs verification or expansion:
1. Recent announcements, M&A, partnerships
2. Regulatory developments
3. Product launches or strategy shifts

Use targeted searches like:
- "{ticker} announcement {current_month} {current_year}"
- "{ticker} {specific_topic_from_context}"

You have a maximum of 5 web searches. Be targeted.

Output JSON with:
```json
{{
  "key_developments": [
    {{"topic": "...", "detail": "...", "significance": "..."}}
  ],
  "searches": [
    {{"query": "actual query used", "finding": "what you found", "source_date": "2026-01-10"}}
  ]
}}
```

Output ONLY the JSON."""


# =============================================================================
# Orchestrator System Prompt
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the Discovery Orchestrator for institutional equity research.

You coordinate research to identify 5-8 high-priority research threads.

## YOUR ROLE

You analyze CompanyContext directly (Lenses 1-3, 7) and synthesize subagent findings (Lenses 4-6).

## THE 7-LENS FRAMEWORK

**YOU analyze (from CompanyContext):**
- LENS 1: Official Segments - What does the company say it does?
- LENS 2: Financial Performance - Revenue growth, margins, trajectory
- LENS 3: Management Emphasis - What CEO/CFO emphasized in transcripts
- LENS 7: Hidden Value / Blind Spots - What might the market be missing?

**Subagents search for (results provided):**
- LENS 4: Recent Developments - News, M&A, partnerships
- LENS 5: Analyst Sentiment - Street consensus and debates
- LENS 6: Competitive Position - How competitors are valued

## OUTPUT FORMAT

Output valid JSON:
```json
{
  "threads": [
    {
      "name": "Google Cloud Margin Expansion",
      "type": "SEGMENT",
      "priority": 1,
      "hypothesis": "Cloud margins accelerating faster than Street expects",
      "grounded_in": {
        "from_company_context": "Q4 operating margin 11.2% vs Q3 9.4%",
        "from_transcript": "CFO mentioned 'operating leverage' 4 times",
        "from_web_search": {
          "query": "Google Cloud margin analyst expectations 2026",
          "finding": "Street consensus is 12% by Q4 2026",
          "source_date": "2026-01-10"
        }
      },
      "questions": [
        "What is driving the margin improvement?",
        "Is this sustainable or one-time?"
      ]
    }
  ],
  "data_gaps": ["Segment-level margins not disclosed"]
}
```

## CRITICAL RULES

1. **5-8 threads** - No more, no less
2. **grounded_in is REQUIRED** - Every thread must cite evidence
3. **Include ALL optionalities** - Don't pre-judge materiality
4. **Be specific** - Not "growth is good" but "Cloud grew 28% in Q4"
5. **Synthesize subagent findings** - Use them to ground your hypotheses

Output ONLY the JSON."""


# =============================================================================
# Discovery Orchestrator
# =============================================================================

class DiscoveryOrchestrator:
    """Opus 4.5 orchestrator with Sonnet subagents for Discovery.

    LEAN profile:
    - Orchestrator: Opus 4.5 (smart planning, synthesis)
    - Subagents: Sonnet (fast web search)
    - Max subagents: 3
    - Max searches per subagent: 5
    """

    def __init__(
        self,
        api_key: str | None = None,
        orchestrator_model: str = "claude-opus-4-5-20251101",
        subagent_model: str = "claude-sonnet-4-5-20250929",
        max_subagent_searches: int = 5,
    ) -> None:
        import os

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY required")

        self.client = Anthropic(api_key=key)
        self.orchestrator_model = orchestrator_model
        self.subagent_model = subagent_model
        self.max_subagent_searches = max_subagent_searches

    async def run(self, company_context: CompanyContext) -> DiscoveryOutput:
        """Execute Discovery with orchestrator pattern.

        Args:
            company_context: CompanyContext from Stage 1.

        Returns:
            DiscoveryOutput with research threads.
        """
        ticker = company_context.symbol
        company_name = company_context.company_name

        logger.info(
            "Starting Discovery Orchestrator",
            ticker=ticker,
            orchestrator=self.orchestrator_model,
            subagent=self.subagent_model,
        )

        # Build date context
        now = datetime.now(timezone.utc)
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        # Identify main competitor from context (simple heuristic)
        main_competitor = self._identify_competitor(company_context)

        # ==============================================================
        # STEP 1: Run subagents in parallel (Lenses 4-6)
        # ==============================================================
        logger.info("Spawning subagents for Lenses 4-6")

        subagent_tasks = [
            self._run_subagent(
                "analyst_sentiment",
                ANALYST_SENTIMENT_PROMPT.format(
                    ticker=ticker,
                    current_month=current_month,
                    current_year=current_year,
                ),
            ),
            self._run_subagent(
                "competitor_position",
                COMPETITOR_POSITION_PROMPT.format(
                    ticker=ticker,
                    competitor=main_competitor,
                    current_year=current_year,
                    segment="cloud",  # TODO: Extract from context
                ),
            ),
            self._run_subagent(
                "recent_developments",
                RECENT_DEVELOPMENTS_PROMPT.format(
                    ticker=ticker,
                    current_month=current_month,
                    current_year=current_year,
                ),
            ),
        ]

        subagent_results = await asyncio.gather(*subagent_tasks, return_exceptions=True)

        # Process results
        subagent_data: dict[str, Any] = {}
        all_searches: list[dict[str, str]] = []

        for name, result in zip(
            ["analyst_sentiment", "competitor_position", "recent_developments"],
            subagent_results,
        ):
            if isinstance(result, Exception):
                logger.warning(f"Subagent {name} failed: {result}")
                subagent_data[name] = {"error": str(result)}
            else:
                subagent_data[name] = result
                # Collect searches for audit
                if isinstance(result, dict) and "searches" in result:
                    for s in result["searches"]:
                        s["subagent"] = name
                        all_searches.append(s)

        logger.info(
            "Subagents complete",
            total_searches=len(all_searches),
        )

        # ==============================================================
        # STEP 2: Orchestrator synthesizes (Opus 4.5)
        # ==============================================================
        logger.info("Orchestrator synthesizing threads")

        context_str = company_context.for_discovery()

        orchestrator_prompt = f"""## DISCOVERY TASK

Analyze {ticker} ({company_name}) and identify 5-8 research threads.

TODAY: {now.strftime("%Y-%m-%d")}

## COMPANY CONTEXT (Lenses 1-3)

{context_str}

## SUBAGENT FINDINGS (Lenses 4-6)

### Analyst Sentiment (Lens 5)
{json.dumps(subagent_data.get("analyst_sentiment", {}), indent=2)}

### Competitive Position (Lens 6)
{json.dumps(subagent_data.get("competitor_position", {}), indent=2)}

### Recent Developments (Lens 4)
{json.dumps(subagent_data.get("recent_developments", {}), indent=2)}

## INSTRUCTIONS

1. Analyze CompanyContext for Lenses 1-3
2. Cross-reference with subagent findings
3. Apply Lens 7 (Hidden Value / Blind Spots)
4. Output 5-8 research threads with grounded_in evidence

Include ALL interesting optionalities. Don't pre-judge what's material.

Output your analysis as JSON."""

        response = self.client.messages.create(
            model=self.orchestrator_model,
            max_tokens=16000,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": orchestrator_prompt}],
        )

        # Extract text
        full_content = ""
        for block in response.content:
            if block.type == "text":
                full_content += block.text

        logger.info(
            "Orchestrator complete",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # Parse response
        output = self._parse_response(full_content, ticker)
        output.searches_performed = all_searches
        output.subagent_results = subagent_data

        return output

    async def _run_subagent(self, name: str, prompt: str) -> dict[str, Any]:
        """Run a Sonnet subagent with web search.

        Args:
            name: Subagent identifier.
            prompt: The prompt for the subagent.

        Returns:
            Parsed JSON response from subagent.
        """
        logger.info(f"Running subagent: {name}")

        web_search_tool: dict[str, Any] = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": self.max_subagent_searches,
        }

        response = self.client.messages.create(
            model=self.subagent_model,
            max_tokens=4000,
            tools=[web_search_tool],
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract text content
        content_parts: list[str] = []
        search_count = 0

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "web_search_tool_result":
                search_count += 1

        full_content = "\n".join(content_parts)

        logger.info(
            f"Subagent {name} complete",
            searches=search_count,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # Parse JSON
        try:
            start = full_content.find("{")
            end = full_content.rfind("}") + 1
            if start == -1 or end == 0:
                return {"raw": full_content, "error": "No JSON found"}
            return json.loads(full_content[start:end])
        except json.JSONDecodeError as e:
            return {"raw": full_content, "error": str(e)}

    def _identify_competitor(self, context: CompanyContext) -> str:
        """Identify main competitor from context (simple heuristic)."""
        # Map common companies to their main competitor
        competitors = {
            "GOOGL": "Microsoft",
            "GOOG": "Microsoft",
            "MSFT": "Google",
            "AMZN": "Microsoft",
            "META": "TikTok",
            "AAPL": "Samsung",
            "NVDA": "AMD",
        }
        return competitors.get(context.symbol, "competitors")

    def _parse_response(self, content: str, ticker: str) -> DiscoveryOutput:
        """Parse the orchestrator response into DiscoveryOutput."""
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON object found")
            data = json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse orchestrator response: {e}")
            return DiscoveryOutput(
                threads=[],
                data_gaps=[f"Parse error: {e}"],
            )

        # Parse threads
        threads: list[ResearchThread] = []
        for t in data.get("threads", []):
            grounded = t.get("grounded_in", {})
            web_search_ev = None
            if grounded.get("from_web_search"):
                ws = grounded["from_web_search"]
                web_search_ev = WebSearchEvidence(
                    query=ws.get("query", ""),
                    finding=ws.get("finding", ""),
                    source_date=ws.get("source_date"),
                )

            thread = ResearchThread(
                name=t.get("name", "Unknown"),
                thread_type=t.get("type", "SEGMENT"),
                priority=t.get("priority", 5),
                hypothesis=t.get("hypothesis", ""),
                grounded_in=GroundedEvidence(
                    from_company_context=grounded.get("from_company_context"),
                    from_transcript=grounded.get("from_transcript"),
                    from_web_search=web_search_ev,
                ),
                questions=t.get("questions", []),
            )
            threads.append(thread)

        threads.sort(key=lambda x: x.priority)

        logger.info(
            "Orchestrator parsing complete",
            ticker=ticker,
            thread_count=len(threads),
        )

        return DiscoveryOutput(
            threads=threads,
            data_gaps=data.get("data_gaps", []),
        )


# =============================================================================
# Standalone Test
# =============================================================================

async def test_orchestrator(ticker: str = "GOOGL") -> None:
    """Test the Discovery Orchestrator standalone."""
    import os
    from pathlib import Path

    from er.data.fmp_client import FMPClient
    from er.evidence.store import EvidenceStore

    print("=" * 60)
    print(f"DISCOVERY ORCHESTRATOR TEST: {ticker}")
    print("=" * 60)

    if not os.environ.get("FMP_API_KEY"):
        print("ERROR: FMP_API_KEY not set")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    output_dir = Path("./output/orchestrator_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    evidence_store = EvidenceStore(output_dir / "cache")
    await evidence_store.init()

    try:
        # Stage 1: Get CompanyContext
        print("\n[Stage 1] Fetching CompanyContext...")
        fmp_client = FMPClient(evidence_store)
        raw_context = await fmp_client.get_full_context(ticker)
        company_context = CompanyContext.from_fmp_data(raw_context)
        print(f"  Company: {company_context.company_name}")
        print(f"  Sector: {company_context.sector}")

        # Stage 2: Run Orchestrator
        print("\n[Stage 2] Running Discovery Orchestrator...")
        orchestrator = DiscoveryOrchestrator()
        output = await orchestrator.run(company_context)

        # Display results
        print("\n" + "=" * 60)
        print("DISCOVERY RESULTS")
        print("=" * 60)

        print(f"\nThreads discovered: {len(output.threads)}")
        for i, thread in enumerate(output.threads, 1):
            print(f"\n{i}. [{thread.priority}] {thread.name} ({thread.thread_type})")
            print(f"   Hypothesis: {thread.hypothesis[:80]}...")
            print("   Grounded in:")
            if thread.grounded_in.from_company_context:
                ctx = thread.grounded_in.from_company_context[:60]
                print(f"     - CompanyContext: {ctx}...")
            if thread.grounded_in.from_transcript:
                tr = thread.grounded_in.from_transcript[:60]
                print(f"     - Transcript: {tr}...")
            if thread.grounded_in.from_web_search:
                print(f"     - Web: {thread.grounded_in.from_web_search.query}")
            print(f"   Questions: {len(thread.questions)}")

        if output.data_gaps:
            print(f"\nData gaps: {len(output.data_gaps)}")
            for gap in output.data_gaps:
                print(f"  - {gap}")

        print(f"\nTotal searches performed: {len(output.searches_performed)}")
        for s in output.searches_performed[:5]:
            print(f"  - [{s.get('subagent', '?')}] {s.get('query', '')[:50]}...")

        # Save output
        output_file = output_dir / f"orchestrator_{ticker}.json"
        output_file.write_text(json.dumps(output.to_dict(), indent=2))
        print(f"\nOutput saved to: {output_file}")

    finally:
        await evidence_store.close()


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "GOOGL"
    asyncio.run(test_orchestrator(ticker))
