"""
Discovery Agent using Claude Agent SDK (Stage 2).

Implements the 7-lens framework with:
- Main orchestrator that analyzes CompanyContext
- 3 Sonnet subagents for parallel web search:
  - analyst-sentiment (Lens 3 - Analyst Attention)
  - competitor-analysis (Lens 2 - Competitive Cross-Reference)
  - recent-developments (Lens 4 - Recent Deals & Developments)

Prompts are loaded from docs/prompts/ for easy editing.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

from er.evidence.store import EvidenceStore
from er.logging import get_logger
from er.types import (
    CompanyContext,
    DiscoveredThread,
    DiscoveryOutput,
    ResearchGroup,
    ThreadBrief,
    ThreadType,
    generate_id,
)
from er.utils.dates import (
    get_latest_quarter_from_data,
    format_quarter,
    format_quarters_for_prompt,
)

logger = get_logger(__name__)


# =============================================================================
# PROMPT LOADING - From docs/prompts/ for editability
# =============================================================================

def _get_prompts_dir() -> Path:
    """Get the prompts directory relative to this file."""
    # src/er/agents/discovery_anthropic.py -> docs/prompts/
    return Path(__file__).parent.parent.parent.parent / "docs" / "prompts"


def _load_prompt(filename: str) -> str:
    """Load a prompt from docs/prompts/, stripping markdown headers."""
    prompt_path = _get_prompts_dir() / filename
    if not prompt_path.exists():
        logger.warning(f"Prompt file not found: {prompt_path}, using fallback")
        return ""

    content = prompt_path.read_text()

    # Strip markdown frontmatter (everything before first ---)
    if content.startswith("#"):
        # Find the actual prompt content after the header section
        lines = content.split("\n")
        prompt_start = 0
        found_separator = False
        for i, line in enumerate(lines):
            if line.strip() == "---":
                if found_separator:
                    prompt_start = i + 1
                    break
                found_separator = True
        content = "\n".join(lines[prompt_start:]).strip()

    return content


# =============================================================================
# ORCHESTRATOR SYSTEM PROMPT - Detailed output schema
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the Lead Discovery Orchestrator for an institutional equity research system.

Your job is to find ALL value drivers - especially ones NOT in official segment reporting.
The official 10-K segments are your STARTING POINT, not your answer.

## YOUR ROLE

You analyze the CompanyContext data directly for:
- Lens 1: Official Structure (from 10-K segments, revenue_by_product)
- Lens 5: Asset Inventory (from balance sheet, capex, hidden assets)
- Lens 6: Management Emphasis (from transcripts - what CEO prioritizes)
- Lens 7: Blind Spots (synthesis - what market might be missing)

You delegate to specialized subagents for web search:
- analyst-sentiment: Lens 3 - Analyst ratings, bull/bear cases, price targets
- competitor-analysis: Lens 2 - Competitive dynamics, peer valuations
- recent-developments: Lens 4 - News, M&A, partnerships (last 90 days)
- threat-analysis: External threats - Competitive disruption, regulatory, technology shifts

## CRITICAL BEHAVIORS

1. **USE WEB SEARCH EFFICIENTLY** - Delegate to subagents for real-time information. TOTAL budget: ~20 searches across all subagents. Be strategic.
2. **LOOK BEYOND OFFICIAL SEGMENTS** - Find hidden value drivers:
   - Internal tech that could be sold externally (e.g., TPUs, internal tools)
   - Strategic bets not yet in financials (e.g., autonomous vehicles)
   - Cross-cutting themes (AI, automation across segments)
3. **PRIORITIZE RECENCY** - Assume training data is stale, search for recent news
4. **BE SPECIFIC** - Not "growth is good" but "Cloud revenue grew 28% QoQ in Q4 2025"
5. **PRESERVE SUBAGENT FINDINGS** - When subagents return results, you MUST include their findings in the `lens_outputs` section of your final JSON:
   - analyst-sentiment results → `lens_outputs.analyst_attention`
   - competitor-analysis results → `lens_outputs.competitive_cross_reference`
   - recent-developments results → `lens_outputs.recent_developments`
   - threat-analysis results → `external_threats` (separate section)

   **THIS IS CRITICAL**: Deep Research agents need the full subagent findings to avoid re-discovering the same information. Do NOT summarize or omit subagent data.

## OUTPUT FORMAT

Output valid JSON with this EXACT structure:
```json
{
  "meta": {
    "analysis_date": "YYYY-MM-DD",
    "ticker": "SYMBOL",
    "company_name": "Name",
    "lenses_completed": 7
  },
  "searches_performed": [
    {"lens": "lens_name", "query": "search query", "key_finding": "what you found"}
  ],
  "lens_outputs": {
    "official_structure": {
      "segments": [{"name": "...", "latest_quarter_revenue_usd": 0, "quarterly_trend": "accelerating|stable|decelerating", "percent_of_total": 0.0}]
    },
    "competitive_cross_reference": {
      "competitors_analyzed": [{"name": "...", "valuation_driver": "...", "ticker_has_similar": true, "potential_vertical": "..."}]
    },
    "analyst_attention": {
      "consensus": "bullish|neutral|bearish",
      "bull_thesis": "...",
      "bear_thesis": "...",
      "key_debate": "...",
      "unanswered_question": "..."
    },
    "recent_developments": {
      "events": [{"date": "YYYY-MM-DD", "type": "deal|acquisition|launch", "description": "...", "creates_new_vertical": true}]
    },
    "asset_inventory": {
      "assets": [{"name": "...", "current_use": "internal|external|both", "monetization_status": "not_monetized|early|scaling|mature", "is_potential_vertical": true}]
    },
    "management_emphasis": {
      "top_priority_quote": "...",
      "unusual_emphasis": "...",
      "new_initiatives": ["..."],
      "deflected_topics": ["..."]
    },
    "blind_spots": {
      "potential_missed_driver": "...",
      "supporting_lenses": ["lens2", "lens5"],
      "hypothesis": "..."
    }
  },
  "external_threats": [
    {
      "threat_name": "Specific name of threat",
      "threat_type": "market_share|disruption|consumer_behavior|technology|regulatory|macro",
      "threat_source": "legacy_incumbent|startup|open_source|adjacent_entrant|government|economic",
      "specific_actor": "Name of company/entity (e.g., 'OpenAI', 'TikTok', 'EU DMA')",
      "affected_verticals": ["v1", "v2"],
      "current_impact": "none|emerging|material|severe",
      "trajectory": "accelerating|growing|stable|declining",
      "time_horizon": "near_term_0_12mo|medium_term_1_3yr|long_term_3yr_plus",
      "revenue_at_risk_pct": "Estimate: X-Y% of segment revenue",
      "description": "2-3 sentences on the threat with specific data points",
      "company_response": "How is the company responding?",
      "monitoring_signals": ["Specific metrics to watch"]
    }
  ],
  "threat_summary": {
    "most_urgent_threat": "Name of threat requiring immediate attention",
    "largest_magnitude_threat": "Name of threat with biggest revenue impact",
    "fastest_growing_threat": "Name of threat accelerating most quickly"
  },
  "research_verticals": [
    {
      "id": "v1",
      "name": "Vertical Name",
      "source_lens": "which lens discovered this",
      "is_official_segment": false,
      "why_it_matters": "1-2 sentences on valuation impact",
      "current_state": {"revenue_usd": 0, "growth_rate": 0.0, "data_source": "json|web_search|transcript"},
      "market_debate": {"bull_view": "...", "bear_view": "...", "key_question": "..."},
      "research_questions": ["Specific question 1", "Specific question 2", "Specific question 3"],
      "priority": 1
    }
  ],
  "research_groups": {
    "group_1": {
      "name": "Core Business",
      "verticals": ["v1", "v2"],
      "theme": "What unifies these",
      "grouping_rationale": "Why together",
      "shared_context": "Context for all",
      "key_questions": ["Cross-vertical Q1"],
      "valuation_approach": "DCF|Mixed|Option value"
    }
  },
  "critical_information_gaps": ["What deep research must answer"]
}
```

Output ONLY the JSON. No preamble, no explanation, no markdown formatting outside the JSON."""


