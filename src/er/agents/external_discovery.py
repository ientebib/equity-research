"""
External Discovery Agent (Stage 2B).

Finds competitive intelligence, news, and market context using web search.
Focuses on Pillar 2: What's happening OUTSIDE the company.

Model: Claude 4.5 Sonnet (with web search via tool)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.anthropic_client import AnthropicClient
from er.llm.base import LLMRequest
from er.types import (
    CompanyContext,
    DiscoveredThread,
    Phase,
    RunState,
    ThreadType,
    generate_id,
)


# External Discovery prompt - focused on competitive/news/market context
EXTERNAL_DISCOVERY_PROMPT = """You are the External Discovery Agent for an institutional equity research system.

## ⚠️ CRITICAL: DATE AWARENESS ⚠️

**TODAY IS: {date}**
**CURRENT MONTH: {current_month} {current_year}**
**TODAY IS: {date}**

Your training data is STALE and OUTDATED. You are analyzing a company in REAL-TIME.

**DO NOT USE YOUR TRAINING DATA FOR FACTS.**
**EVERYTHING MUST COME FROM WEB SEARCHES.**

If you cannot find something via web search, say "Not found via search" - do NOT fill in from memory.

---

TICKER: {ticker}
COMPANY: {company_name}
SECTOR: {sector}
INDUSTRY: {industry}

---

## ⚠️ REPEAT: DATE GROUNDING ⚠️

Today is **{date}**. This is **{current_month} {current_year}**.

- "Recent" means the last 90 days (since {ninety_days_ago})
- News from 2024 is OLD (over a year ago)
- News from early 2025 is STALE (6+ months old)
- Only {current_month} {current_year} and {last_month} {current_year} are truly "recent"

When you search, include "{current_month} {current_year}" or "December 2025" in your queries.

---

## YOUR MISSION

Your job is to find everything happening OUTSIDE this company that affects its investment thesis:
- What competitors announced recently
- What the market discourse is about
- What analysts are debating
- What regulatory/industry changes matter
- What the "variant perception" opportunities are

You work alongside an Internal Discovery agent who analyzes company financials and management statements.
Your focus is EXTERNAL context only.

## KNOWN COMPETITORS

Based on the company profile, likely competitors include:
{competitors}

## MANDATORY DISCOVERY PROCESS

Complete ALL 5 lenses below. Each lens requires web searches.

---

## LENS 1: Competitor Developments (Last 90 Days)

**Purpose:** What have competitors done that affects {ticker}?

**REQUIRED SEARCHES (for each major competitor):**
- "[competitor] announcement {current_month} {current_year}"
- "[competitor] product launch 2025"
- "[competitor] earnings {current_year}"

**Task:**
- What did each major competitor announce?
- Any product launches that threaten {ticker}?
- Any strategic shifts?
- Market share changes?

**Required Output:**
For each competitor:
- competitor_name
- recent_announcement (specific, with date)
- implication_for_ticker (how does this affect {ticker}?)

---

## LENS 2: Industry News & Trends

**Purpose:** What's happening in the industry that affects all players?

**REQUIRED SEARCHES:**
- "{industry} market news {current_month} {current_year}"
- "{industry} regulation 2025"
- "{industry} market size growth 2025"
- "{sector} trends 2025"

**Task:**
- Regulatory changes affecting the industry
- Market growth/contraction signals
- Technology shifts
- M&A activity in the space

**Required Output:**
- headline
- date
- affected_companies
- implication (for {ticker} specifically)

---

## LENS 3: Analyst Sentiment & Debates

**Purpose:** What is Wall Street debating about this stock?

**REQUIRED SEARCHES:**
- "{ticker} analyst upgrade downgrade {current_month} {current_year}"
- "{ticker} price target 2025"
- "{ticker} bull case bear case"
- "{ticker} what is consensus missing"

**Task:**
- Current consensus view
- Recent rating changes
- Key debates between bulls and bears
- What questions keep coming up?

**Required Output:**
- consensus_view (bullish/neutral/bearish)
- recent_rating_changes (list with analyst, date, old→new)
- bull_thesis (specific, not vague)
- bear_thesis (specific, not vague)
- key_debate_topics

---

## LENS 4: Market Discourse & Sentiment

**Purpose:** What are people talking about regarding this company?

**REQUIRED SEARCHES:**
- "{ticker} news {current_month} {current_year}"
- "{company_name} controversy 2025"
- "{ticker} reddit sentiment"
- "{company_name} what people are saying"

