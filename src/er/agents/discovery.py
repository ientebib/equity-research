"""
Discovery Agent (Stage 2).

Finds ALL potential value drivers using 7 lenses, not just official segments.
Uses GPT-5.2 with web search for current information.

Model: GPT-5.2 (with reasoning_effort: high + web_search_preview tool)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.base import LLMRequest
from er.llm.openai_client import OpenAIClient
from er.types import (
    CompanyContext,
    DiscoveredThread,
    DiscoveryOutput,
    Phase,
    ResearchGroup,
    RunState,
    ThreadType,
    generate_id,
)


# Discovery prompt template - 7 Mandatory Lenses
DISCOVERY_PROMPT = """You are the Discovery Agent for an institutional equity research system.

## CRITICAL CONTEXT

TODAY: {date}
TICKER: {ticker}
COMPANY: {company_name}

Your job is to find ALL value drivers - especially ones NOT in official segment reporting. The official 10-K segments are your STARTING POINT, not your answer.

## GROUND TRUTH DATA

{company_context}

## QUANT METRICS (Pre-Computed)

The JSON includes `quant_metrics` with pre-computed ratios and red flags. USE THESE:

### What's Priced In (expectations)
- `pe_ratio`, `peg_ratio`, `ev_to_ebitda`, `fcf_yield`
- `implied_growth_narrative` — interpret what growth the market expects

### Earnings Quality Red Flags (earnings_quality)
- `income_quality` — OCF/Net Income. Below 0.9 = investigate, below 0.8 = CRITICAL
- `dso` — Days Sales Outstanding. Rising DSO = revenue recognition issues
- `dio` — Days Inventory Outstanding. Rising = obsolescence risk
- `sbc_to_revenue` — Stock-based comp. Above 15% = significant dilution

### Capital Allocation (capital_allocation)
- `roic` — Return on Invested Capital. THE compounding metric
- `roic_assessment` — Pre-computed interpretation
- `capex_to_revenue`, `rd_to_revenue` — Investment intensity

### Financial Health (financial_health)
- `debt_to_equity`, `interest_coverage`, `net_debt_to_ebitda`, `current_ratio`

### Pre-Computed Scores (scores)
- `altman_z` — Bankruptcy risk. <1.8 = danger, <2.99 = grey zone
- `piotroski` — Financial strength (0-9). <3 = weak

### Red Flags (red_flags)
**ALWAYS CHECK THIS ARRAY FIRST.** Pre-computed warnings like:
- "CRITICAL: Income quality below 0.8"
- "WARNING: ROIC below 8%"
- "WARNING: ~47% of EPS growth is buyback-driven, not operational"

If red_flags is non-empty, these MUST inform your analysis.

### Buyback Distortion Check (buyback_check)
EPS-based metrics (PE, PEG) can be artificially inflated by buybacks.
- `share_count_change_yoy` — Negative = shares shrinking (buybacks active)
- `eps_growth_decomposition` — Shows how much EPS growth came from operations vs. buybacks
- `flag` — Warning if buybacks drive >30% of EPS growth

**If share count is shrinking AND EPS growth looks strong:**
1. PE/PEG may look better than operational reality
2. Check if "growth" is real or financial engineering
3. A company with flat revenue, flat margins, but 10% EPS growth via 10% buybacks has ZERO operational improvement

---

## RATIO INTERPRETATION BY BUSINESS TYPE

The same ratios mean different things for different businesses:

**Software/SaaS:**
- DIO: IGNORE (no inventory)
- DSO: CRITICAL (subscription collection health)
- SBC to revenue: CRITICAL (often 15-25%, affects real earnings)
- Gross margin: Should be 70%+ for good SaaS
- ROIC: May be low/negative if growth mode — check trajectory

**Retail/Consumer Goods:**
- DIO: CRITICAL (inventory obsolescence risk)
- Cash conversion cycle: CRITICAL (working capital efficiency)
- Gross margin: 30-50% is normal
- Capex to depreciation: Watch for underinvestment in stores