# =============================================================================
# SUBAGENT PROMPTS - For parallel web search
# =============================================================================

ANALYST_SENTIMENT_PROMPT = """You are the Analyst Attention researcher for equity research (Lens 3).

Your task: Search for current analyst debates, ratings, bull/bear cases for {ticker}.

SUGGESTED SEARCHES:
- "{ticker} analyst rating upgrade downgrade {current_month} {current_year}"
- "{ticker} bull vs bear case {current_year}"
- "{ticker} price target changes"

Search for:
1. Recent analyst upgrades/downgrades (last 30 days)
2. Bull thesis - why analysts are bullish
3. Bear thesis - key concerns
4. Price target changes and consensus
5. Key debates - what analysts disagree about
6. Unanswered questions analysts want answered

IMPORTANT: You have a HARD LIMIT of {max_searches} web searches. Do NOT exceed this. Prioritize the most impactful searches.

Return JSON:
```json
{{
  "consensus": "bullish|neutral|bearish",
  "bull_thesis": "Main bullish argument with specific data",
  "bear_thesis": "Main bearish argument with specific concerns",
  "key_debate": "What analysts disagree about",
  "unanswered_question": "What analysts want to know",
  "recent_changes": [
    {{"analyst": "Firm Name", "action": "upgrade/downgrade", "target": "$X", "date": "YYYY-MM-DD", "rationale": "why"}}
  ],
  "searches": [
    {{"query": "what you searched", "finding": "what you found", "source": "source name"}}
  ]
}}
```"""


