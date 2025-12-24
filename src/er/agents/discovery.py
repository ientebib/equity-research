"""
Discovery Agent (Stage 2).

Finds ALL potential value drivers using 7 lenses, not just official segments.
Uses Gemini 3 Deep Research with web search/grounding.

Model: Gemini 3 Pro Deep Research (with grounding/web search)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.gemini_client import GeminiClient
from er.llm.router import AgentRole
from er.types import (
    CompanyContext,
    DiscoveredThread,
    DiscoveryOutput,
    Phase,
    RunState,
    ThreadType,
)


# Discovery prompt template
DISCOVERY_PROMPT = """You are the Discovery Agent for an institutional equity research system.

TODAY'S DATE: {date}
COMPANY: {ticker} ({company_name})

## CRITICAL INSTRUCTION
DO NOT rely on training data for financials - use ONLY the provided CompanyContext below.
Your job is to find EVERYTHING that could matter for valuation - especially things NOT in official segment breakdowns.

## CompanyContext (Ground Truth Data)
{company_context}

## Your Task: Explore 7 Lenses

### Lens 1: Official Structure
What segments does the company officially report? Extract from the financials above.
This is your BASELINE, not your complete answer.

### Lens 2: Analyst Attention
What are analysts debating about this company? Bull vs bear arguments?
What questions did analysts ask on recent earnings calls?

### Lens 3: Recent Deals & Developments
What happened in the last 12 months? M&A, partnerships, product launches, regulatory events?

### Lens 4: Asset Inventory
What technologies, IP, or infrastructure does this company own that could be valuable?
What could be monetized that isn't being monetized yet?

### Lens 5: Competitive Cross-Reference
What are this company's competitors valued for?
Does {ticker} have similar assets? If competitors are valued for X, does {ticker} have X?

### Lens 6: Management Emphasis
From the earnings transcripts above: What did management spend time discussing?
What's the stated strategic priority they're telegraphing?

### Lens 7: Investor Questions
From the transcripts: What are investors asking about? What are they confused or skeptical about?

## Output Requirements

You MUST output valid JSON with this exact structure:

```json
{{
  "official_segments": ["list of official segments from 10-K"],
  "research_threads": [
    {{
      "name": "Short name for the thread",
      "description": "What this value driver is",
      "thread_type": "segment|optionality|cross_cutting",
      "priority": 1,
      "discovery_lens": "which lens found this (1-7)",
      "is_official_segment": true,
      "official_segment_name": "Name if official, null otherwise",
      "value_driver_hypothesis": "Why this matters for valuation",
      "research_questions": ["Specific questions to answer", "..."]
    }}
  ],
  "cross_cutting_themes": ["Themes that span multiple segments"],
  "optionality_candidates": ["Strategic options like Waymo"],
  "data_gaps": ["What we couldn't find"],
  "conflicting_signals": ["Where evidence conflicts"]
}}
```

## Hard Rules

1. Include ALL official segments as research threads (is_official_segment: true)
2. Also include non-official value drivers (is_official_segment: false)
3. For Google example: MUST find TPU external sales, Gemini API, YouTube dynamics, Waymo optionality
4. Every research_question must be specific and falsifiable
5. Priority 1 = most important, 5 = least important
6. If you only return official segments, you have FAILED

