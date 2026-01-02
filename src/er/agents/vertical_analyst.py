"""
Vertical Analyst Agent (Stage 3).

Deep dives into research groups using OpenAI o4-mini Deep Research.
Runs 2 parallel instances - one per research group.

Model: o4-mini-deep-research (with web search)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.openai_client import OpenAIClient
from er.types import (
    CompanyContext,
    DiscoveredThread,
    GroupResearchOutput,
    Phase,
    ResearchGroup,
    RunState,
    VerticalAnalysis,
)


# Deep Research prompt template - handles multiple verticals in a research group
DEEP_RESEARCH_PROMPT = """You are a Deep Research Analyst for an institutional equity research system.

## CRITICAL: DATE AND DATA GROUNDING

TODAY IS: {date}
CURRENT MONTH: {current_month} {current_year}

Your training data is STALE. You MUST use web search for anything that may have changed.

## QUARTERLY DATA IS THE LATEST

The JSON contains data through Q3 2025:
- Q3 2025 = MOST RECENT (use this as baseline)
- Q2 2025, Q1 2025 = Recent quarters (analyze the TREND)
- FY 2024 = OLD - one year ago, historical context only

ALWAYS cite quarterly data. "Q3 2025 revenue was $X" not "annual revenue is $Y"

**DO NOT USE FY2024** as "current" state. FY2024 data is 12+ months old. Only use for historical comparison.

## GROUND TRUTH DATA (DO NOT CONTRADICT)

```json
{company_context}
```

## YOUR RESEARCH ASSIGNMENT

Company: {ticker} ({company_name})
Research Group: **{group_name}**
Theme: {group_theme}
Focus: {group_focus}

### Verticals to Research:
{verticals_detail}

## CO-ANALYST COORDINATION

You are NOT the only Deep Research agent. Your co-analyst is researching other verticals in parallel.

**Your co-analyst is researching:**
{other_groups_detail}

**Coordination Rules:**
1. **DO NOT duplicate their work** - If a topic belongs to their group, don't deep-dive it
2. **Note cross-references briefly** - If you find info relevant to their verticals, mention it in "cross_vertical_insights" but don't analyze it in depth
3. **Focus on YOUR verticals** - Your time and tokens are limited. Go deep on your assignment, not broad on everything
4. **Trust the synthesizer** - A synthesis agent will combine both analyses later. You don't need the complete picture alone.

**Example:** If your co-analyst is researching "Google Cloud", and you find a news article about cloud competition while researching "AI/ML Infrastructure", just note "See co-analyst's Google Cloud analysis for competitive dynamics" - don't analyze AWS vs GCP yourself.

## CRITICAL: USE DISCOVERY OUTPUT

Discovery Agent already identified the verticals and research questions. Your job is to ANSWER those questions, not re-discover.

For each vertical in your group:
- Discovery gave you research questions. Answer them.
- Discovery gave you a hypothesis. Validate or refute it.
- Discovery identified data gaps. Fill them.