COMPETITOR_ANALYSIS_PROMPT = """You are the Competitive Cross-Reference researcher for equity research (Lens 2).

Your task: Search for main competitors and what they're valued for. Does {ticker} have similar capabilities?

SUGGESTED SEARCHES:
- "{ticker} main competitors {current_year}"
- "[largest competitor] valuation thesis"
- "{ticker} market share vs competitors"
- "[competitor] segment that {ticker} might have"

Search for:
1. Main competitors and their market positioning
2. How competitors value similar business segments
3. What competitors emphasize that {ticker} might have but doesn't highlight
4. Market share trends and competitive dynamics
5. Hidden assets competitors monetize that {ticker} might also have

IMPORTANT: You have a HARD LIMIT of {max_searches} web searches. Do NOT exceed this. Prioritize the most impactful searches.

Return JSON:
```json
{{
  "main_competitors": ["Competitor 1", "Competitor 2"],
  "competitive_dynamics": "Summary of competitive landscape",
  "competitors_analyzed": [
    {{"name": "Competitor", "valuation_driver": "What they're valued for", "ticker_has_similar": true, "potential_vertical": "What {ticker} could highlight"}}
  ],
  "ticker_advantages": ["Advantage 1 with specifics"],
  "ticker_disadvantages": ["Disadvantage 1 with specifics"],
  "hidden_assets_competitors_monetize": "What competitors have that {ticker} might also have but doesn't highlight",
  "searches": [
    {{"query": "what you searched", "finding": "what you found", "source": "source name"}}
  ]
}}
```"""


RECENT_DEVELOPMENTS_PROMPT = """You are the Recent Deals & Developments researcher for equity research (Lens 4).

Your task: Search for M&A, partnerships, product launches for {ticker} in the LAST 90 DAYS.

SUGGESTED SEARCHES:
- "{ticker} partnership deal {current_month} {current_year}"
- "{ticker} acquisition announcement {current_year}"
- "{ticker} new product launch {current_year}"
- "{ticker} regulatory news {current_year}"

Search for:
1. M&A activity (acquisitions, divestitures)
2. Strategic partnerships and deals
3. New product launches
4. Management changes
5. Regulatory developments
6. Any surprising news that might create new value drivers

IMPORTANT: You have a HARD LIMIT of {max_searches} web searches. Do NOT exceed this. Focus on the most impactful recent news.

Return JSON:
```json
{{
  "events": [
    {{
      "date": "YYYY-MM-DD",
      "type": "deal|acquisition|launch|partnership|regulatory|management",
      "description": "What happened with specifics",
      "potential_impact": "Why it matters for valuation",
      "creates_new_vertical": true,
      "source": "source name"
    }}
  ],
  "searches": [
    {{"query": "what you searched", "finding": "what you found", "source": "source name"}}
  ]
}}
```"""