Be exhaustive. The goal is to NOT MISS anything that could matter."""


class DiscoveryAgent(Agent):
    """Stage 2: Discovery + Enrichment.

    Responsible for:
    1. Analyzing CompanyContext with 7 lenses
    2. Finding ALL value drivers (official + hidden)
    3. Using web search/grounding for recent information
    4. Outputting 3-5 prioritized research threads

    Uses Gemini 3 Deep Research for web-enhanced discovery.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Discovery Agent.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._gemini_client: GeminiClient | None = None

    @property
    def name(self) -> str:
        return "discovery"

    @property
    def role(self) -> str:
        return "Find all value drivers using 7 lenses with web search"

    async def _get_gemini_client(self) -> GeminiClient:
        """Get or create Gemini client for Deep Research."""
        if self._gemini_client is None:
            self._gemini_client = GeminiClient(
                api_key=self.settings.GEMINI_API_KEY,
            )
        return self._gemini_client

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        use_deep_research: bool = True,
        **kwargs: Any,
    ) -> DiscoveryOutput:
        """Execute Stage 2: Discovery with 7 lenses.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            use_deep_research: Whether to use Deep Research agent (vs regular grounding).

        Returns:
            DiscoveryOutput with all discovered research threads.
        """
        self.log_info(
            "Starting discovery",
            ticker=run_state.ticker,
            use_deep_research=use_deep_research,
        )

        run_state.phase = Phase.DISCOVERY

        # Build the prompt with company context
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prompt = DISCOVERY_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            company_context=company_context.to_prompt_string(max_tokens=15000),
        )

        # Get Gemini client
        gemini = await self._get_gemini_client()

        # Run discovery
        if use_deep_research:
            # Use Deep Research agent for comprehensive web search
            self.log_info("Using Deep Research agent", ticker=run_state.ticker)
            response = await gemini.deep_research(
                query=prompt,
                poll_interval=15.0,
                max_wait_seconds=600.0,
            )
        else:
            # Use regular completion with Google Search grounding
            self.log_info("Using grounded completion", ticker=run_state.ticker)
            from er.llm.base import LLMRequest

            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                model="gemini-3-pro",
                temperature=0.3,
                max_tokens=8000,
            )
            response = await gemini.complete_with_grounding(
                request,
                enable_google_search=True,
            )

        # Record cost (estimate for Deep Research)
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="google",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="discovery",
            )

        # Parse the response
        discovery_output = self._parse_response(
            response.content,
            company_context.evidence_ids,
        )

        # Update run state
        run_state.discovery_output = {
            "official_segments": discovery_output.official_segments,
            "research_threads": [
                {
                    "thread_id": t.thread_id,
                    "name": t.name,
                    "thread_type": t.thread_type.value,
                    "priority": t.priority,
                }
                for t in discovery_output.research_threads
            ],
            "cross_cutting_themes": discovery_output.cross_cutting_themes,
            "optionality_candidates": discovery_output.optionality_candidates,
        }

        self.log_info(
            "Completed discovery",
            ticker=run_state.ticker,
            thread_count=len(discovery_output.research_threads),
            official_count=len([t for t in discovery_output.research_threads if t.is_official_segment]),
            non_official_count=len([t for t in discovery_output.research_threads if not t.is_official_segment]),
        )

        return discovery_output

    def _parse_response(
        self,
        content: str,
        base_evidence_ids: tuple[str, ...],
    ) -> DiscoveryOutput:
        """Parse the LLM response into DiscoveryOutput.

        Args:
            content: Raw LLM response.
            base_evidence_ids: Evidence IDs from CompanyContext.

        Returns:
            Parsed DiscoveryOutput.
        """
        # Try to extract JSON from the response
        try:
            # Find JSON block
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            else:
                # Try to find JSON object directly
                start = content.find("{")
                end = content.rfind("}") + 1
                json_str = content[start:end]

            data = json.loads(json_str)

        except (json.JSONDecodeError, ValueError) as e:
            self.log_warning(f"Failed to parse JSON response: {e}")
            # Return minimal output with error
            return DiscoveryOutput(
                official_segments=[],
                research_threads=[],
                cross_cutting_themes=[],
                optionality_candidates=[],
                data_gaps=["Failed to parse discovery response"],
                conflicting_signals=[],
                evidence_ids=list(base_evidence_ids),
            )

        # Convert to DiscoveryOutput
        research_threads = []
        for t in data.get("research_threads", []):
            thread_type_str = t.get("thread_type", "segment")
            if thread_type_str == "segment":
                thread_type = ThreadType.SEGMENT
            elif thread_type_str == "optionality":
                thread_type = ThreadType.OPTIONALITY
            else:
                thread_type = ThreadType.CROSS_CUTTING

            thread = DiscoveredThread.create(
                name=t.get("name", "Unknown"),
                description=t.get("description", ""),
                thread_type=thread_type,
                priority=t.get("priority", 3),
                discovery_lens=t.get("discovery_lens", "1"),
                is_official_segment=t.get("is_official_segment", False),
                official_segment_name=t.get("official_segment_name"),
                value_driver_hypothesis=t.get("value_driver_hypothesis", ""),
                research_questions=t.get("research_questions", []),
                evidence_ids=list(base_evidence_ids),
            )
            research_threads.append(thread)

        return DiscoveryOutput(
            official_segments=data.get("official_segments", []),
            research_threads=research_threads,
            cross_cutting_themes=data.get("cross_cutting_themes", []),
            optionality_candidates=data.get("optionality_candidates", []),
            data_gaps=data.get("data_gaps", []),
            conflicting_signals=data.get("conflicting_signals", []),
            evidence_ids=list(base_evidence_ids),
        )

    async def close(self) -> None:
        """Close any open clients."""
        if self._gemini_client:
            await self._gemini_client.close()
            self._gemini_client = None