Do NOT:
- Ignore the research questions and do your own thing
- Skip verticals Discovery assigned to you
- Invent new verticals (that was Discovery's job)

## MANDATORY WEB SEARCHES

You MUST execute targeted searches. Claiming to search without actually searching is detectable and a failure.

### What You Already Have (DO NOT SEARCH FOR):
- Revenue numbers → in JSON (income_statement_quarterly)
- Growth rates → calculable from JSON
- Margins → in JSON
- Segment breakdown → in JSON (revenue_product_segmentation)

### What You MUST Search For (NOT in JSON):

1. **Competitive position:** "{ticker} vs [competitor] [vertical] market share 2025"
2. **Competitor moves:** "[main competitor] [vertical] announcement {current_year}"
3. **Recent developments:** "{ticker} [vertical] news {current_month} {current_year}"
4. **Analyst views:** "{ticker} [vertical] analyst outlook 2025"
5. **Industry trends:** "[vertical industry] growth forecast 2025"

### Search Quality Requirements:

- **NEVER search for revenue/growth/margins** - you have this in JSON
- Search for CONTEXT: market share, competitive moves, analyst views, news
- Use SPECIFIC queries with dates
- BAD: "Google Cloud" → too vague, might return financials you shouldn't use
- GOOD: "Google Cloud vs AWS market share Q3 2025"
- GOOD: "AWS re:Invent 2025 announcements" (competitor context)

### You Must Report:
```json
"searches_performed": [
  {{
    "query": "exact query you used",
    "source_found": "publication name",
    "date_of_source": "YYYY-MM-DD",
    "key_finding": "what you learned"
  }}
]
```

**If you list fewer than 6 searches per group, you haven't searched enough for competitive/market context.**

## RESEARCH METHODOLOGY

For EACH vertical:

### 1. Financial Analysis (FROM JSON ONLY)
- Q3 2025 revenue and growth
- Q1->Q2->Q3 2025 trend (accelerating/decelerating?)
- Margin trajectory if available
- DO NOT invent numbers. Use JSON or say "not available"

### 2. Competitive Position (WEB SEARCH REQUIRED)
- Current market share (cite source, cite date)
- Key competitors and their recent moves
- Moat assessment - is it strengthening or weakening?
- Search for "[competitor] news {current_month} {current_year}"

### 3. Recent Developments (WEB SEARCH REQUIRED)
- What happened in the last 60 days?
- Product launches, partnerships, leadership changes
- Analyst upgrades/downgrades
- DO NOT use training data. SEARCH.

### 4. Key Uncertainties
What are the open questions that could swing the outlook either way?
- What would need to happen for this vertical to significantly outperform?
- What would need to happen for it to significantly underperform?
- Be SPECIFIC. Not "growth could slow" but "if [metric] changes to [X]"

## OUTPUT REQUIREMENTS

**Write tight, information-dense prose. Target 3,000-4,000 tokens per vertical.**

Output your analysis as a structured research report in markdown. NO JSON output.

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

### Output Structure (for each vertical):

---

## [VERTICAL NAME]

### Overview
3-4 sentences. What is this vertical and what does it do? (Factual, no opinion)

### Financial Performance (FROM JSON ONLY)
- Q3 2025 revenue: $X (+Y% YoY)
- Quarterly trajectory: Q1→Q2→Q3 trend (accelerating/stable/decelerating)
- Margin: X% or "not disclosed"
- Source: Cite which JSON field you used

### Competitive Landscape (WEB SEARCH REQUIRED)
- Market position: Leader/Challenger/Follower
- Market share: X% (source: [publication], date: [when])
- Key competitors and their recent moves
- Competitive dynamics: What's changing in the market?
- Moat characteristics: What advantages exist? Are they strengthening or weakening?

### Recent Developments (last 60 days)
List 3-5 key events with dates and sources. For each:
- What happened
- Factual impact on this vertical
- Source (publication name)

### Growth Dynamics
**Tailwinds** (factors that could accelerate growth):
- Tailwind 1: [magnitude: high/med/low] - evidence
- Tailwind 2: [magnitude: high/med/low] - evidence

**Headwinds** (factors that could slow growth):
- Headwind 1: [magnitude: high/med/low] - evidence
- Headwind 2: [magnitude: high/med/low] - evidence

TAM estimate: $X (source)

### Risk Factors
For each risk, include ALL of: probability, impact, trigger, mitigant
- **Risk 1**: [prob: H/M/L, impact: H/M/L]
  - Trigger: What would cause this
  - Mitigant: What reduces this risk

### Key Uncertainties
What questions remain unanswered that could materially affect this vertical?
- Uncertainty 1: [what we don't know and why it matters]
- Uncertainty 2: [what we don't know and why it matters]

What metrics/events to watch:
- If [X happens], it would suggest [positive/negative for growth]
- If [Y happens], it would suggest [positive/negative for growth]

### Research Quality
- Data quality: good/limited/poor
- Sources used: [list publications]
- Gaps: [what we couldn't find or verify]

---

### At the end, add:

## Cross-Vertical Observations for {group_name}
- **Interconnections**: How do verticals in this group interact with each other?
- **Shared exposures**: What factors affect multiple verticals?
- **Key questions for synthesis**: What should the investment analyst consider when forming a view?

## Web Searches Performed
List all searches with: query, source found, date of source, key finding

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

1. **JSON = FINANCIALS** - All revenue, growth, margin numbers come from JSON. Never use web search numbers for financials.

2. **WEB SEARCH = CONTEXT** - Search for: market share, competitive moves, analyst views, recent news, industry trends. NOT for financials.

3. **QUARTERLY DATA FIRST** - Q3 2025 > Q2 2025 > Q1 2025 >> FY2024. If you cite FY2024 as "current," you've failed.

4. **ANSWER DISCOVERY'S QUESTIONS** - Each vertical came with research questions. Answer them explicitly.

5. **CONFIDENCE = EVIDENCE** - High confidence requires multiple recent sources. No exceptions.

6. **CITE DATES** - Every non-JSON claim needs a date. "Market share is 25%" means nothing without "as of Q3 2025 per [source]."

7. **8K TOKENS MAX PER VERTICAL** - Be ruthless. Cut fluff. Keep analysis.

8. **ADMIT GAPS** - If you can't find something, say so. List it in unanswered_questions. Don't fabricate."""


class VerticalAnalystAgent(Agent):
    """Stage 3: Vertical Analyst (Deep Research).

    Responsible for:
    1. Deep diving into a research group (multiple verticals)
    2. Analyzing competitive position and growth drivers
    3. Developing bull and bear cases
    4. Using OpenAI o4-mini Deep Research with web search

    Uses OpenAI o4-mini Deep Research for web-enhanced analysis.
    Two instances run in parallel - one per research group.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Vertical Analyst.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._openai_client: OpenAIClient | None = None

    @property
    def name(self) -> str:
        return "vertical_analyst"

    @property
    def role(self) -> str:
        return "Deep dive analysis of research groups with web research"

    async def _get_openai_client(self) -> OpenAIClient:
        """Get or create OpenAI client for Deep Research."""
        if self._openai_client is None:
            self._openai_client = OpenAIClient(
                api_key=self.settings.OPENAI_API_KEY,
            )
        return self._openai_client

    async def run_group(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        research_group: ResearchGroup,
        threads: list[DiscoveredThread],
        use_deep_research: bool = True,
        other_groups: list[tuple[ResearchGroup, list[DiscoveredThread]]] | None = None,
        **kwargs: Any,
    ) -> GroupResearchOutput:
        """Execute Stage 3: Deep Research for a research group.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            research_group: The research group to analyze.
            threads: The threads/verticals within this group.
            use_deep_research: Whether to use deep research.
            other_groups: Other research groups being analyzed in parallel.
                          List of (ResearchGroup, threads) tuples. Used for
                          co-analyst coordination to avoid duplicate work.

        Returns:
            GroupResearchOutput with all vertical analyses.
        """
        self.log_info(
            "Starting group research",
            ticker=run_state.ticker,
            group=research_group.name,
            vertical_count=len(threads),
            use_deep_research=use_deep_research,
        )

        run_state.phase = Phase.VERTICALS

        # Build verticals detail section
        verticals_detail = ""
        for i, thread in enumerate(threads, 1):
            questions = "\n".join(f"      - {q}" for q in thread.research_questions)
            verticals_detail += f"""
**Vertical {i}: {thread.name}**
- Type: {thread.thread_type.value}
- Priority: {thread.priority}
- Description: {thread.description}
- Hypothesis: {thread.value_driver_hypothesis}
- Research Questions:
{questions}
"""

        # Build other groups detail for co-analyst coordination
        if other_groups:
            other_groups_detail = ""
            for other_group, other_threads in other_groups:
                verticals_list = ", ".join(t.name for t in other_threads)
                other_groups_detail += f"""
**Group: {other_group.name}**
- Theme: {other_group.theme}
- Verticals: {verticals_list}
"""
        else:
            other_groups_detail = "(No other groups - you are the only analyst)"

        # Build the prompt
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        current_month = now.strftime("%B")
        current_year = now.strftime("%Y")

        prompt = DEEP_RESEARCH_PROMPT.format(
            date=today,
            current_month=current_month,
            current_year=current_year,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            group_name=research_group.name,
            group_theme=research_group.theme,
            group_focus=research_group.focus,
            verticals_detail=verticals_detail,
            other_groups_detail=other_groups_detail,
            company_context=company_context.to_prompt_string(max_tokens=15000),
        )

        # Get OpenAI client
        openai_client = await self._get_openai_client()

        # Run analysis
        if use_deep_research:
            self.log_info(
                "Using OpenAI o4-mini Deep Research",
                ticker=run_state.ticker,
                group=research_group.name,
            )
            response = await openai_client.deep_research(
                query=prompt,
                model="o4-mini-deep-research-2025-06-26",
                poll_interval=15.0,
                max_wait_seconds=900.0,  # 15 minutes max
            )
        else:
            # Use regular GPT with web search
            from er.llm.base import LLMRequest

            self.log_info(
                "Using GPT-5.2 with web search",
                ticker=run_state.ticker,
                group=research_group.name,
            )
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-5.2",
                temperature=0.3,
                max_tokens=32000,
            )
            response = await openai_client.complete_with_web_search(
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
                phase="verticals",
            )

        # Parse the response
        group_output = self._parse_group_response(
            response.content,
            research_group,
            threads,
            company_context.evidence_ids,
        )

        self.log_info(
            "Completed group research",
            ticker=run_state.ticker,
            group=research_group.name,
            vertical_count=len(group_output.vertical_analyses),
            overall_confidence=group_output.overall_confidence,
        )

        return group_output

    def _parse_group_response(
        self,
        content: str,
        research_group: ResearchGroup,
        threads: list[DiscoveredThread],
        base_evidence_ids: tuple[str, ...],
    ) -> GroupResearchOutput:
        """Parse the LLM prose response into GroupResearchOutput.

        The Deep Research agent outputs structured markdown prose.
        We extract key sections and store the full prose for synthesis.

        Args:
            content: Raw LLM response (markdown prose).
            research_group: The research group.
            threads: Threads in this group.
            base_evidence_ids: Evidence IDs from CompanyContext.

        Returns:
            Parsed GroupResearchOutput.
        """
        # Split content by vertical sections (## VERTICAL NAME)
        vertical_sections = re.split(r'\n## (?=[A-Z])', content)

        vertical_analyses = []
        cross_vertical_section = ""
        web_searches_section = ""

        for section in vertical_sections:
            if not section.strip():
                continue

            # Check for special sections
            if section.startswith("Cross-Vertical Insights") or section.startswith("cross-vertical"):
                cross_vertical_section = section
                continue
            if section.startswith("Web Searches Performed") or section.startswith("web searches"):
                web_searches_section = section
                continue

            # Extract vertical name (first line)
            lines = section.strip().split('\n')
            if not lines:
                continue

            v_name = lines[0].strip().strip('#').strip()
            if not v_name or v_name.lower() in ['confidence calibration', 'hard rules', 'output requirements']:
                continue

            # Find matching thread
            thread = None
            for t in threads:
                if t.name.lower() in v_name.lower() or v_name.lower() in t.name.lower():
                    thread = t
                    break
            if not thread and threads:
                # Try looser matching
                for t in threads:
                    if any(word in v_name.lower() for word in t.name.lower().split()):
                        thread = t
                        break
            if not thread and threads:
                thread = threads[0]  # Fallback

            # Extract confidence if available
            confidence = 0.5
            conf_match = re.search(r'Confidence:\s*(\d+)/10', section)
            if conf_match:
                confidence = float(conf_match.group(1)) / 10

            # Store full prose - that's all we need
            vertical_analysis = VerticalAnalysis(
                thread_id=thread.thread_id if thread else "",
                vertical_name=v_name,
                business_understanding=section,  # Full prose for synthesizer
                evidence_ids=list(base_evidence_ids),
                overall_confidence=confidence,
            )
            vertical_analyses.append(vertical_analysis)

        # Extract cross-vertical insights
        synergies = ""
        shared_risks = ""
        group_thesis = ""
        if cross_vertical_section:
            syn_match = re.search(r'\*\*Synergies\*\*:?\s*(.+?)(?=\*\*|\Z)', cross_vertical_section, re.DOTALL)
            if syn_match:
                synergies = syn_match.group(1).strip()
            risk_match = re.search(r'\*\*Shared risks\*\*:?\s*(.+?)(?=\*\*|\Z)', cross_vertical_section, re.DOTALL)
            if risk_match:
                shared_risks = risk_match.group(1).strip()
            thesis_match = re.search(r'\*\*Group thesis\*\*:?\s*(.+?)(?=\*\*|\Z)', cross_vertical_section, re.DOTALL)
            if thesis_match:
                group_thesis = thesis_match.group(1).strip()

        # Calculate overall confidence
        if vertical_analyses:
            avg_confidence = sum(v.overall_confidence for v in vertical_analyses) / len(vertical_analyses)
        else:
            avg_confidence = 0.0

        # If we got no verticals but have content, create one from full content
        if not vertical_analyses and content.strip():
            self.log_warning("Could not parse vertical sections, storing full response")
            # Store full content as single analysis
            if threads:
                thread = threads[0]
                vertical_analyses.append(
                    VerticalAnalysis(
                        thread_id=thread.thread_id,
                        vertical_name=thread.name,
                        business_understanding=content,  # Full prose
                        evidence_ids=list(base_evidence_ids),
                        overall_confidence=0.5,
                    )
                )

        return GroupResearchOutput(
            group_id=research_group.group_id,
            group_name=research_group.name,
            vertical_analyses=vertical_analyses,
            synergies=synergies,
            shared_risks=shared_risks,
            group_thesis=group_thesis,
            web_searches_performed=[],  # Prose format doesn't have structured search list
            overall_confidence=avg_confidence,
            data_gaps=[],
            evidence_ids=list(base_evidence_ids),
        )

    # Keep legacy single-vertical method for backwards compatibility
    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        thread: DiscoveredThread,
        use_deep_research: bool = True,
        **kwargs: Any,
    ) -> VerticalAnalysis:
        """Execute Stage 3: Vertical Analysis for a single thread (legacy).

        For backwards compatibility. Wraps the thread in a group and runs.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            thread: The research thread to analyze.
            use_deep_research: Whether to use deep research.

        Returns:
            VerticalAnalysis with deep dive results.
        """
        # Create a synthetic group with just this thread
        synthetic_group = ResearchGroup(
            group_id=f"single_{thread.thread_id}",
            name=thread.name,
            theme=thread.description,
            focus=thread.value_driver_hypothesis,
            vertical_ids=[thread.thread_id],
            key_questions=list(thread.research_questions),
        )

        group_output = await self.run_group(
            run_state,
            company_context,
            synthetic_group,
            [thread],
            use_deep_research,
        )

        # Return the first (and only) vertical analysis
        if group_output.vertical_analyses:
            return group_output.vertical_analyses[0]
        else:
            # Return error analysis
            return VerticalAnalysis(
                thread_id=thread.thread_id,
                vertical_name=thread.name,
                business_understanding="Failed to analyze",
                evidence_ids=list(company_context.evidence_ids),
                overall_confidence=0.0,
            )

    async def close(self) -> None:
        """Close any open clients."""
        if self._openai_client:
            await self._openai_client.close()
            self._openai_client = None