THREAT_ANALYSIS_PROMPT = """You are the External Threat Analyst for equity research.

Your task: Identify and assess external threats to {ticker}'s business model, competitive position, and valuation.

SUGGESTED SEARCHES:
- "{ticker} competitive threat {current_year}"
- "{ticker} disruption risk AI ChatGPT {current_year}"
- "{ticker} antitrust regulatory risk {current_year}"
- "{ticker} market share loss {current_year}"
- "startups disrupting {ticker} {current_year}"
- "{ticker} consumer behavior shift {current_year}"

## THREAT SOURCES TO INVESTIGATE

### BY COMPETITOR TYPE:
1. **LEGACY INCUMBENTS**: Established players gaining share or expanding into {ticker}'s territory
2. **WELL-FUNDED STARTUPS**: VC-backed disruptors with new business models
3. **OPEN-SOURCE/COMMUNITY**: Open-source alternatives commoditizing proprietary technology
4. **ADJACENT MARKET ENTRANTS**: Companies from adjacent industries expanding into {ticker}'s space
5. **ECOSYSTEM PARTNERS TURNED COMPETITORS**: Companies that are customers/partners but also compete in certain segments

### IMPORTANT: ANALYZE COMPETITIVE RELATIONSHIPS AT MULTIPLE LAYERS

Many competitors have COMPLEX relationships with {ticker}. Analyze threats at each layer:

**LAYER 1 - APPLICATION/PRODUCT**: Who competes for end users?
- Consumer products (search, chat, video)
- Enterprise applications (productivity, CRM, analytics)

**LAYER 2 - MODEL/AI**: Who competes on AI model quality?
- Foundation models (GPT vs Gemini vs Claude)
- Specialized models (code, image, video)

**LAYER 3 - INFRASTRUCTURE**: Who competes on compute/cloud?
- Cloud platforms (AWS vs GCP vs Azure)
- AI chips (Nvidia vs TPU vs custom silicon)

**LAYER 4 - DISTRIBUTION**: Who controls access to customers?
- Device platforms (iOS, Android, Windows)
- Enterprise sales channels

For each competitor, identify:
- Which layers they compete with {ticker}
- Which layers they PARTNER with {ticker}
- Net threat assessment considering both

Example: A company might compete at Model layer but be a customer at Infrastructure layer.
This creates a "frenemy" dynamic where {ticker} both loses model revenue but gains cloud revenue.

### BY THREAT TYPE:
1. **MARKET SHARE EROSION**: Direct competitors taking customers
   - Which competitors are growing faster than {ticker}?
   - What market share has {ticker} lost in the last 2 years?

2. **BUSINESS MODEL DISRUPTION**: New models that obsolete current approach
   - Are AI-native competitors changing how the industry works?
   - Are subscription/freemium models threatening ad-based revenue?
   - Is "good enough" free competing with premium paid?

3. **CONSUMER BEHAVIOR SHIFTS**: Changes in how customers use products
   - Are younger cohorts (Gen Z, Gen Alpha) preferring alternatives?
   - Is time-spent shifting to competitors (TikTok vs YouTube)?
   - Are enterprise buyers consolidating vendors?

4. **TECHNOLOGY COMMODITIZATION**: Proprietary advantages eroding
   - Are open-source models catching up to proprietary ones?
   - Is infrastructure becoming commodity (cloud, AI chips)?
   - Can competitors replicate {ticker}'s technology moat?

5. **REGULATORY/LEGAL**: Government actions limiting business
   - Antitrust: breakup risk, forced divestitures, behavior restrictions
   - Privacy: data collection limitations, consent requirements
   - Content: liability for user content, moderation mandates

6. **MACROECONOMIC**: Economic conditions affecting business
   - Ad spending sensitivity to recession
   - Enterprise IT budget cuts affecting cloud
   - Currency headwinds in international markets

## CRITICAL QUESTIONS

For each threat, assess:
- **Probability**: How likely is this threat to materialize?
- **Magnitude**: If it materializes, how much revenue/profit at risk?
- **Velocity**: How quickly is this threat growing?
- **Defensibility**: Can {ticker} respond effectively?

IMPORTANT: You have a HARD LIMIT of {max_searches} web searches. Do NOT exceed this. Be SPECIFIC about competitors and quantify impact where possible.

Return JSON:
```json
{{
  "threats_identified": [
    {{
      "threat_name": "Specific name of threat",
      "threat_type": "market_share|disruption|consumer_behavior|technology|regulatory|macro",
      "threat_source": "legacy_incumbent|startup|open_source|adjacent_entrant|frenemy|government|economic",
      "specific_actor": "Name of company/entity",
      "relationship_complexity": {{
        "competes_at_layers": ["application", "model", "infrastructure", "distribution"],
        "partners_at_layers": ["application", "model", "infrastructure", "distribution"],
        "is_also_customer": true,
        "net_relationship": "pure_competitor|pure_partner|frenemy_net_negative|frenemy_net_positive|frenemy_neutral"
      }},
      "affected_business_lines": ["Search", "Cloud", "YouTube"],
      "current_impact": "none|emerging|material|severe",
      "trajectory": "accelerating|growing|stable|declining",
      "time_horizon": "near_term_0_12mo|medium_term_1_3yr|long_term_3yr_plus",
      "revenue_at_risk_pct": "Estimate: X-Y% of segment revenue",
      "revenue_gained_from_actor": "If frenemy, estimate revenue {ticker} earns FROM this actor",
      "description": "2-3 sentences on the threat with specific data points",
      "company_response": "How is {ticker} responding to this threat?",
      "monitoring_signals": ["Specific metrics to watch"]
    }}
  ],
  "threat_summary": {{
    "most_urgent_threat": "Name of most time-sensitive threat",
    "largest_magnitude_threat": "Name of threat with biggest potential impact",
    "fastest_growing_threat": "Name of threat accelerating most quickly",
    "most_complex_frenemy": "Name of competitor with most complex relationship (both threat and customer)"
  }},
  "searches": [
    {{"query": "what you searched", "finding": "what you found", "source": "source name"}}
  ]
}}
```"""


