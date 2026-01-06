"""
External Discovery Agent (Stage 2B).

Finds competitive intelligence, news, and market context using web search.
Focuses on Pillar 2: What's happening OUTSIDE the company.

Architecture: Evidence-First approach
1. Build deterministic query plan
2. Execute searches via WebResearchService (returns EvidenceCards, not full pages)
3. Feed EvidenceCards to LLM for analysis (no web_search tool in LLM call)

This avoids token explosion from full page content in LLM context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.router import AgentRole
from er.types import (
    CompanyContext,
    DiscoveredThread,
    Phase,
    RunState,
    ThreadBrief,
    ThreadType,
    generate_id,
)


# External Discovery prompt - now receives pre-fetched EvidenceCards
EXTERNAL_DISCOVERY_PROMPT = """You are the External Discovery Agent for an institutional equity research system.

## ⚠️ DATE AWARENESS ⚠️

**TODAY IS: {date}**
**CURRENT MONTH: {current_month} {current_year}**

---

TICKER: {ticker}
COMPANY: {company_name}
SECTOR: {sector}
INDUSTRY: {industry}

---

## YOUR MISSION

Analyze the pre-fetched web research below to find everything happening OUTSIDE this company that affects its investment thesis:
- What competitors announced recently
- What the market discourse is about
- What analysts are debating
- What regulatory/industry changes matter
- What the "variant perception" opportunities are

You work alongside an Internal Discovery agent who analyzes company financials.
Your focus is EXTERNAL context only.

## KNOWN COMPETITORS

{competitors}

---

## PRE-FETCHED WEB RESEARCH

The following EvidenceCards summarize web pages that were fetched for you.
Each card has an Evidence ID for citation tracking.

{evidence_cards}

---

## OUTPUT FORMAT

Based on the evidence cards above, output this JSON structure:

```json
{{
  "meta": {{
    "analysis_date": "{date}",
    "ticker": "{ticker}",
    "company_name": "{company_name}",
    "focus": "external_context"
  }},

  "competitor_developments": [
    {{
      "competitor": "Company Name",
      "announcement": "What they announced",
      "date": "YYYY-MM-DD",
      "source": "Bloomberg|Reuters|etc",
      "evidence_id": "ev_xxx",
      "implication_for_ticker": "How this affects {ticker}",
      "threat_level": "high|medium|low"
    }}
  ],

  "industry_news": [
    {{
      "headline": "...",
      "date": "YYYY-MM-DD",
      "source": "...",
      "evidence_id": "ev_xxx",
      "affected_companies": ["{ticker}", "CompetitorA"],
      "implication": "..."
    }}
  ],

  "analyst_sentiment": {{
    "consensus": "bullish|neutral|bearish",
    "average_rating": "Buy|Hold|Sell",
    "recent_changes": [
      {{
        "analyst": "...",
        "date": "YYYY-MM-DD",
        "action": "upgrade|downgrade|initiate",
        "from_to": "Hold → Buy",
        "evidence_id": "ev_xxx"
      }}
    ],
    "bull_thesis": "Specific bull case",
    "bear_thesis": "Specific bear case",
    "key_debates": ["debate topic 1", "debate topic 2"]
  }},

  "market_discourse": {{
    "major_stories": [
      {{
        "headline": "...",
        "date": "YYYY-MM-DD",
        "sentiment": "positive|negative|neutral",
        "evidence_id": "ev_xxx"
      }}
    ],
    "controversies": ["if any"],
    "retail_sentiment": "bullish|bearish|mixed",
    "viral_topics": ["what people are talking about"]
  }},

  "strategic_shifts": [
    {{
      "shift_type": "internal_to_external|new_market|new_product|acquisition",
      "description": "Description of the strategic shift",
      "date_announced": "YYYY-MM-DD",
      "source": "Bloomberg|Reuters|Official PR",
      "evidence_id": "ev_xxx",
      "competitive_implication": "How this changes competitive dynamics",
      "is_priced_in": "yes|no|partially",
      "materiality": "high|medium|low"
    }}
  ],

  "variant_perceptions": [
    {{
      "topic": "Topic where consensus may be wrong",
      "consensus_view": "What most investors/analysts believe",
      "variant_view": "Alternative view supported by evidence",
      "evidence": "Specific evidence supporting the variant view",
      "evidence_ids": ["ev_xxx", "ev_yyy"],
      "trigger_event": "What would prove the variant view correct",
      "confidence": "medium"
    }}
  ],

  "research_threads_suggested": [
    {{
      "name": "Suggested vertical name",
      "source_lens": "which lens found this",
      "why_it_matters": "Why this deserves its own research thread",
      "research_questions": ["Question 1", "Question 2"],
      "evidence_ids": ["ev_xxx"],
      "priority": 1
    }}
  ],

  "critical_external_context": [
    "Key external fact 1 that internal discovery might miss",
    "Key external fact 2"
  ]
}}
```