**Financials:**
- Most ratios don't apply — FLAG: "Financial sector — standard ratios not applicable"

**Capital-Intensive (Manufacturing, Utilities):**
- Capex to revenue: CRITICAL (ongoing investment required)
- Debt levels: Higher leverage is normal
- ROIC: Lower acceptable (~8-12% is fine)

**Your job:** Note which ratios are most relevant for THIS company's business model.

---

## MANDATORY DISCOVERY PROCESS

You MUST complete ALL 7 lenses below. Each lens has REQUIRED SEARCHES and REQUIRED OUTPUTS.

If you skip a lens or give vague output, you have failed.

If a lens produces nothing meaningful, explicitly state "No findings" with reasoning.

---

## LENS 1: Official Structure

**Source:** JSON provided (no web search)

**Task:** Extract from revenue_by_product in JSON:
- Each segment name
- Q3 2025 revenue
- Q1→Q2→Q3 2025 growth trajectory
- Percent of total revenue

**Required Output Fields:**
- segment_name
- q3_2025_revenue
- quarterly_trend (accelerating/stable/decelerating)
- percent_of_total

This is your BASELINE. Not your final answer.

---

## LENS 2: Competitive Cross-Reference

**Purpose:** Find value drivers by examining what competitors are valued for.

**SUGGESTED SEARCHES (start with these, add more as needed):**
- "{ticker} main competitors 2025"
- "[largest competitor] valuation thesis 2025"
- "[largest competitor] vs {ticker} market cap comparison"
- Additional searches as needed to understand competitive landscape

**Task:**
- Identify what competitors are valued for
- Ask: Does {ticker} have similar capabilities?
- If yes, this is a potential value driver

**Example Logic:**
- Search finds: "NVIDIA valued at $3T for AI accelerator chips"
- Ask: "Does {ticker} make AI chips?"
- If Google: "Yes - TPUs" → NEW RESEARCH VERTICAL