# =============================================================================
# USER PROMPT TEMPLATE - Loaded from file or fallback
# =============================================================================

DISCOVERY_USER_PROMPT = """## DISCOVERY TASK

Analyze {ticker} ({company_name}) using the 7-lens framework.

TODAY: {date}
CURRENT MONTH/YEAR: {current_month} {current_year}
LATEST QUARTER: {latest_quarter}

## COMPANY CONTEXT (from financial data APIs - this is REAL data, not hallucinated)

{company_context}

## QUARTERLY DATA CONTEXT

{quarter_context}

## 7 MANDATORY LENSES

Complete ALL 7 lenses. Each lens has specific outputs.

### LENS 1: Official Structure (from JSON above)
Extract segments from revenue_by_product. Note quarterly trends.

### LENS 2: Competitive Cross-Reference
Use "competitor-analysis" subagent to search for competitors and peer valuations.

### LENS 3: Analyst Attention
Use "analyst-sentiment" subagent to search for analyst debates and ratings.

### LENS 4: Recent Deals & Developments (last 90 days)
Use "recent-developments" subagent to search for M&A, partnerships, product launches.

### LENS 5: Asset Inventory
Analyze balance sheet and capex for valuable assets not yet monetized as segments.
Look for internal technology that could be sold externally.

### LENS 6: Management Emphasis (from earnings_transcripts in JSON)
Analyze the earnings call transcript to identify CEO/CFO priorities:
- What topics did CEO mention repeatedly? (count mentions)
- What specific forward guidance was given? (quote exact phrases)
- What questions were deflected or given vague answers?
- What competitors were acknowledged?

**IMPORTANT**: When a thread is sourced from transcript analysis, include:
- `"data_source": "transcript"` in current_state
- The actual quote in your reasoning (e.g., "CEO stated: 'AI is our top priority'")
- The quarter referenced (e.g., "Q3 2025 earnings call")

### LENS 7: Blind Spots Synthesis
What value driver might the market be missing? Cross-reference all lenses.

### EXTERNAL THREATS
Use "threat-analysis" subagent to identify competitive, disruption, regulatory, and technology threats.
Map each threat to affected verticals.

## HARD RULES

1. COMPLETE ALL 7 LENSES - each must have output
2. USE ALL 4 SUBAGENTS for web search (competitor-analysis, analyst-sentiment, recent-developments, threat-analysis)
3. AT LEAST ONE NON-OFFICIAL VERTICAL (from Lens 2, 4, 5, or 7)
4. IDENTIFY 3-6 EXTERNAL THREATS with trajectory (growing/stable/declining)
5. SPECIFIC RESEARCH QUESTIONS - not vague like "is growth good?"
6. 5-8 RESEARCH VERTICALS MAX
7. TWO RESEARCH GROUPS - split by business model similarity (Core Business + Growth/Optionality)

Output ONLY JSON matching the schema in your system prompt."""