**Task:**
- Major news stories in last 30 days
- Any controversies or PR issues?
- Retail investor sentiment
- Viral discussions or memes

**Required Output:**
- major_stories (with dates)
- controversies (if any)
- sentiment_indicators
- viral_topics

---

## LENS 5: Strategic Shifts & Business Model Changes (LAST 6-12 MONTHS)

**Purpose:** What STRATEGIC changes happened this year? (Not just "recent news" - strategic pivots)

**IMPORTANT:** Strategic shifts may be 2-6 months old but still material if not fully priced in.
A product launch from October 2025 is STILL relevant in December 2025 if it represents a business model change.

**REQUIRED SEARCHES:**
- "{company_name} new business model 2025"
- "{company_name} new revenue stream 2025"
- "{company_name} selling externally 2025" (internal assets now sold to third parties)
- "{company_name} strategic pivot 2025"
- "{ticker} entering new market 2025"
- "{company_name} competing with new competitors 2025"
- "{company_name} proprietary technology external customers 2025" (chips, infrastructure, APIs)
- "{company_name} research breakthrough 2025" (labs, new capabilities)
- "{company_name} infrastructure as a service 2025"

**Task:**
- What was INTERNAL-ONLY that is now sold EXTERNALLY? (proprietary tech, APIs, infrastructure, custom hardware)
- What NEW MARKETS did the company enter this year?
- What NEW PRODUCTS were launched that change the competitive landscape?
- What ACQUISITIONS changed the strategy?
- What R&D or RESEARCH breakthroughs were announced? (new capabilities, patents, benchmarks)
- Is the company now competing in ADJACENT markets by monetizing internal capabilities?

**These are often 2-6 months old but STILL MATERIAL if not priced in.**

---

## LENS 6: Variant Perception Opportunities

**Purpose:** Where might consensus be wrong?

**REQUIRED SEARCHES:**
- "{ticker} underappreciated"
- "{ticker} hidden value"
- "{ticker} what market is missing"
- "{ticker} undervalued segment"

**Task:**
- What capabilities does {ticker} have that competitors are valued for?
- What new business lines are emerging that aren't priced in?
- Where does your research suggest consensus is wrong?

For each potential variant perception:
- topic
- consensus_view (what most people think)
- variant_view (what might be different)
- evidence (what supports the variant view)
- trigger_event (what would prove the variant view right)

---

## OUTPUT FORMAT

Output this JSON structure:

```json
{{
  "meta": {{
    "analysis_date": "{date}",
    "ticker": "{ticker}",
    "company_name": "{company_name}",
    "model": "claude-sonnet",
    "focus": "external_context"
  }},

  "searches_performed": [
    {{
      "lens": "competitor_developments",
      "query": "actual search query used",
      "sources_found": ["Bloomberg", "Reuters"],
      "date_range_covered": "2025-10-01 to 2025-12-25",
      "key_findings": ["finding 1", "finding 2"]
    }}
  ],

  "competitor_developments": [
    {{
      "competitor": "Company Name",
      "announcement": "What they announced",
      "date": "YYYY-MM-DD",
      "source": "Bloomberg|Reuters|etc",
      "source_url": "https://...",
      "implication_for_ticker": "How this affects {ticker}",
      "threat_level": "high|medium|low"
    }}
  ],

  "industry_news": [
    {{
      "headline": "...",
      "date": "YYYY-MM-DD",
      "source": "...",
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
        "from_to": "Hold → Buy"
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
        "sentiment": "positive|negative|neutral"
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
      "source_url": "https://...",
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
      "priority": 1
    }}
  ],

  "critical_external_context": [
    "Key external fact 1 that internal discovery might miss",
    "Key external fact 2"
  ]
}}
```

## HARD RULES

1. **SEARCH EXTENSIVELY** - You must execute real web searches. List all searches in searches_performed.

2. **CITE SOURCES** - Every finding needs a source and date. No training data claims.

3. **FOCUS ON EXTERNAL** - You are NOT analyzing the company's financials. That's the Internal agent's job.

4. **BE SPECIFIC** - Not "competitors are doing well" but "Microsoft announced X on DATE"

5. **VARIANT PERCEPTION IS KEY** - The most valuable output is variant_perceptions. Where is consensus wrong?

6. **SUGGEST THREADS** - If you find something that deserves deep research, add it to research_threads_suggested.

7. **RECENT = VALUABLE** - Prioritize information from the last 90 days.

---

## ⚠️ SOURCE QUALITY REQUIREMENTS ⚠️