**Required Output Fields:**
- competitor_name
- competitor_valuation_driver (what they're valued for)
- does_ticker_have_this (yes/no/partially)
- potential_vertical (if yes, name the value driver)

---

## LENS 3: Analyst Attention

**Purpose:** Find what the market is debating right now.

**SUGGESTED SEARCHES (start with these, add more as needed):**
- "{ticker} analyst rating upgrade downgrade {current_month} {current_year}"
- "{ticker} bull vs bear case 2025"
- "{ticker} earnings call analyst questions Q3 2025"
- Additional searches to understand analyst debates

**Task:**
- What's the current analyst consensus?
- What's the bull thesis?
- What's the bear thesis?
- What question do analysts keep asking that management avoids?

**Required Output Fields:**
- consensus_rating
- bull_thesis (specific, not vague)
- bear_thesis (specific, not vague)
- key_debate_topic
- unanswered_question

---

## LENS 4: Recent Deals & Developments

**Purpose:** Find value-creating events from last 90 days.

**SUGGESTED SEARCHES (start with these, add more as needed):**
- "{ticker} partnership deal {current_month} {current_year}"
- "{ticker} acquisition announcement 2025"
- "{ticker} product launch {current_year}"
- Additional searches for recent developments

**Task:**
- Any M&A in last 90 days?
- Any major partnerships?
- Any product launches that create new revenue streams?

**Required Output Fields:**
- event_date
- event_type (deal/acquisition/launch)
- description
- value_driver_implication (does this create a new vertical?)

If nothing found, output: "No major developments in last 90 days"

---

## LENS 5: Asset Inventory

**Purpose:** Find valuable assets that aren't yet monetized as segments.

**SUGGESTED SEARCHES (start with these, add more as needed):**
- "{ticker} technology infrastructure assets"
- "{ticker} internal technology external sales monetization"
- Additional searches for hidden assets and R&D

**Task:**
- What technologies does this company own?
- What's used internally that could be sold externally?
- What R&D investments could become products?

**Example:** Google's TPUs were internal infrastructure for years before external sales began.

**Required Output Fields:**
- asset_name
- current_use (internal/external/both)
- monetization_status (not monetized/early/scaling/mature)
- potential_value_driver (yes/no)

---

## LENS 6: Management Emphasis

**Source:** earnings_transcripts in JSON (no web search needed)

**Task:** Read the transcripts and extract:
- What did CEO spend the most time on?
- What's the stated strategic priority?
- Any initiatives mentioned that aren't in segment data?
- Copy EXACT QUOTES for important statements

**Required Output Fields:**
- top_priority (exact quote from transcript)
- time_emphasis (what topic got unusual airtime)
- new_initiatives (not yet in segment data)
- deflected_topics (what management avoided answering)

---

## LENS 7: Blind Spots Synthesis

**Source:** Your analysis of lenses 1-6

**Task:**
- What value driver exists that the market might be missing?
- What showed up in multiple lenses?
- What surprised you?

**Required Output Fields:**
- potential_blind_spot
- supporting_evidence (which lenses)
- why_market_missing_it

---

## RESEARCH GROUP ASSIGNMENT

You must assign verticals to exactly 2 research groups. The grouping matters because:
1. Each group runs as ONE deep research call
2. The researcher needs coherent context across verticals
3. Related verticals benefit from cross-analysis

### Grouping Criteria (in priority order):

**1. Business Model Similarity**
Group verticals with similar business models together:
- Ad-driven revenue → together (Search, YouTube, Network)
- Subscription/consumption → together (Cloud, Workspace, API)
- Hardware/licensing → together (Devices, Licensing)
- Pre-revenue/bets → together (Waymo, Verily, Other Bets)

**2. Valuation Method Alignment**
Group verticals that use similar valuation approaches:
- DCF-able (stable cash flows) → Group 1
- Multiple-based (comparable peers exist) → Group 1
- Option value (binary outcomes) → Group 2
- Probability-weighted (high uncertainty) → Group 2

**3. Research Synergies**
Group verticals where understanding one helps understand another:
- AI infrastructure + AI applications → together (TPUs + Gemini API)
- Platform + monetization → together (Android + Play Store)
- Core + extension → together (Search + Search AI features)

**4. Data Source Overlap**
Group verticals that draw from similar sources:
- Same competitors to research → together
- Same earnings call sections → together
- Same analyst coverage → together

### Balance Consideration

Try to balance the groups somewhat:
- If one group has 5 verticals and another has 1, reconsider
- Ideal: 2-4 verticals per group
- Acceptable: 1-5 verticals per group
- Avoid: 6+ in one group (too much for one research call)

---

## FINAL OUTPUT FORMAT

After completing ALL 7 lenses, output this JSON:

```json
{{
  "meta": {{
    "analysis_date": "{date}",
    "ticker": "{ticker}",
    "company_name": "{company_name}",
    "model": "gpt-5.2",
    "lenses_completed": 7
  }},

  "searches_performed": [
    {{
      "lens": "competitive_cross_reference",
      "query": "actual search query",
      "key_finding": "what you found"
    }}
  ],

  "lens_outputs": {{
    "official_structure": {{
      "segments": [
        {{
          "name": "...",
          "q3_2025_revenue_usd": 0,
          "quarterly_trend": "accelerating|stable|decelerating",
          "percent_of_total": 0.0
        }}
      ]
    }},

    "competitive_cross_reference": {{
      "competitors_analyzed": [
        {{
          "name": "...",
          "valuation_driver": "what they're valued for",
          "ticker_has_similar": true,
          "potential_vertical": "name if applicable"
        }}
      ]
    }},

    "analyst_attention": {{
      "consensus": "bullish|neutral|bearish",
      "bull_thesis": "...",
      "bear_thesis": "...",
      "key_debate": "...",
      "unanswered_question": "..."
    }},

    "recent_developments": {{
      "events": [
        {{
          "date": "YYYY-MM-DD",
          "type": "deal|acquisition|launch",
          "description": "...",
          "creates_new_vertical": true
        }}
      ]
    }},

    "asset_inventory": {{
      "assets": [
        {{
          "name": "...",
          "current_use": "internal|external|both",
          "monetization_status": "not_monetized|early|scaling|mature",
          "is_potential_vertical": true
        }}
      ]
    }},

    "management_emphasis": {{
      "top_priority_quote": "exact quote",
      "unusual_emphasis": "topic",
      "new_initiatives": ["..."],
      "deflected_topics": ["..."]
    }},

    "blind_spots": {{
      "potential_missed_driver": "...",
      "supporting_lenses": ["lens2", "lens5"],
      "hypothesis": "why market is missing this"
    }}
  }},

  "research_verticals": [
    {{
      "id": "v1",
      "name": "Vertical Name",
      "source_lens": "which lens discovered this",
      "is_official_segment": false,
      "why_it_matters": "1-2 sentences on valuation impact",
      "current_state": {{
        "revenue_usd": 0,
        "growth_rate": 0.0,
        "data_source": "json|web_search|transcript"
      }},
      "market_debate": {{
        "bull_view": "...",
        "bear_view": "...",
        "key_question": "..."
      }},
      "research_questions": [
        "Specific question 1",
        "Specific question 2",
        "Specific question 3"
      ],
      "priority": 1
    }}
  ],

  "research_groups": {{
    "group_1": {{
      "name": "Descriptive name based on theme",
      "verticals": ["v1", "v2", "v3"],
      "theme": "What unifies these verticals",
      "grouping_rationale": "Why these belong together (cite criteria above)",
      "shared_context": "What the researcher should know applies to all",
      "key_questions": ["Cross-vertical question 1", "Cross-vertical question 2"],
      "valuation_approach": "Likely DCF for all / Mixed / Primarily option value"
    }},
    "group_2": {{
      "name": "Descriptive name based on theme",
      "verticals": ["v4", "v5"],
      "theme": "What unifies these verticals",
      "grouping_rationale": "Why these belong together",
      "shared_context": "What the researcher should know applies to all",
      "key_questions": ["Cross-vertical question 1", "Cross-vertical question 2"],
      "valuation_approach": "Likely DCF for all / Mixed / Primarily option value"
    }}
  }},

  "grouping_validation": {{
    "balance_check": "Group 1 has X verticals, Group 2 has Y verticals",
    "no_orphans": true,
    "thematic_coherence": "Confirm groups make sense"
  }},

  "critical_information_gaps": [
    "What we couldn't find that deep research must answer"
  ]
}}
```

## HARD RULES

1. **COMPLETE ALL 7 LENSES** - No skipping. Output "No findings" if empty.

2. **SEARCH AS MUCH AS NEEDED** - Use as many web searches as necessary. There is NO LIMIT. List all searches in searches_performed.

3. **AT LEAST ONE NON-OFFICIAL VERTICAL** - If all your verticals are official segments, you failed Lens 2, 4, 5, or 7.

4. **SPECIFIC RESEARCH QUESTIONS** - Not "Is growth good?" but "What is Cloud revenue growth rate in Q3 2025 vs AWS?"

5. **CITE YOUR SOURCES** - Each finding must say where it came from (JSON, which search, which transcript).

6. **QUARTERLY DATA FIRST** - Q3 2025 is latest. FY2024 is old. Always cite quarters.

7. **5-8 VERTICALS MAX** - Prioritize by materiality. Not everything is worth researching.

8. **TWO RESEARCH GROUPS** - Split verticals into two groups for parallel deep research.

9. **COHERENT GROUPING** - Verticals in a group must share business model, valuation method, or research synergy. Random grouping is a failure. Ad-driven segments go together. Growth bets go together. Justify your grouping.

Output ONLY the JSON. No preamble, no explanation, no markdown formatting outside the JSON."""


class DiscoveryAgent(Agent):
    """Stage 2: Discovery + Enrichment.

    Responsible for:
    1. Analyzing CompanyContext with 7 lenses
    2. Finding ALL value drivers (official + hidden)
    3. Using web search for recent information
    4. Outputting 3-5 prioritized research threads

    Uses GPT-5.2 with web search for web-enhanced discovery.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Discovery Agent.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._openai_client: OpenAIClient | None = None

    @property
    def name(self) -> str:
        return "discovery"

    @property
    def role(self) -> str:
        return "Find all value drivers using 7 lenses with web search"

    async def _get_openai_client(self) -> OpenAIClient:
        """Get or create OpenAI client."""
        if self._openai_client is None:
            self._openai_client = OpenAIClient(
                api_key=self.settings.OPENAI_API_KEY,
            )
        return self._openai_client

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        use_web_search: bool = True,
        reasoning_effort: str = "medium",
        **kwargs: Any,
    ) -> DiscoveryOutput:
        """Execute Stage 2: Discovery with 7 lenses.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            use_web_search: Whether to use web search (recommended).

        Returns:
            DiscoveryOutput with all discovered research threads.
        """
        self.log_info(
            "Starting discovery",
            ticker=run_state.ticker,
            use_web_search=use_web_search,
        )

        run_state.phase = Phase.DISCOVERY

        # Build the prompt with company context
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B")  # e.g., "December"
        current_year = now.strftime("%Y")   # e.g., "2025"

        prompt = DISCOVERY_PROMPT.format(
            date=today,
            current_month=current_month,
            current_year=current_year,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            company_context=company_context.to_prompt_string(),
        )

        # Get OpenAI client
        openai = await self._get_openai_client()

        # Build request - high max_tokens for reasoning + web search + output
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-5.2",
            temperature=0.3,
            max_tokens=100000,
        )

        # Run discovery
        if use_web_search:
            # Use GPT-5.2 with web search enabled
            self.log_info("Using GPT-5.2 with web search", ticker=run_state.ticker)
            response = await openai.complete_with_web_search(
                request,
                reasoning_effort=reasoning_effort,
            )
        else:
            # Use regular GPT-5.2 with reasoning (no web search)
            self.log_info("Using GPT-5.2 with reasoning (no web search)", ticker=run_state.ticker)
            response = await openai.complete_with_reasoning(
                request,
                reasoning_effort="high",
            )

        # Record cost
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="openai",
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
            "research_groups": [
                {
                    "group_id": g.group_id,
                    "name": g.name,
                    "vertical_count": len(g.vertical_ids),
                }
                for g in discovery_output.research_groups
            ],
            "cross_cutting_themes": discovery_output.cross_cutting_themes,
            "optionality_candidates": discovery_output.optionality_candidates,
        }

        self.log_info(
            "Completed discovery",
            ticker=run_state.ticker,
            thread_count=len(discovery_output.research_threads),
            group_count=len(discovery_output.research_groups),
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

        Handles the new 7-lens format with lens_outputs, source_lens,
        grouping_rationale, shared_context, and valuation_approach.

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

        # Parse research verticals into threads
        # Build a map from vertical ID to thread for group resolution
        research_threads = []
        thread_id_map: dict[str, str] = {}  # Maps prompt ID (v1, v2) to actual thread_id

        for v in data.get("research_verticals", []):
            prompt_id = v.get("id", "")

            # Determine thread type based on is_official_segment and source_lens
            is_official = v.get("is_official_segment", False)
            source_lens = v.get("source_lens", "official_structure")

            if is_official or source_lens == "official_structure":
                thread_type = ThreadType.SEGMENT
            elif source_lens in ("asset_inventory", "blind_spots") or "optionality" in v.get("name", "").lower():
                thread_type = ThreadType.OPTIONALITY
            else:
                thread_type = ThreadType.CROSS_CUTTING

            # Extract market debate info
            market_debate = v.get("market_debate", {})
            key_question = market_debate.get("key_question", "")

            thread = DiscoveredThread.create(
                name=v.get("name", "Unknown"),
                description=v.get("why_it_matters", ""),
                thread_type=thread_type,
                priority=v.get("priority", 3),
                discovery_lens=source_lens,  # Now uses source_lens from output
                is_official_segment=is_official,
                official_segment_name=v.get("name") if is_official else None,
                value_driver_hypothesis=key_question,
                research_questions=v.get("research_questions", []),
                evidence_ids=list(base_evidence_ids),
            )
            research_threads.append(thread)
            thread_id_map[prompt_id] = thread.thread_id

        # Parse research groups with new fields
        research_groups = []
        groups_data = data.get("research_groups", {})

        for group_key, group_data in groups_data.items():
            # Convert vertical IDs (v1, v2, etc.) to actual thread_ids
            vertical_ids = []
            for vid in group_data.get("verticals", []):
                if vid in thread_id_map:
                    vertical_ids.append(thread_id_map[vid])

            group = ResearchGroup(
                group_id=generate_id("group"),
                name=group_data.get("name", group_key),
                theme=group_data.get("theme", ""),
                vertical_ids=vertical_ids,
                key_questions=group_data.get("key_questions", []),
                # New fields from fixed prompt
                grouping_rationale=group_data.get("grouping_rationale", ""),
                shared_context=group_data.get("shared_context", ""),
                valuation_approach=group_data.get("valuation_approach", ""),
                # Legacy field
                focus=group_data.get("shared_context", group_data.get("theme", "")),
            )
            research_groups.append(group)

        # Extract official segments from lens_outputs or official_segments array
        official_segments = []
        lens_outputs = data.get("lens_outputs", {})
        official_structure = lens_outputs.get("official_structure", {})

        # Try new format first (lens_outputs.official_structure.segments)
        for seg in official_structure.get("segments", []):
            if isinstance(seg, dict):
                official_segments.append(seg.get("name", ""))

        # Fall back to old format if empty
        if not official_segments:
            for seg in data.get("official_segments", []):
                if isinstance(seg, dict):
                    official_segments.append(seg.get("name", ""))
                else:
                    official_segments.append(str(seg))

        # Parse cross-cutting themes from lens_outputs.blind_spots or cross_cutting_themes
        cross_cutting = []
        blind_spots = lens_outputs.get("blind_spots", {})
        if blind_spots.get("potential_missed_driver"):
            cross_cutting.append(blind_spots["potential_missed_driver"])

        # Also check old format
        for theme in data.get("cross_cutting_themes", []):
            if isinstance(theme, dict):
                theme_name = theme.get("theme", "")
                if theme_name and theme_name not in cross_cutting:
                    cross_cutting.append(theme_name)
            elif theme and theme not in cross_cutting:
                cross_cutting.append(str(theme))

        # Extract optionality candidates from asset_inventory
        optionality_candidates = []
        asset_inventory = lens_outputs.get("asset_inventory", {})
        for asset in asset_inventory.get("assets", []):
            if asset.get("is_potential_vertical") and asset.get("monetization_status") != "mature":
                optionality_candidates.append(asset.get("name", ""))

        # Data gaps from critical_information_gaps or information_gaps
        data_gaps = data.get("critical_information_gaps", data.get("information_gaps", data.get("data_gaps", [])))

        return DiscoveryOutput(
            official_segments=official_segments,
            research_threads=research_threads,
            research_groups=research_groups,
            cross_cutting_themes=cross_cutting,
            optionality_candidates=optionality_candidates,
            data_gaps=data_gaps,
            conflicting_signals=data.get("conflicting_signals", []),
            evidence_ids=list(base_evidence_ids),
        )

    async def close(self) -> None:
        """Close any open clients."""
        if self._openai_client:
            await self._openai_client.close()
            self._openai_client = None