# =============================================================================
# AGENT CLASS
# =============================================================================

class AnthropicDiscoveryAgent:
    """Discovery Agent using Claude Agent SDK with subagents.

    Architecture:
    - Main orchestrator analyzes CompanyContext (Lenses 1, 5, 6, 7)
    - 4 Sonnet subagents do parallel web search:
      - analyst-sentiment (Lens 3)
      - competitor-analysis (Lens 2)
      - recent-developments (Lens 4)
      - threat-analysis (external threats)
    - Orchestrator synthesizes into 5-8 research verticals + external threats
    """

    def __init__(
        self,
        evidence_store: EvidenceStore | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_searches_per_subagent: int = 5,
    ) -> None:
        """Initialize the Discovery Agent.

        Args:
            evidence_store: Store for persisting evidence. Optional.
            model: Model for subagents (orchestrator always uses what SDK provides).
            max_searches_per_subagent: Max web searches per subagent.
        """
        self.evidence_store = evidence_store
        self.model = model
        self.max_searches = max_searches_per_subagent

    async def run(
        self,
        company_context: CompanyContext,
    ) -> DiscoveryOutput:
        """Execute Discovery using Claude Agent SDK.

        Args:
            company_context: CompanyContext from Stage 1.

        Returns:
            DiscoveryOutput with all discovered research threads.
        """
        ticker = company_context.symbol
        company_name = company_context.company_name

        logger.info(
            "Starting Discovery with Claude Agent SDK",
            ticker=ticker,
            architecture="orchestrator + 4 subagents",
        )

        # Build date context
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B")  # e.g., "January"
        current_year = str(now.year)  # e.g., "2026"

        # Get dynamic quarter from data
        latest_year, latest_qtr = get_latest_quarter_from_data(company_context)
        latest_quarter = format_quarter(latest_year, latest_qtr)
        quarter_context = format_quarters_for_prompt(latest_year, latest_qtr)

        # Build the main prompt
        prompt = DISCOVERY_USER_PROMPT.format(
            ticker=ticker,
            company_name=company_name,
            date=today,
            current_month=current_month,
            current_year=current_year,
            latest_quarter=latest_quarter,
            quarter_context=quarter_context,
            company_context=company_context.for_discovery(),
        )

        # Define the 4 subagents with date context and search limits
        agents = {
            "analyst-sentiment": AgentDefinition(
                description="Searches for analyst ratings, bull/bear cases, price targets",
                prompt=ANALYST_SENTIMENT_PROMPT.format(
                    ticker=ticker,
                    current_month=current_month,
                    current_year=current_year,
                    max_searches=self.max_searches,
                ),
                tools=["WebSearch"],
            ),
            "competitor-analysis": AgentDefinition(
                description="Searches for competitor dynamics and peer valuations",
                prompt=COMPETITOR_ANALYSIS_PROMPT.format(
                    ticker=ticker,
                    current_month=current_month,
                    current_year=current_year,
                    max_searches=self.max_searches,
                ),
                tools=["WebSearch"],
            ),
            "recent-developments": AgentDefinition(
                description="Searches for recent news, M&A, partnerships (last 90 days)",
                prompt=RECENT_DEVELOPMENTS_PROMPT.format(
                    ticker=ticker,
                    current_month=current_month,
                    current_year=current_year,
                    max_searches=self.max_searches,
                ),
                tools=["WebSearch"],
            ),
            "threat-analysis": AgentDefinition(
                description="Searches for external threats: competitive disruption, regulatory, technology shifts",
                prompt=THREAT_ANALYSIS_PROMPT.format(
                    ticker=ticker,
                    current_month=current_month,
                    current_year=current_year,
                    max_searches=self.max_searches,
                ),
                tools=["WebSearch"],
            ),
        }

        # Run the orchestrator with subagents
        # Use timeout and retry logic to handle long-running queries and connection issues
        result_text = ""
        subagent_count = 0
        max_retries = 2
        timeout_seconds = 1800  # 30 minute timeout

        for attempt in range(max_retries + 1):
            try:
                async with asyncio.timeout(timeout_seconds):
                    async for message in query(
                        prompt=prompt,
                        options=ClaudeAgentOptions(
                            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
                            allowed_tools=["WebSearch", "Task"],
                            agents=agents,
                            permission_mode="bypassPermissions",
                        )
                    ):
                        # Track subagent spawns
                        if hasattr(message, 'parent_tool_use_id') and message.parent_tool_use_id:
                            subagent_count += 1

                        # Capture final result
                        if hasattr(message, "result"):
                            result_text = str(message.result)

                # Success - break out of retry loop
                break

            except asyncio.TimeoutError:
                logger.error(f"Discovery timed out after {timeout_seconds}s (attempt {attempt + 1}/{max_retries + 1})")
                if attempt == max_retries:
                    raise TimeoutError(f"Discovery failed after {max_retries + 1} attempts - timed out")
                logger.info("Retrying Discovery...")
                await asyncio.sleep(2)  # Brief pause before retry

            except Exception as e:
                error_str = str(e)
                # Retry on connection failures
                if "exit code 1" in error_str or "connection" in error_str.lower():
                    logger.warning(f"Discovery connection error (attempt {attempt + 1}): {e}")
                    if attempt == max_retries:
                        raise
                    logger.info("Retrying Discovery after connection error...")
                    await asyncio.sleep(5)  # Longer pause for connection issues
                else:
                    logger.error(f"Discovery failed: {e}")
                    raise

        logger.info(
            "Discovery complete",
            ticker=ticker,
            subagents_spawned=subagent_count,
        )

        # Parse the response
        base_evidence_ids = company_context.evidence_ids
        discovery_output = self._parse_response(result_text, base_evidence_ids)

        logger.info(
            "Discovery parsed",
            ticker=ticker,
            thread_count=len(discovery_output.research_threads),
            group_count=len(discovery_output.research_groups),
        )

        return discovery_output

    def _parse_response(
        self,
        content: str,
        base_evidence_ids: tuple[str, ...],
    ) -> DiscoveryOutput:
        """Parse the LLM response into DiscoveryOutput.

        Handles both the new detailed schema (research_verticals) and
        the legacy schema (threads) for backwards compatibility.
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
            logger.warning(f"Failed to parse JSON response: {e}")
            return DiscoveryOutput(
                official_segments=[],
                research_threads=[],
                cross_cutting_themes=[],
                optionality_candidates=[],
                data_gaps=["Failed to parse discovery response"],
                conflicting_signals=[],
                evidence_ids=list(base_evidence_ids),
            )

        # Parse research_verticals (new schema) or threads (legacy schema)
        research_threads = []
        thread_id_map: dict[str, str] = {}

        # Try new schema first (research_verticals), fall back to legacy (threads)
        verticals = data.get("research_verticals", data.get("threads", []))

        for i, v in enumerate(verticals):
            # Determine thread type based on is_official_segment or source_lens
            is_official = v.get("is_official_segment", False)
            source_lens = v.get("source_lens", "").lower()

            if is_official or source_lens in ("lens_1", "official_structure"):
                thread_type = ThreadType.SEGMENT
            elif source_lens in ("lens_5", "asset_inventory", "blind_spots", "lens_7"):
                thread_type = ThreadType.OPTIONALITY
            elif source_lens in ("lens_2", "competitive", "lens_4", "recent"):
                thread_type = ThreadType.CROSS_CUTTING
            else:
                # Fall back to legacy type field
                type_str = v.get("type", "SEGMENT").upper()
                if type_str == "SEGMENT":
                    thread_type = ThreadType.SEGMENT
                elif type_str == "OPTIONALITY":
                    thread_type = ThreadType.OPTIONALITY
                else:
                    thread_type = ThreadType.CROSS_CUTTING

            # Build description from why_it_matters or current_state
            description = v.get("why_it_matters", "")
            current_state = v.get("current_state", {})
            if current_state.get("revenue_usd"):
                description += f" Revenue: ${current_state['revenue_usd']:,.0f}"
            if current_state.get("growth_rate"):
                description += f" Growth: {current_state['growth_rate']:.1%}"

            # Get market debate for hypothesis
            market_debate = v.get("market_debate", {})
            hypothesis = market_debate.get("key_question", v.get("value_driver_hypothesis", v.get("hypothesis", "")))

            # Get research questions
            questions = v.get("research_questions", v.get("questions", []))

            thread = DiscoveredThread.create(
                name=v.get("name", f"Vertical {i+1}"),
                description=description or hypothesis,
                thread_type=thread_type,
                priority=v.get("priority", i + 1),
                discovery_lens=v.get("source_lens", v.get("type", "SEGMENT")),
                is_official_segment=is_official,
                official_segment_name=v.get("name") if is_official else None,
                value_driver_hypothesis=hypothesis,
                research_questions=questions,
                evidence_ids=list(base_evidence_ids),
            )
            research_threads.append(thread)
            vertical_id = v.get("id", f"v{i+1}")
            thread_id_map[vertical_id] = thread.thread_id

        # Parse research_groups from response or create defaults
        research_groups = []
        response_groups = data.get("research_groups", {})

        if response_groups:
            # Parse groups from response
            for group_key, group_data in response_groups.items():
                vertical_ids_in_group = group_data.get("verticals", [])
                # Map vertical IDs to thread IDs
                mapped_ids = [thread_id_map.get(vid, vid) for vid in vertical_ids_in_group]

                research_groups.append(ResearchGroup(
                    group_id=generate_id("group"),
                    name=group_data.get("name", group_key),
                    theme=group_data.get("theme", ""),
                    vertical_ids=mapped_ids,
                    key_questions=group_data.get("key_questions", []),
                    grouping_rationale=group_data.get("grouping_rationale", ""),
                    shared_context=group_data.get("shared_context", ""),
                    valuation_approach=group_data.get("valuation_approach", "DCF"),
                    focus=group_data.get("theme", ""),
                ))
        else:
            # Create default groups based on thread types
            core_threads = [t for t in research_threads if t.thread_type == ThreadType.SEGMENT]
            growth_threads = [t for t in research_threads if t.thread_type != ThreadType.SEGMENT]

            if core_threads:
                research_groups.append(ResearchGroup(
                    group_id=generate_id("group"),
                    name="Core Business",
                    theme="Official segments and established revenue streams",
                    vertical_ids=[t.thread_id for t in core_threads],
                    key_questions=["What are the growth trajectories?", "How are margins evolving?"],
                    grouping_rationale="Established business segments",
                    shared_context="Official 10-K segments",
                    valuation_approach="DCF",
                    focus="Financial performance",
                ))

            if growth_threads:
                research_groups.append(ResearchGroup(
                    group_id=generate_id("group"),
                    name="Growth & Optionality",
                    theme="Hidden value drivers and strategic opportunities",
                    vertical_ids=[t.thread_id for t in growth_threads],
                    key_questions=["What hidden value exists?", "What optionalities might the market miss?"],
                    grouping_rationale="Non-traditional value drivers",
                    shared_context="Strategic initiatives and hidden assets",
                    valuation_approach="Option value",
                    focus="Optionality and strategic value",
                ))

        # Extract official segments from lens_outputs or threads
        lens_outputs = data.get("lens_outputs", {})
        official_structure = lens_outputs.get("official_structure", {})
        official_segments = [s.get("name") for s in official_structure.get("segments", [])]
        if not official_segments:
            official_segments = [t.name for t in research_threads if t.is_official_segment]

        # Data gaps - from critical_information_gaps or data_gaps
        data_gaps = data.get("critical_information_gaps", data.get("data_gaps", []))

        # Searches performed
        searches_performed = data.get("searches_performed", [])

        # External threats - from threat-analysis subagent
        external_threats = data.get("external_threats", [])

        return DiscoveryOutput(
            official_segments=official_segments,
            research_threads=research_threads,
            research_groups=research_groups,
            cross_cutting_themes=[],
            optionality_candidates=[t.name for t in research_threads if t.thread_type == ThreadType.OPTIONALITY],
            data_gaps=data_gaps,
            conflicting_signals=[],
            evidence_ids=list(base_evidence_ids),
            thread_briefs=[],
            searches_performed=searches_performed,
            lens_outputs=lens_outputs,  # Preserve for Stage 3
            external_threats=external_threats,  # Preserve for Stage 3
        )
