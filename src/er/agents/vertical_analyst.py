"""
Vertical Analyst Agent (Stage 3).

Deep dives into a single research thread/vertical using o4-mini-deep-research.
Multiple instances run in parallel for different verticals.

Model: o4-mini-deep-research (with web search)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.openai_client import OpenAIClient
from er.types import (
    CompanyContext,
    DiscoveredThread,
    Phase,
    Risk,
    RunState,
    ThesisCase,
    VerticalAnalysis,
)


# Vertical analysis prompt template
VERTICAL_ANALYST_PROMPT = """You are a Vertical Analyst for an institutional equity research system.

TODAY'S DATE: {date}
COMPANY: {ticker} ({company_name})
YOUR VERTICAL: {vertical_name}

## CRITICAL INSTRUCTION
DO NOT rely on training data for financials - use ONLY the provided CompanyContext below.
Use web search to find recent developments, competitive intelligence, and analyst opinions.

## CompanyContext (Ground Truth Data)
{company_context}

## Your Assigned Vertical
Name: {vertical_name}
Type: {thread_type}
Priority: {priority}
Description: {description}
Hypothesis: {hypothesis}

## Research Questions to Answer
{research_questions}

## Your Task: Deep Dive Analysis

### 1. Business Understanding
- What is this vertical/segment? How does it make money?
- What's the revenue model? Key customers?
- What are the unit economics (if discoverable)?

### 2. Competitive Position
- Who are the direct competitors?
- What's the market share situation?
- What's the moat (if any)? Is it widening or narrowing?

### 3. Growth Drivers
- What drives growth in this vertical?
- TAM analysis - how big is the opportunity?
- What's the growth rate? Is it accelerating or decelerating?

### 4. Key Risks
- What could go wrong?
- Competitive threats, regulatory risk, execution risk?
- Technology disruption risk?

### 5. Bull Case
- What has to go right for this vertical to significantly exceed expectations?
- What would the key metrics look like?
- What catalysts would prove this case?

### 6. Bear Case
- What has to go wrong for this vertical to disappoint?
- What would trigger a bearish scenario?
- What are the warning signs to watch?

## Output Requirements

You MUST output valid JSON with this exact structure:

```json
{{
  "business_understanding": "Detailed explanation of this vertical's business model",
  "competitive_position": "Analysis of competitive dynamics and positioning",
  "growth_drivers": ["List of key growth drivers"],
  "key_risks": [
    {{
      "name": "Risk name",
      "description": "What the risk is",
      "probability": "high|medium|low",
      "impact": "high|medium|low",
      "mitigants": ["What could reduce this risk"]
    }}
  ],
  "bull_case": {{
    "thesis": "The bull case narrative",
    "key_assumptions": ["Assumptions that must be true"],
    "key_metrics": ["Metrics to watch"],
    "catalysts": ["Events that would prove the bull case"],
    "confidence": 0.7
  }},
  "bear_case": {{
    "thesis": "The bear case narrative",
    "key_assumptions": ["Assumptions for the bear case"],
    "key_metrics": ["Warning metrics"],
    "catalysts": ["Events that would prove the bear case"],
    "confidence": 0.3
  }},
  "overall_confidence": 0.65,
  "confidence_drivers": ["What gives you confidence", "What reduces confidence"],
  "unanswered_questions": ["Questions you couldn't fully answer"],
  "data_gaps": ["Data you couldn't find"]
}}
```

## Hard Rules