**ONLY USE REPUTABLE SOURCES.** Ignore SEO spam, content farms, and low-quality sites.

**TIER 1 - Highest Credibility (PREFER THESE):**
- **Financial News**: Bloomberg, Reuters, Financial Times, Wall Street Journal, CNBC, Yahoo Finance
- **Tech News**: The Verge, Ars Technica, TechCrunch, Wired, The Information
- **AI/ML News**: VentureBeat AI, MIT Technology Review
- **Company Sources**: Official press releases, investor relations pages, SEC filings
- **Analyst Reports**: Morgan Stanley, Goldman Sachs, JP Morgan, Bank of America (when publicly cited)

**TIER 2 - Acceptable:**
- **Business News**: Business Insider, Fortune, Forbes (news articles, not contributor posts)
- **Market Data**: Seeking Alpha (for news, not opinions), MarketWatch
- **Industry Publications**: Semiconductor Engineering, Cloud Computing News

**TIER 3 - Use With Caution (cite as "unverified"):**
- Reddit (for sentiment only, not facts)
- Twitter/X (for announcements from official company accounts only)
- YouTube (official company channels only)

**NEVER USE:**
- Random blogs, Medium posts from unknown authors
- SEO content farms, affiliate marketing sites
- Sites with excessive ads or clickbait headlines
- "Expert" roundups from unknown publications
- Press release aggregators without editorial review

**If you cannot find information from Tier 1-2 sources, state "Not found in reputable sources" rather than citing low-quality sources.**

---

## ⚠️ FINAL REMINDER: DATE AWARENESS ⚠️

Today is **{date}**. You are providing analysis as of **{current_month} {current_year}**.

**EVERY claim must have a source and date from your web searches.**
**If you cannot cite a web search result, do NOT include the claim.**
**Training data = STALE. Web search = FRESH.**

---

Output ONLY the JSON. No preamble, no explanation, no markdown formatting outside the JSON."""


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

    Uses Claude Sonnet with web search for external context gathering.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the External Discovery Agent.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._anthropic_client: AnthropicClient | None = None

    @property
    def name(self) -> str:
        return "external_discovery"

    @property
    def role(self) -> str:
        return "Find competitive intelligence, news, and market context"

    async def _get_anthropic_client(self) -> AnthropicClient:
        """Get or create Anthropic client."""
        if self._anthropic_client is None:
            self._anthropic_client = AnthropicClient(
                api_key=self.settings.ANTHROPIC_API_KEY,
            )
        return self._anthropic_client

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

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        **kwargs: Any,
    ) -> ExternalDiscoveryOutput:
        """Execute External Discovery.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.

        Returns:
            ExternalDiscoveryOutput with competitive intelligence and market context.
        """
        self.log_info(
            "Starting external discovery",
            ticker=run_state.ticker,
        )

        # Get competitors
        competitors = self._get_competitors(company_context)
        competitors_str = "\n".join(f"- {c}" for c in competitors)

        # Build prompt with extensive date grounding
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        # Calculate 90 days ago and last month
        from datetime import timedelta
        ninety_days_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")

        # Get last month name
        last_month_date = now.replace(day=1) - timedelta(days=1)
        last_month = last_month_date.strftime("%B")

        prompt = EXTERNAL_DISCOVERY_PROMPT.format(
            date=today,
            current_month=current_month,
            current_year=current_year,
            ninety_days_ago=ninety_days_ago,
            last_month=last_month,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            sector=company_context.profile.get("sector", "Technology"),
            industry=company_context.profile.get("industry", "Technology"),
            competitors=competitors_str,
        )

        # Get Anthropic client
        anthropic = await self._get_anthropic_client()

        # Build request
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="claude-sonnet-4-20250514",
            temperature=0.3,
            max_tokens=16000,
        )

        # Run with web search enabled
        self.log_info("Using Claude Sonnet with web search", ticker=run_state.ticker)
        response = await anthropic.complete_with_web_search(request)

        # Record cost
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="anthropic",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="external_discovery",
            )

        # Parse response
        output = self._parse_response(
            response.content,
            company_context.evidence_ids,
        )

        self.log_info(
            "Completed external discovery",
            ticker=run_state.ticker,
            competitor_developments=len(output.competitor_developments),
            variant_perceptions=len(output.variant_perceptions),
            suggested_threads=len(output.suggested_threads),
        )

        return output

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

    async def close(self) -> None:
        """Close any open clients."""
        if self._anthropic_client:
            await self._anthropic_client.close()
            self._anthropic_client = None
