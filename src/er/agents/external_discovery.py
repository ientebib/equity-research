"""
External Discovery Agent (Stage 2B).

Finds competitive intelligence, news, and market context using web search.
Focuses on Pillar 2: What's happening OUTSIDE the company.

Architecture: Evidence-First approach
1. Build hybrid query plan (market map + baseline + LLM-proposed extras)
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


# External Discovery prompts - now receives pre-fetched EvidenceCards
EXTERNAL_DISCOVERY_PROMPT_LIGHT = """You are the External Discovery Agent for an institutional equity research system.

## ⚠️ DATE AWARENESS ⚠️

**TODAY IS: {date}**
**CURRENT MONTH: {current_month} {current_year}**

---

SECTOR: {sector}
INDUSTRY: {industry}

---

## YOUR MISSION (CONTEXT-LIGHT MODE)

Analyze the pre-fetched web research below to find everything happening OUTSIDE a target company that affects its investment thesis:
- What competitors announced recently
- What the market discourse is about
- What analysts are debating
- What regulatory/industry changes matter
- What the "variant perception" opportunities are

Important:
- You are operating in CONTEXT-LIGHT mode.
- DO NOT rely on company-specific or internal information.
- Use the evidence cards only, and focus on industry/market/competitor developments.

## KNOWN INDUSTRY PLAYERS (for search context only)

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
    "focus": "external_context",
    "mode": "light"
  }},

  "competitor_developments": [
    {{
      "competitor": "Company Name",
      "announcement": "What they announced",
      "date": "YYYY-MM-DD",
      "source": "Bloomberg|Reuters|etc",
      "evidence_id": "ev_xxx",
      "implication_for_ticker": "How this affects the target company",
      "threat_level": "high|medium|low"
    }}
  ],

  "industry_news": [
    {{
      "headline": "...",
      "date": "YYYY-MM-DD",
      "source": "...",
      "evidence_id": "ev_xxx",
      "affected_companies": ["TargetCo", "CompetitorA"],
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


EXTERNAL_DISCOVERY_PROMPT_ANCHORED = """You are the External Discovery Agent for an institutional equity research system.

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
    "focus": "external_context",
    "mode": "anchored"
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
    mode: str = ""
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

    def __init__(
        self,
        context: AgentContext,
        mode: str = "anchored",
        extra_queries: int = 6,
        max_total_queries: int = 25,
    ) -> None:
        """Initialize the External Discovery Agent.

        Args:
            context: Agent context with shared resources.
            mode: "anchored" for company-specific context, "light" for context-light.
            extra_queries: LLM-proposed additional queries (beyond deterministic baseline).
            max_total_queries: Hard cap on total queries per run.
        """
        self._mode = mode
        self._extra_queries = max(0, extra_queries)
        self._max_total_queries = max(5, max_total_queries)
        super().__init__(context)
        self._web_research_service = None

    @property
    def name(self) -> str:
        mode = getattr(self, "_mode", "anchored")
        return f"external_discovery_{mode}"

    @property
    def role(self) -> str:
        mode = getattr(self, "_mode", "anchored")
        return f"Find competitive intelligence, news, and market context ({mode})"

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

    async def _extract_topic_tags(self, company_context: CompanyContext) -> list[str]:
        """Extract topic tags from company context for market scanning."""
        description = company_context.profile.get("description", "") or ""
        segments = [
            seg.get("segment") or seg.get("name") or seg.get("label")
            for seg in (company_context.revenue_product_segmentation or [])
        ]
        segments = [s for s in segments if isinstance(s, str) and s][:8]
        transcript_snippets = []
        for t in (company_context.transcripts or [])[:2]:
            snippet = t.get("full_text") or t.get("content") or ""
            if snippet:
                transcript_snippets.append(snippet[:400])

        context = {
            "company": company_context.company_name,
            "sector": company_context.profile.get("sector", ""),
            "industry": company_context.profile.get("industry", ""),
            "description": description[:1200],
            "segments": segments,
            "transcript_snippets": transcript_snippets,
        }

        prompt = f"""Extract 6-10 topic tags that represent product areas, technologies, or business themes.
Use ONLY terms present in the context (do not guess).
Keep tags short (2-4 words). No company names.

Context:
{json.dumps(context, indent=2)}

Return JSON:
{{"topic_tags": ["tag1", "tag2", ...]}}
"""
        try:
            response = await self.llm_router.call(
                role=AgentRole.WORKHORSE,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            content = response.get("content", "") or ""
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(content[start : end + 1])
                else:
                    data = {}
            tags = data.get("topic_tags", [])
        except Exception as e:
            self.log_warning("Failed to extract topic tags", error=str(e))
            return segments[:6]

        if not isinstance(tags, list):
            return segments[:6]
        cleaned = []
        seen = set()
        for tag in tags:
            if not isinstance(tag, str):
                continue
            t = tag.strip()
            if not t:
                continue
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(t)
        return cleaned[:10]

    def _build_market_map_queries(
        self,
        company_context: CompanyContext,
        topic_tags: list[str],
        max_queries: int,
    ) -> list[str]:
        """Build market map queries to discover emergent competitors and shifts."""
        industry = company_context.profile.get("industry", "Technology")
        sector = company_context.profile.get("sector", "Technology")
        now = datetime.now(timezone.utc)
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        queries: list[str] = []
        base_tags = [t for t in topic_tags if t]
        if not base_tags:
            base_tags = [industry, sector]

        for tag in base_tags[:4]:
            queries.append(f"{tag} competitive landscape {current_year}")
            queries.append(f"{tag} market share {current_year}")
            queries.append(f"{tag} emerging players {current_year}")
            queries.append(f"{tag} recent developments last 90 days")
            queries.append(f"{tag} product launches {current_month} {current_year}")
            if "ai" in tag.lower() or "model" in tag.lower() or "llm" in tag.lower():
                queries.append(f"{tag} model leaderboard {current_year}")
                queries.append(f"{tag} new model release last 60 days")

        queries.append(f"{industry} new entrants {current_year}")
        queries.append(f"{industry} major announcements {current_year}")
        queries.append(f"{industry} funding rounds last 90 days")
        return queries[:max_queries]

    async def _extract_market_entities(
        self,
        market_results: list[Any],
    ) -> tuple[list[str], list[str]]:
        """Extract competitor names and emergent topics from market scan results."""
        if not market_results:
            return [], []

        payload = []
        for result in market_results:
            payload.append({
                "query": result.query,
                "result_titles": [r.title for r in result.search_results][:5],
                "card_titles": [c.title for c in result.evidence_cards][:5],
                "card_summaries": [c.summary for c in result.evidence_cards][:5],
            })

        prompt = f"""Extract competitor/peer names and emergent topics based ONLY on the evidence below.
Only include names explicitly present in the titles/summaries.

Evidence:
{json.dumps(payload, indent=2)}

Return JSON:
{{
  "competitors": ["Name1", "Name2", ...],
  "topics": ["topic1", "topic2", ...]
}}
"""
        try:
            response = await self.llm_router.call(
                role=AgentRole.WORKHORSE,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            content = response.get("content", "") or ""
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(content[start : end + 1])
                else:
                    data = {}
        except Exception as e:
            self.log_warning("Failed to extract market entities", error=str(e))
            return [], []

        competitors = data.get("competitors", [])
        topics = data.get("topics", [])

        def clean_list(values: Any, limit: int) -> list[str]:
            if not isinstance(values, list):
                return []
            cleaned = []
            seen = set()
            for item in values:
                if not isinstance(item, str):
                    continue
                val = item.strip()
                if not val:
                    continue
                key = val.lower()
                if key in seen:
                    continue
                seen.add(key)
                cleaned.append(val)
            return cleaned[:limit]

        return clean_list(competitors, 12), clean_list(topics, 12)

    def _build_query_plan(
        self,
        company_context: CompanyContext,
        competitors: list[str],
        mode: str,
        max_queries: int,
        topic_tags: list[str] | None = None,
        emergent_topics: list[str] | None = None,
    ) -> list[str]:
        """Build deterministic search query plan.

        Returns a list of search queries covering all lenses:
        - Competitor developments
        - Industry news (last 90 days)
        - Analyst upgrades/downgrades
        - Product launches
        - Regulatory changes
        """
        industry = company_context.profile.get("industry", "Technology")
        sector = company_context.profile.get("sector", "Technology")
        ticker = company_context.symbol
        company_name = company_context.company_name

        now = datetime.now(timezone.utc)
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        queries: list[str] = []

        topic_pool: list[str] = []
        for topic in (emergent_topics or []) + (topic_tags or []):
            if not isinstance(topic, str):
                continue
            cleaned = topic.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in {t.lower() for t in topic_pool}:
                continue
            topic_pool.append(cleaned)
        if not topic_pool:
            topic_pool = [industry, sector]

        # Lens 1: Competitor developments (topic-aligned, recency-focused)
        for competitor in competitors[:4]:  # Top 4 competitors
            for topic in topic_pool[:2]:
                queries.append(f"{competitor} {topic} launch last 90 days")
                queries.append(f"{competitor} {topic} pricing change last 12 months")
                queries.append(f"{competitor} {topic} partnership {current_year}")
            queries.append(f"{competitor} strategic shift {current_year}")

        # Lens 2: Industry news (recency + structure)
        queries.append(f"{industry} regulatory changes last 12 months")
        queries.append(f"{industry} market share shift {current_year}")
        queries.append(f"{sector} investment trends {current_year}")

        # Lens 2.5: Topic-level competitive shifts
        for topic in (topic_tags or [])[:3]:
            queries.append(f"{topic} competitive landscape {current_year}")
            queries.append(f"{topic} new entrants last 12 months")
            queries.append(f"{topic} pricing changes last 12 months")

        for topic in (emergent_topics or [])[:3]:
            queries.append(f"{topic} announcement {current_month} {current_year}")
            queries.append(f"{topic} funding round {current_year}")

        if mode == "anchored":
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
        else:
            # Context-light variant: industry/sector-level focus, no ticker/company terms
            queries.append(f"{industry} analyst report {current_year}")
            queries.append(f"{industry} competitive landscape last 12 months")
            queries.append(f"{industry} regulatory risk {current_year}")
            queries.append(f"{industry} pricing pressure {current_year}")
            queries.append(f"{industry} capacity expansion {current_year}")
            queries.append(f"{industry} strategic pivots {current_year}")
            queries.append(f"{industry} new entrants last 12 months")
            queries.append(f"{sector} market discourse {current_month} {current_year}")
            queries.append(f"{industry} underappreciated hidden value")

        return queries[:max_queries]

    async def _generate_additional_queries(
        self,
        company_context: CompanyContext,
        competitors: list[str],
        existing_queries: list[str],
        max_queries: int,
    ) -> list[str]:
        """Ask the LLM to propose additional external discovery queries."""
        if max_queries <= 0:
            return []

        now = datetime.now(timezone.utc)
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        avoid_terms = "ticker/company name"
        mode_instructions = (
            "You are in CONTEXT-LIGHT mode. Avoid using ticker or company name in queries."
        )
        if self._mode == "anchored":
            avoid_terms = "financial statements"
            mode_instructions = (
                "You are in ANCHORED mode. Use the ticker/company name, but avoid financial statement queries."
            )

        prompt = f"""You propose additional web search queries for external discovery.

TODAY: {now.strftime("%Y-%m-%d")}
MONTH/YEAR: {current_month} {current_year}
TICKER: {company_context.symbol}
COMPANY: {company_context.company_name}
SECTOR: {company_context.profile.get("sector", "Technology")}
INDUSTRY: {company_context.profile.get("industry", "Technology")}
COMPETITORS: {", ".join(competitors)}

MODE RULES:
- {mode_instructions}
- Focus on external/market/competitor/regulatory developments
- Prioritize last 30/60/90 days
- Avoid queries about {avoid_terms}
- Avoid duplicates or near-duplicates of existing queries

EXISTING QUERIES:
{json.dumps(existing_queries, indent=2)}

Return JSON:
{{
  "additional_queries": ["query 1", "query 2", ...]
}}
Return ONLY JSON.
"""

        try:
            response = await self.llm_router.call(
                role=AgentRole.WORKHORSE,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            content = response.get("content", "") or ""
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(content[start : end + 1])
                else:
                    data = {}
            queries = data.get("additional_queries", [])
        except Exception as e:
            self.log_warning(
                "Failed to generate additional queries",
                mode=self._mode,
                error=str(e),
            )
            return []

        if not isinstance(queries, list):
            return []

        cleaned: list[str] = []
        existing_lower = {q.strip().lower() for q in existing_queries if q}
        for q in queries:
            if not isinstance(q, str):
                continue
            query = q.strip()
            if not query:
                continue
            if query.lower() in existing_lower:
                continue
            existing_lower.add(query.lower())
            cleaned.append(query)

        return cleaned[:max_queries]

    def _normalize_override_queries(self, override_queries: Any) -> list[str]:
        """Normalize override queries for this agent mode."""
        if not override_queries:
            return []

        mode_queries: list[str] = []
        if isinstance(override_queries, dict):
            mode_queries = (
                override_queries.get(self._mode)
                or override_queries.get("all")
                or []
            )
        elif isinstance(override_queries, list):
            mode_queries = override_queries
        elif isinstance(override_queries, str):
            mode_queries = [override_queries]

        cleaned: list[str] = []
        seen: set[str] = set()
        for q in mode_queries:
            if not isinstance(q, str):
                continue
            query = q.strip()
            if not query:
                continue
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(query)

        return cleaned

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        **kwargs: Any,
    ) -> ExternalDiscoveryOutput:
        """Execute External Discovery using Evidence-First approach.

        1. Build hybrid query plan (market map + baseline + LLM extras + overrides)
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

        # Build market map scan to discover emergent competitors/topics
        topic_tags = await self._extract_topic_tags(company_context)
        market_map_budget = min(6, max(3, self._max_total_queries // 4))
        market_map_queries = self._build_market_map_queries(
            company_context,
            topic_tags,
            market_map_budget,
        )

        web_service = await self._get_web_research_service()
        market_map_results = []
        market_competitors: list[str] = []
        emergent_topics: list[str] = []
        if market_map_queries:
            market_map_results = await web_service.research_batch(
                queries=market_map_queries,
                max_results_per_query=3,
                recency_days=365,
                max_total_queries=market_map_budget,
            )
            market_competitors, emergent_topics = await self._extract_market_entities(
                market_map_results,
            )

        # Merge competitors (market scan + static mapping)
        merged_competitors = []
        for name in (market_competitors + competitors):
            if not isinstance(name, str):
                continue
            key = name.strip()
            if not key:
                continue
            if key.lower() in {c.lower() for c in merged_competitors}:
                continue
            merged_competitors.append(key)
        if not merged_competitors:
            merged_competitors = competitors
        competitors_str = "\n".join(f"- {c}" for c in merged_competitors)

        # Build deterministic query plan
        max_extra = min(self._extra_queries, max(0, self._max_total_queries - 10))
        baseline_budget = max(10, self._max_total_queries - max_extra)
        baseline_queries = self._build_query_plan(
            company_context,
            merged_competitors,
            self._mode,
            baseline_budget,
            topic_tags=topic_tags,
            emergent_topics=emergent_topics,
        )

        # Add LLM-proposed extra queries (capped)
        extra_queries = await self._generate_additional_queries(
            company_context,
            merged_competitors,
            baseline_queries,
            max_extra,
        )

        override_mode = str(kwargs.get("override_mode") or "append").lower()
        override_queries = self._normalize_override_queries(
            kwargs.get("override_queries")
        )

        query_sources: dict[str, str] = {}
        queries: list[str] = []

        def add_queries(items: list[str], source: str) -> None:
            for q in items:
                key = q.strip().lower()
                if not key or key in query_sources:
                    continue
                query_sources[key] = source
                queries.append(q.strip())

        if override_mode == "replace" and override_queries:
            add_queries(override_queries, "override")
        else:
            add_queries(baseline_queries, "baseline")
            add_queries(override_queries, "override")
            add_queries(extra_queries, "llm_extra")

        # Final cap
        queries = queries[:self._max_total_queries]
        self.log_info(
            "Built query plan",
            ticker=run_state.ticker,
            query_count=len(queries),
            baseline_queries=len(baseline_queries),
            extra_queries=len(extra_queries),
            override_queries=len(override_queries),
            override_mode=override_mode,
        )

        # Execute searches via WebResearchService
        research_results = await web_service.research_batch(
            queries=queries,
            max_results_per_query=3,
            recency_days=90,
            max_total_queries=self._max_total_queries,
        )

        provider_label = "openai_web_search"
        try:
            from er.retrieval.search_provider import GeminiWebSearchProvider
            if isinstance(web_service.search_provider, GeminiWebSearchProvider):
                provider_label = "google_search"
        except Exception:
            provider_label = "openai_web_search"

        # Collect all evidence cards
        all_cards = []
        all_evidence_ids = list(company_context.evidence_ids)
        searches_performed = []

        # Include market map results first
        for result in market_map_results:
            all_cards.extend(result.evidence_cards)
            all_evidence_ids.extend(result.evidence_ids)
            searches_performed.append({
                "source": "market_map",
                "mode": self._mode,
                "query": result.query,
                "urls_found": [r.url for r in result.search_results],
                "cards_generated": len(result.evidence_cards),
                "phase": "market_map",
                "provider": provider_label,
            })

        for result in research_results:
            all_cards.extend(result.evidence_cards)
            all_evidence_ids.extend(result.evidence_ids)
            searches_performed.append({
                "source": query_sources.get(result.query.strip().lower(), "unknown"),
                "mode": self._mode,
                "query": result.query,
                "urls_found": [r.url for r in result.search_results],
                "cards_generated": len(result.evidence_cards),
                "phase": "baseline",
                "provider": provider_label,
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

        prompt_template = EXTERNAL_DISCOVERY_PROMPT_ANCHORED
        if self._mode == "light":
            prompt_template = EXTERNAL_DISCOVERY_PROMPT_LIGHT

        prompt = prompt_template.format(
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
            self._mode,
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
        mode: str,
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
                mode=mode,
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
            mode=mode,
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