1. NO CLAIMS WITHOUT EVIDENCE - cite specific sources for material claims
2. Use confidence < 0.5 if evidence is thin
3. Flag what you couldn't find explicitly
4. Be specific about competitors and market dynamics
5. Quantify where possible (market size, growth rates, market share)
6. Distinguish between facts and your inferences
"""


class VerticalAnalystAgent(Agent):
    """Stage 3: Vertical Analyst.

    Responsible for:
    1. Deep diving into a single research thread/vertical
    2. Analyzing competitive position and growth drivers
    3. Developing bull and bear cases
    4. Using web search for recent information

    Uses o4-mini-deep-research for web-enhanced analysis.
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
        return "Deep dive analysis of a single vertical with web research"

    async def _get_openai_client(self) -> OpenAIClient:
        """Get or create OpenAI client for Deep Research."""
        if self._openai_client is None:
            self._openai_client = OpenAIClient(
                api_key=self.settings.OPENAI_API_KEY,
            )
        return self._openai_client

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        thread: DiscoveredThread,
        use_deep_research: bool = True,
        **kwargs: Any,
    ) -> VerticalAnalysis:
        """Execute Stage 3: Vertical Analysis for a single thread.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            thread: The research thread to analyze.
            use_deep_research: Whether to use deep research (vs regular completion).

        Returns:
            VerticalAnalysis with deep dive results.
        """
        self.log_info(
            "Starting vertical analysis",
            ticker=run_state.ticker,
            vertical=thread.name,
            thread_id=thread.thread_id,
            use_deep_research=use_deep_research,
        )

        run_state.phase = Phase.VERTICALS

        # Build the prompt
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        research_questions = "\n".join(
            f"- {q}" for q in thread.research_questions
        )

        prompt = VERTICAL_ANALYST_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            vertical_name=thread.name,
            thread_type=thread.thread_type.value,
            priority=thread.priority,
            description=thread.description,
            hypothesis=thread.value_driver_hypothesis,
            research_questions=research_questions,
            company_context=company_context.to_prompt_string(max_tokens=12000),
        )

        # Get OpenAI client
        openai = await self._get_openai_client()

        # Run analysis
        if use_deep_research:
            # Use o4-mini-deep-research for web-enhanced analysis
            self.log_info(
                "Using deep research",
                ticker=run_state.ticker,
                vertical=thread.name,
            )
            response = await openai.deep_research(
                query=prompt,
                system_message="You are a senior equity research analyst performing deep analysis on a single business vertical.",
                poll_interval=10.0,
                max_wait_seconds=600.0,
            )
        else:
            # Use regular GPT-5.2 with reasoning
            from er.llm.base import LLMRequest

            self.log_info(
                "Using GPT-5.2 with reasoning",
                ticker=run_state.ticker,
                vertical=thread.name,
            )
            request = LLMRequest(
                messages=[
                    {"role": "system", "content": "You are a senior equity research analyst."},
                    {"role": "user", "content": prompt},
                ],
                model="gpt-5.2",
                temperature=0.3,
                max_tokens=8000,
            )
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
                phase="verticals",
            )

        # Parse the response
        vertical_analysis = self._parse_response(
            response.content,
            thread,
            company_context.evidence_ids,
        )

        self.log_info(
            "Completed vertical analysis",
            ticker=run_state.ticker,
            vertical=thread.name,
            confidence=vertical_analysis.overall_confidence,
            risk_count=len(vertical_analysis.key_risks),
        )

        return vertical_analysis

    def _parse_response(
        self,
        content: str,
        thread: DiscoveredThread,
        base_evidence_ids: tuple[str, ...],
    ) -> VerticalAnalysis:
        """Parse the LLM response into VerticalAnalysis.

        Args:
            content: Raw LLM response.
            thread: The research thread being analyzed.
            base_evidence_ids: Evidence IDs from CompanyContext.

        Returns:
            Parsed VerticalAnalysis.
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
            return VerticalAnalysis(
                thread_id=thread.thread_id,
                vertical_name=thread.name,
                business_understanding="Failed to parse response",
                competitive_position="",
                growth_drivers=[],
                key_risks=[],
                bull_case=ThesisCase(
                    thesis="",
                    key_assumptions=[],
                    key_metrics=[],
                    catalysts=[],
                    confidence=0.0,
                ),
                bear_case=ThesisCase(
                    thesis="",
                    key_assumptions=[],
                    key_metrics=[],
                    catalysts=[],
                    confidence=0.0,
                ),
                overall_confidence=0.0,
                confidence_drivers=["Parse error"],
                unanswered_questions=["Failed to parse response"],
                data_gaps=["Failed to parse response"],
                evidence_ids=list(base_evidence_ids),
            )

        # Parse risks
        risks = []
        for r in data.get("key_risks", []):
            risks.append(
                Risk(
                    name=r.get("name", "Unknown"),
                    description=r.get("description", ""),
                    probability=r.get("probability", "medium"),
                    impact=r.get("impact", "medium"),
                    mitigants=r.get("mitigants", []),
                )
            )

        # Parse thesis cases
        bull_data = data.get("bull_case", {})
        bull_case = ThesisCase(
            thesis=bull_data.get("thesis", ""),
            key_assumptions=bull_data.get("key_assumptions", []),
            key_metrics=bull_data.get("key_metrics", []),
            catalysts=bull_data.get("catalysts", []),
            confidence=bull_data.get("confidence", 0.5),
        )

        bear_data = data.get("bear_case", {})
        bear_case = ThesisCase(
            thesis=bear_data.get("thesis", ""),
            key_assumptions=bear_data.get("key_assumptions", []),
            key_metrics=bear_data.get("key_metrics", []),
            catalysts=bear_data.get("catalysts", []),
            confidence=bear_data.get("confidence", 0.5),
        )

        return VerticalAnalysis(
            thread_id=thread.thread_id,
            vertical_name=thread.name,
            business_understanding=data.get("business_understanding", ""),
            competitive_position=data.get("competitive_position", ""),
            growth_drivers=data.get("growth_drivers", []),
            key_risks=risks,
            bull_case=bull_case,
            bear_case=bear_case,
            overall_confidence=data.get("overall_confidence", 0.5),
            confidence_drivers=data.get("confidence_drivers", []),
            unanswered_questions=data.get("unanswered_questions", []),
            data_gaps=data.get("data_gaps", []),
            evidence_ids=list(base_evidence_ids),
        )

    async def close(self) -> None:
        """Close any open clients."""
        if self._openai_client:
            await self._openai_client.close()
            self._openai_client = None
