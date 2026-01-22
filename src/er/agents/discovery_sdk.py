"""
Discovery Agent using Claude Agent SDK (Stage 2).

Uses the redesigned 7-Lens Framework to identify research threads.
Combines CompanyContext analysis with targeted web search.

This agent does "Mini DR" - lightweight research to ground hypotheses
before passing threads to full Deep Research.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from er.logging import get_logger
from er.types import CompanyContext

logger = get_logger(__name__)


# =============================================================================
# Output Types
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
class RejectedThread:
    """A thread that was considered but rejected."""
    name: str
    reason: str


@dataclass
class DiscoveryOutput:
    """Output from the Discovery Agent."""
    threads: list[ResearchThread]
    rejected_threads: list[RejectedThread] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    searches_performed: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threads": [t.to_dict() for t in self.threads],
            "rejected_threads": [{"name": r.name, "reason": r.reason} for r in self.rejected_threads],
            "data_gaps": self.data_gaps,
            "searches_performed": self.searches_performed,
        }


# =============================================================================
# System Prompt
# =============================================================================

DISCOVERY_SYSTEM_PROMPT = """You are the Discovery Agent for an institutional equity research system.

Your job is to identify 5-8 research threads that will be investigated in depth.
You have access to CompanyContext (fresh financial data) and web search.

## YOUR DATA SOURCES

1. **CompanyContext** (provided below) - This is FRESH data from financial APIs:
   - Latest quarterly earnings
   - Revenue segmentation
   - Recent earnings transcripts
   - News articles
   - Analyst estimates

2. **Web Search** - Use for information NOT in CompanyContext:
   - Current analyst sentiment/debates
   - Competitor valuations and strategies
   - Recent developments not yet in news feed
   - Market perception vs reality

## THE 7-LENS FRAMEWORK (in order)

### LENS 1: Official Segments (from CompanyContext)
Extract business segments from revenue_product_segmentation.
What are the reported divisions?

### LENS 2: Financial Performance (from CompanyContext)
How is each segment performing? Look at:
- Revenue growth rates
- Margin trends (if disclosed)
- Quarterly trajectory

### LENS 3: Management Emphasis (from CompanyContext transcripts)
What did the CEO/CFO emphasize in earnings calls?
- Topics mentioned repeatedly
- New initiatives highlighted
- Questions deflected or avoided

### LENS 4: Recent Developments (CompanyContext + SEARCH)
Check news in CompanyContext. Then SEARCH for:
- "{ticker} announcement {current_month} {current_year}"
- Any topics from Lens 3 that need verification

### LENS 5: Analyst Sentiment (MUST SEARCH)
YOU MUST web search for this - it's not in CompanyContext:
- "{ticker} analyst rating {current_month} {current_year}"
- "{ticker} bull bear case 2025"
What's the Street debate?

### LENS 6: Competitive Position (MUST SEARCH)
YOU MUST web search for this:
- "{ticker} vs [main competitor] {current_year}"
- "[competitor] valuation thesis"
How do competitors value similar assets?

### LENS 7: Hidden Value / Blind Spots (Synthesis)
Cross-reference all lenses. What might the market be missing?
- Assets not yet monetized
- Strategic optionalities
- Cross-cutting themes (AI, etc.)

## OUTPUT FORMAT