## RULES

1. **CITE EVIDENCE IDs** - Every finding must reference an evidence_id from the cards above.

2. **FOCUS ON EXTERNAL** - You are NOT analyzing the company's financials.

3. **BE SPECIFIC** - Not "competitors are doing well" but "Microsoft announced X on DATE"

4. **VARIANT PERCEPTION IS KEY** - The most valuable output is variant_perceptions.

5. **ONLY USE PROVIDED EVIDENCE** - Do not make claims not supported by the evidence cards.

---

Output ONLY the JSON. No preamble, no explanation."""


@dataclass
class ExternalDiscoveryOutput:
    """Output from External Discovery Agent.

    Contains competitive intelligence, news, and market context.
    Designed to be merged with Internal Discovery output.
    """

    competitor_developments: list[dict[str, Any]]
    industry_news: list[dict[str, Any]]
    analyst_sentiment: dict[str, Any]
    market_discourse: dict[str, Any]
    strategic_shifts: list[dict[str, Any]]  # Business model changes (may be 2-6 months old but material)
    variant_perceptions: list[dict[str, Any]]
    suggested_threads: list[dict[str, Any]]
    critical_external_context: list[str]
    searches_performed: list[dict[str, str]]

    # Metadata
    analysis_date: str = ""
    evidence_ids: list[str] = field(default_factory=list)


class ExternalDiscoveryAgent(Agent):
    """Stage 2B: External Discovery.

    Responsible for:
    1. Scanning competitor announcements and developments
    2. Finding industry news and trends
    3. Understanding analyst debates and sentiment
    4. Identifying market discourse and viral topics
    5. Surfacing variant perception opportunities

    Architecture: Evidence-First approach
    1. Build deterministic query plan
    2. Execute searches via WebResearchService (returns EvidenceCards, not full pages)
    3. Feed EvidenceCards to LLM for analysis (no web_search tool in LLM call)

    This avoids token explosion from full page content in LLM context.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the External Discovery Agent.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._web_research_service = None

    @property
    def name(self) -> str:
        return "external_discovery"

    @property
    def role(self) -> str:
        return "Find competitive intelligence, news, and market context"

    async def _get_web_research_service(self):
        """Get or create WebResearchService."""
        if self._web_research_service is None:
            from er.retrieval.service import WebResearchService
            self._web_research_service = WebResearchService(
                llm_router=self.llm_router,
                evidence_store=self.evidence_store,
                workspace_store=self.workspace_store,
            )
        return self._web_research_service

    def _get_competitors(self, company_context: CompanyContext) -> list[str]:
        """Extract likely competitors from company context.

        Uses sector/industry to suggest competitors.
        """
        industry = company_context.profile.get("industry", "")
        sector = company_context.profile.get("sector", "")

        # Common competitor mappings by industry
        competitor_map = {
            "Internet Content & Information": ["Microsoft", "Meta", "Amazon", "Apple", "OpenAI"],
            "Software—Infrastructure": ["Microsoft", "Amazon", "Oracle", "Salesforce"],
            "Semiconductors": ["NVIDIA", "AMD", "Intel", "Qualcomm", "Broadcom"],
            "Internet Retail": ["Amazon", "Walmart", "Alibaba", "eBay"],
            "Consumer Electronics": ["Apple", "Samsung", "Microsoft", "Sony"],
            "Cloud Computing": ["Amazon AWS", "Microsoft Azure", "Google Cloud", "Oracle"],
        }

        # Get competitors for this industry
        competitors = competitor_map.get(industry, [])

        # Remove the company itself from competitors
        company_name = company_context.company_name.lower()
        competitors = [c for c in competitors if c.lower() not in company_name]

        # If no specific mapping, return generic large tech
        if not competitors:
            competitors = ["Microsoft", "Amazon", "Apple", "Meta"]

        return competitors[:5]  # Limit to 5 competitors

    def _build_query_plan(
        self,
        company_context: CompanyContext,
        competitors: list[str],
    ) -> list[str]:
        """Build deterministic search query plan.

        Returns a list of search queries covering all lenses:
        - Competitor developments
        - Industry news (last 90 days)
        - Analyst upgrades/downgrades
        - Product launches
        - Regulatory changes
        """
        ticker = company_context.symbol
        company_name = company_context.company_name
        industry = company_context.profile.get("industry", "Technology")
        sector = company_context.profile.get("sector", "Technology")

        now = datetime.now(timezone.utc)
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        queries = []

        # Lens 1: Competitor developments
        for competitor in competitors[:3]:  # Top 3 competitors
            queries.append(f"{competitor} announcement {current_month} {current_year}")
            queries.append(f"{competitor} earnings {current_year}")

        # Lens 2: Industry news
        queries.append(f"{industry} market news {current_month} {current_year}")
        queries.append(f"{industry} regulation {current_year}")
        queries.append(f"{sector} trends {current_year}")

        # Lens 3: Analyst sentiment
        queries.append(f"{ticker} analyst upgrade downgrade {current_month} {current_year}")
        queries.append(f"{ticker} price target {current_year}")
        queries.append(f"{ticker} bull case bear case")

        # Lens 4: Market discourse
        queries.append(f"{ticker} news {current_month} {current_year}")
        queries.append(f"{company_name} controversy {current_year}")

        # Lens 5: Strategic shifts
        queries.append(f"{company_name} new business model {current_year}")
        queries.append(f"{company_name} strategic pivot {current_year}")
        queries.append(f"{ticker} entering new market {current_year}")

        # Lens 6: Variant perceptions
        queries.append(f"{ticker} underappreciated hidden value")
        queries.append(f"{ticker} what market is missing")

        return queries[:25]  # Max 25 queries

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        **kwargs: Any,
    ) -> ExternalDiscoveryOutput:
        """Execute External Discovery using Evidence-First approach.

        1. Build deterministic query plan
        2. Execute searches via WebResearchService (fetches URLs, creates EvidenceCards)
        3. Feed EvidenceCards to LLM for analysis (no web_search tool)

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.

        Returns:
            ExternalDiscoveryOutput with competitive intelligence and market context.
        """
        self.log_info(
            "Starting external discovery (evidence-first)",
            ticker=run_state.ticker,
        )

        # Get competitors
        competitors = self._get_competitors(company_context)
        competitors_str = "\n".join(f"- {c}" for c in competitors)

        # Build query plan
        queries = self._build_query_plan(company_context, competitors)
        self.log_info(
            "Built query plan",
            ticker=run_state.ticker,
            query_count=len(queries),
        )

        # Execute searches via WebResearchService
        web_service = await self._get_web_research_service()
        research_results = await web_service.research_batch(
            queries=queries,
            max_results_per_query=3,
            recency_days=90,
            max_total_queries=25,
        )

        # Collect all evidence cards
        all_cards = []
        all_evidence_ids = list(company_context.evidence_ids)
        searches_performed = []

        for result in research_results:
            all_cards.extend(result.evidence_cards)
            all_evidence_ids.extend(result.evidence_ids)
            searches_performed.append({
                "query": result.query,
                "urls_found": [r.url for r in result.search_results],
                "cards_generated": len(result.evidence_cards),
            })

        # Deduplicate evidence IDs
        all_evidence_ids = list(set(all_evidence_ids))

        self.log_info(
            "Web research complete",
            ticker=run_state.ticker,
            total_cards=len(all_cards),
            total_evidence_ids=len(all_evidence_ids),
        )

        # Format evidence cards for prompt
        evidence_cards_str = self._format_evidence_cards(all_cards)

        # Build prompt with pre-fetched evidence
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        prompt = EXTERNAL_DISCOVERY_PROMPT.format(
            date=today,
            current_month=current_month,
            current_year=current_year,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            sector=company_context.profile.get("sector", "Technology"),
            industry=company_context.profile.get("industry", "Technology"),
            competitors=competitors_str,
            evidence_cards=evidence_cards_str,
        )

        # Call LLM WITHOUT web_search tool - just analyze the evidence cards
        response = await self.llm_router.call(
            role=AgentRole.SYNTHESIS,  # Use strong model for analysis
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8000,
            response_format={"type": "json_object"},
        )

        # Parse response
        output = self._parse_response(
            response.get("content", ""),
            tuple(all_evidence_ids),
        )

        # Add searches performed
        output.searches_performed = searches_performed

        # Generate and store ThreadBriefs
        thread_briefs = self.generate_thread_briefs(output)
        if self.workspace_store and thread_briefs:
            for brief in thread_briefs:
                self.workspace_store.put_artifact(
                    artifact_type="thread_brief",
                    producer=self.name,
                    json_obj=brief.to_dict(),
                    summary=f"External ThreadBrief: {brief.rationale[:100]}...",
                    evidence_ids=brief.key_evidence_ids,
                )
            self.log_info(
                "Stored external thread briefs",
                count=len(thread_briefs),
            )

        self.log_info(
            "Completed external discovery",
            ticker=run_state.ticker,
            competitor_developments=len(output.competitor_developments),
            variant_perceptions=len(output.variant_perceptions),
            suggested_threads=len(output.suggested_threads),
            thread_briefs=len(thread_briefs),
            evidence_ids=len(output.evidence_ids),
        )

        return output

    def _format_evidence_cards(self, cards) -> str:
        """Format evidence cards for LLM prompt."""
        if not cards:
            return "(No web research results available)"

        parts = []
        for i, card in enumerate(cards, 1):
            parts.append(f"""
### Evidence Card {i}
- **Evidence ID**: {card.raw_evidence_id}
- **Source**: {card.source}
- **Title**: {card.title}
- **URL**: {card.url}
- **Relevance**: {card.relevance_score:.0%}

**Summary**: {card.summary}

**Key Facts**:
{chr(10).join(f"  - {f}" for f in card.key_facts) if card.key_facts else "  (none)"}
""")
        return "\n".join(parts)

    def _parse_response(
        self,
        content: str,
        base_evidence_ids: tuple[str, ...],
    ) -> ExternalDiscoveryOutput:
        """Parse the LLM response into ExternalDiscoveryOutput."""
        try:
            # Extract JSON from response
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            else:
                start = content.find("{")
                end = content.rfind("}") + 1
                json_str = content[start:end]

            data = json.loads(json_str)

        except (json.JSONDecodeError, ValueError) as e:
            self.log_warning(f"Failed to parse JSON response: {e}")
            return ExternalDiscoveryOutput(
                competitor_developments=[],
                industry_news=[],
                analyst_sentiment={},
                market_discourse={},
                strategic_shifts=[],
                variant_perceptions=[],
                suggested_threads=[],
                critical_external_context=["Failed to parse external discovery response"],
                searches_performed=[],
                evidence_ids=list(base_evidence_ids),
            )

        return ExternalDiscoveryOutput(
            competitor_developments=data.get("competitor_developments", []),
            industry_news=data.get("industry_news", []),
            analyst_sentiment=data.get("analyst_sentiment", {}),
            market_discourse=data.get("market_discourse", {}),
            strategic_shifts=data.get("strategic_shifts", []),
            variant_perceptions=data.get("variant_perceptions", []),
            suggested_threads=data.get("research_threads_suggested", []),
            critical_external_context=data.get("critical_external_context", []),
            searches_performed=data.get("searches_performed", []),
            analysis_date=data.get("meta", {}).get("analysis_date", ""),
            evidence_ids=list(base_evidence_ids),
        )

    def to_discovered_threads(self, output: ExternalDiscoveryOutput) -> list[DiscoveredThread]:
        """Convert suggested threads to DiscoveredThread objects.

        This allows External Discovery output to be merged with Internal Discovery.
        """
        threads = []

        # Convert variant perceptions to research threads
        for i, vp in enumerate(output.variant_perceptions):
            thread = DiscoveredThread.create(
                name=f"Variant Perception: {vp.get('topic', 'Unknown')}",
                description=f"Consensus: {vp.get('consensus_view', '')}. Variant: {vp.get('variant_view', '')}",
                thread_type=ThreadType.CROSS_CUTTING,
                priority=2,  # High priority for variant perceptions
                discovery_lens="variant_perception",
                is_official_segment=False,
                value_driver_hypothesis=vp.get("variant_view", ""),
                research_questions=[
                    f"Is the consensus view ({vp.get('consensus_view', '')}) correct?",
                    f"What evidence supports the variant view: {vp.get('variant_view', '')}?",
                    f"What would trigger a re-rating: {vp.get('trigger_event', '')}?",
                ],
                evidence_ids=output.evidence_ids,
            )
            threads.append(thread)

        # Convert suggested threads
        for st in output.suggested_threads:
            thread = DiscoveredThread.create(
                name=st.get("name", "Unknown"),
                description=st.get("why_it_matters", ""),
                thread_type=ThreadType.CROSS_CUTTING,
                priority=st.get("priority", 3),
                discovery_lens=st.get("source_lens", "external"),
                is_official_segment=False,
                value_driver_hypothesis=st.get("why_it_matters", ""),
                research_questions=st.get("research_questions", []),
                evidence_ids=output.evidence_ids,
            )
            threads.append(thread)

        return threads

    def generate_thread_briefs(self, output: ExternalDiscoveryOutput) -> list[ThreadBrief]:
        """Generate ThreadBriefs from external discovery output.

        Creates briefs for:
        - Variant perceptions (highest value - where consensus may be wrong)
        - Strategic shifts (material business model changes)
        - Suggested research threads

        Args:
            output: ExternalDiscoveryOutput from run().

        Returns:
            List of ThreadBrief objects for downstream stages.
        """
        briefs = []

        # Generate briefs for variant perceptions (HIGHEST VALUE)
        for vp in output.variant_perceptions:
            topic = vp.get("topic", "Unknown")
            thread_id = generate_id("ext_vp")

            brief = ThreadBrief(
                thread_id=thread_id,
                rationale=f"Variant perception identified: consensus may be wrong on {topic}. "
                         f"Consensus: {vp.get('consensus_view', '')}. "
                         f"Variant: {vp.get('variant_view', '')}",
                hypotheses=[
                    f"If consensus is wrong: {vp.get('variant_view', '')}",
                    f"Trigger event: {vp.get('trigger_event', '')}",
                ],
                key_questions=[
                    f"Is consensus correct: {vp.get('consensus_view', '')}?",
                    f"What evidence supports: {vp.get('variant_view', '')}?",
                    f"When could re-rating occur: {vp.get('trigger_event', '')}?",
                ],
                required_evidence=[
                    "Cross-reference multiple external sources",
                    "Analyst reports with dissenting views",
                    vp.get("evidence", ""),
                ],
                key_evidence_ids=vp.get("evidence_ids", []) or list(output.evidence_ids[:5]),
                confidence=0.7 if vp.get("confidence") == "high" else 0.5,
            )
            briefs.append(brief)

        # Generate briefs for strategic shifts
        for shift in output.strategic_shifts:
            if shift.get("materiality") not in ["high", "medium"]:
                continue

            thread_id = generate_id("ext_shift")
            shift_type = shift.get("shift_type", "unknown")
            description = shift.get("description", "Strategic shift")

            brief = ThreadBrief(
                thread_id=thread_id,
                rationale=f"Strategic shift ({shift_type}): {description}. "
                         f"Competitive implication: {shift.get('competitive_implication', '')}",
                hypotheses=[
                    f"If shift succeeds: new competitive advantage in {shift_type}",
                    f"If shift fails: resource misallocation risk",
                    f"Priced in: {shift.get('is_priced_in', 'unknown')}",
                ],
                key_questions=[
                    f"What is the revenue/margin impact of: {description}?",
                    f"Is this priced in? Current assessment: {shift.get('is_priced_in', 'unknown')}",
                    "How does this change competitive position?",
                ],
                required_evidence=[
                    "Company announcements and press releases",
                    "Competitor response analysis",
                    "Market sizing for new opportunity",
                ],
                key_evidence_ids=[shift.get("evidence_id")] if shift.get("evidence_id") else list(output.evidence_ids[:3]),
                confidence=0.8 if shift.get("materiality") == "high" else 0.6,
            )
            briefs.append(brief)

        # Generate briefs for suggested threads
        for st in output.suggested_threads:
            thread_id = generate_id("ext_thread")
            name = st.get("name", "Unknown")

            brief = ThreadBrief(
                thread_id=thread_id,
                rationale=f"External research suggests: {name}. {st.get('why_it_matters', '')}",
                hypotheses=[
                    f"This vertical may be undervalued: {st.get('why_it_matters', '')}",
                ],
                key_questions=st.get("research_questions", ["What is the value driver here?"]),
                required_evidence=[
                    f"Source lens: {st.get('source_lens', 'external')}",
                    "Competitor comparisons",
                    "Market data",
                ],
                key_evidence_ids=st.get("evidence_ids", []) or list(output.evidence_ids[:3]),
                confidence=max(0.3, 1.0 - (st.get("priority", 3) - 1) * 0.15),
            )
            briefs.append(brief)

        return briefs

    async def close(self) -> None:
        """Close any open clients."""
        if self._web_research_service:
            await self._web_research_service.close()
            self._web_research_service = None