Output valid JSON with this structure:
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
        "Is this sustainable or one-time?",
        "How does this compare to Azure/AWS margins?"
      ]
    }
  ],
  "rejected_threads": [
    {
      "name": "Waymo autonomous vehicles",
      "reason": "Too early stage, minimal revenue impact in 2025-2026 timeframe"
    }
  ],
  "data_gaps": [
    "Segment-level operating margins not disclosed in 10-K"
  ],
  "searches_performed": [
    {"lens": "5", "query": "GOOGL analyst rating January 2026", "key_finding": "..."}
  ]
}
```

## CRITICAL RULES

1. **5-8 threads maximum** - Focus on what matters for valuation
2. **grounded_in is REQUIRED** - Every thread must cite evidence
3. **Lenses 5-6 REQUIRE web search** - Don't rely on training data
4. **Be specific** - Not "growth is good" but "Cloud grew 28% in Q4"
5. **Include rejected threads** - Show what you considered but dropped

Output ONLY the JSON. No preamble, no markdown code blocks."""


# =============================================================================
# Discovery Agent
# =============================================================================

class SDKDiscoveryAgent:
    """Discovery Agent using Claude with web search.

    Uses the 7-lens framework to identify research threads.
    Combines CompanyContext analysis with targeted web search.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_searches: int = 15,
    ) -> None:
        """Initialize the Discovery Agent.

        Args:
            api_key: Anthropic API key. If None, reads from env.
            model: Claude model to use.
            max_searches: Maximum web searches allowed.
        """
        import os

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY required")

        self.client = Anthropic(api_key=key)
        self.model = model
        self.max_searches = max_searches

    async def run(self, company_context: CompanyContext) -> DiscoveryOutput:
        """Execute Discovery on a company.

        Args:
            company_context: CompanyContext from Stage 1 (FMPClient).

        Returns:
            DiscoveryOutput with research threads.
        """
        ticker = company_context.symbol
        company_name = company_context.company_name

        logger.info(
            "Starting SDK Discovery",
            ticker=ticker,
            model=self.model,
            max_searches=self.max_searches,
        )

        # Build date context
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        # Build user prompt with CompanyContext
        user_prompt = self._build_user_prompt(
            company_context=company_context,
            ticker=ticker,
            company_name=company_name,
            today=today,
            current_month=current_month,
            current_year=current_year,
        )

        # Configure web search tool
        web_search_tool: dict[str, Any] = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": self.max_searches,
        }

        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=DISCOVERY_SYSTEM_PROMPT,
            tools=[web_search_tool],
            messages=[{"role": "user", "content": user_prompt}],
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

        # Log usage
        usage = response.usage
        logger.info(
            "Discovery API call complete",
            ticker=ticker,
            searches=search_count,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        # Parse response
        return self._parse_response(full_content, ticker)

    def _build_user_prompt(
        self,
        company_context: CompanyContext,
        ticker: str,
        company_name: str,
        today: str,
        current_month: str,
        current_year: str,
    ) -> str:
        """Build the user prompt with CompanyContext data."""

        # Get the discovery-formatted context
        context_str = company_context.for_discovery()

        prompt = f"""## DISCOVERY TASK

Analyze {ticker} ({company_name}) using the 7-Lens Framework.

TODAY: {today}
CURRENT MONTH/YEAR: {current_month} {current_year}

## COMPANY CONTEXT (Fresh data from financial APIs)

{context_str}

## INSTRUCTIONS

1. Work through all 7 lenses IN ORDER
2. For Lenses 1-3: Analyze the CompanyContext above
3. For Lens 4: Check CompanyContext news + do targeted searches
4. For Lenses 5-6: YOU MUST web search (this info is NOT in CompanyContext)
5. For Lens 7: Synthesize all findings

Remember:
- 5-8 threads maximum
- Every thread needs grounded_in evidence
- Include what you rejected and why
- Note any data gaps

Output your analysis as JSON."""

        return prompt

    def _parse_response(self, content: str, ticker: str) -> DiscoveryOutput:
        """Parse the LLM response into DiscoveryOutput."""

        # Try to extract JSON
        try:
            # Find JSON in response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON object found in response")

            json_str = content[start:end]
            data = json.loads(json_str)

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse Discovery response: {e}")
            return DiscoveryOutput(
                threads=[],
                data_gaps=[f"Failed to parse Discovery response: {e}"],
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

        # Sort by priority
        threads.sort(key=lambda x: x.priority)

        # Parse rejected threads
        rejected: list[RejectedThread] = []
        for r in data.get("rejected_threads", []):
            rejected.append(RejectedThread(
                name=r.get("name", ""),
                reason=r.get("reason", ""),
            ))

        # Parse data gaps and searches
        data_gaps = data.get("data_gaps", [])
        searches = data.get("searches_performed", [])

        logger.info(
            "Discovery parsing complete",
            ticker=ticker,
            thread_count=len(threads),
            rejected_count=len(rejected),
            search_count=len(searches),
        )

        return DiscoveryOutput(
            threads=threads,
            rejected_threads=rejected,
            data_gaps=data_gaps,
            searches_performed=searches,
        )


# =============================================================================
# Standalone Test
# =============================================================================

async def test_discovery(ticker: str = "GOOGL") -> None:
    """Test the Discovery Agent standalone."""
    import os
    from pathlib import Path

    from er.data.fmp_client import FMPClient
    from er.evidence.store import EvidenceStore
    from er.types import CompanyContext

    print("=" * 60)
    print(f"DISCOVERY AGENT TEST: {ticker}")
    print("=" * 60)

    # Check API keys
    if not os.environ.get("FMP_API_KEY"):
        print("ERROR: FMP_API_KEY not set")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    # Setup
    output_dir = Path("./output/discovery_test")
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
        print(f"  Evidence IDs: {len(company_context.evidence_ids)}")

        # Stage 2: Run Discovery
        print("\n[Stage 2] Running Discovery Agent...")
        agent = SDKDiscoveryAgent(max_searches=15)
        output = await agent.run(company_context)

        # Display results
        print("\n" + "=" * 60)
        print("DISCOVERY RESULTS")
        print("=" * 60)

        print(f"\nThreads discovered: {len(output.threads)}")
        for i, thread in enumerate(output.threads, 1):
            print(f"\n{i}. [{thread.priority}] {thread.name} ({thread.thread_type})")
            print(f"   Hypothesis: {thread.hypothesis[:80]}...")
            print(f"   Grounded in:")
            if thread.grounded_in.from_company_context:
                print(f"     - CompanyContext: {thread.grounded_in.from_company_context[:60]}...")
            if thread.grounded_in.from_transcript:
                print(f"     - Transcript: {thread.grounded_in.from_transcript[:60]}...")
            if thread.grounded_in.from_web_search:
                print(f"     - Web Search: {thread.grounded_in.from_web_search.query}")
            print(f"   Questions: {len(thread.questions)}")

        if output.rejected_threads:
            print(f"\nRejected threads: {len(output.rejected_threads)}")
            for r in output.rejected_threads:
                print(f"  - {r.name}: {r.reason[:60]}...")

        if output.data_gaps:
            print(f"\nData gaps: {len(output.data_gaps)}")
            for gap in output.data_gaps:
                print(f"  - {gap}")

        if output.searches_performed:
            print(f"\nSearches performed: {len(output.searches_performed)}")
            for s in output.searches_performed[:5]:  # Show first 5
                print(f"  - Lens {s.get('lens', '?')}: {s.get('query', '')[:50]}...")

        # Save output
        output_file = output_dir / f"discovery_{ticker}.json"
        output_file.write_text(json.dumps(output.to_dict(), indent=2))
        print(f"\nOutput saved to: {output_file}")

    finally:
        await evidence_store.close()


if __name__ == "__main__":
    import asyncio
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else "GOOGL"
    asyncio.run(test_discovery(ticker))
