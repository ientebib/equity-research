"""
Synthesizer Agent (Stage 4).

Dual synthesis: Claude Opus 4.5 and GPT-5.2 run in parallel,
each producing an independent investment thesis.

Models:
- Claude Opus 4.5 (extended thinking, budget_tokens: 15000)
- GPT-5.2 (reasoning_effort: "xhigh")
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.anthropic_client import AnthropicClient
from er.llm.base import LLMRequest
from er.llm.openai_client import OpenAIClient
from er.types import (
    CompanyContext,
    DiscoveryOutput,
    KeyDebate,
    Phase,
    RiskFactor,
    RunState,
    Scenario,
    SynthesisOutput,
    VerticalAnalysis,
)


# Synthesis prompt template
SYNTHESIS_PROMPT = """You are a senior equity research synthesizer producing an investment thesis.

TODAY'S DATE: {date}
COMPANY: {ticker} ({company_name})

## CRITICAL INSTRUCTION
You have been given vertical analyses from multiple specialist analysts.
Your job is to synthesize ALL inputs into a UNIFIED investment thesis.
DO NOT rely on training data - use ONLY the provided analyses and data.

## CompanyContext (Ground Truth Data)
{company_context}

## Discovery Insights
Official Segments: {official_segments}
Cross-Cutting Themes: {cross_cutting_themes}
Optionality Candidates: {optionality_candidates}

## Vertical Analyses
{vertical_analyses}

## Your Task: Unified Synthesis

### 1. Investment View
Form a clear BUY/HOLD/SELL recommendation with conviction level (high/medium/low).
Justify your view with specific evidence from the vertical analyses.

### 2. Thesis Summary
Write a 3-4 sentence summary of the investment thesis that a portfolio manager could read in 30 seconds.

### 3. Scenarios
Develop bull, base, and bear cases:
- What assumptions drive each scenario?
- What's the probability you assign to each?
- What would prove or disprove each case?

### 4. Key Debates
Where do the vertical analyses conflict or highlight uncertainty?
What are the most important questions for the investment case?
For each debate, give bull view, bear view, and YOUR view.

### 5. Risk Assessment
What are the top 5 risks? Rank by probability × impact.
Which risks are priced in vs. underappreciated?

## Output Requirements

You MUST output valid JSON with this exact structure:

```json
{{
  "investment_view": "BUY|HOLD|SELL",
  "conviction": "high|medium|low",
  "thesis_summary": "3-4 sentence summary",
  "scenarios": {{
    "bull": {{
      "name": "bull",
      "probability": 0.25,
      "narrative": "Bull case narrative",
      "key_assumptions": ["Assumption 1", "Assumption 2"]
    }},
    "base": {{
      "name": "base",
      "probability": 0.50,
      "narrative": "Base case narrative",
      "key_assumptions": ["Assumption 1", "Assumption 2"]
    }},
    "bear": {{
      "name": "bear",
      "probability": 0.25,
      "narrative": "Bear case narrative",
      "key_assumptions": ["Assumption 1", "Assumption 2"]
    }}
  }},
  "key_debates": [
    {{
      "topic": "Debate topic",
      "bull_view": "The bullish perspective",
      "bear_view": "The bearish perspective",
      "our_view": "Your synthesized view"
    }}
  ],
  "risk_factors": [
    {{
      "name": "Risk name",
      "description": "What the risk is",
      "probability": "high|medium|low",
      "impact": "high|medium|low",
      "priced_in": true,
      "mitigation": "What could mitigate this"
    }}
  ],
  "overall_confidence": 0.7,
  "evidence_gaps": ["What we don't know"]
}}
```

## Hard Rules

1. NO CLAIMS WITHOUT EVIDENCE - synthesize from provided analyses only
2. Scenarios must sum to ~1.0 probability
3. Every debate must have bull_view, bear_view, AND our_view
4. Risks should be ranked by probability × impact
5. Flag confidence < 0.5 if key inputs are conflicting or thin
6. DO NOT produce a DCF - this is qualitative analysis only
"""


class SynthesizerAgent(Agent):
    """Stage 4: Dual Synthesizer.

    Responsible for:
    1. Running Claude and GPT synthesis in parallel
    2. Each produces independent investment thesis
    3. No coordination between the two - adversarial by design

    Uses:
    - Claude Opus 4.5 with extended thinking (budget_tokens: 15000)
    - GPT-5.2 with reasoning (effort: "xhigh")
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Synthesizer.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._anthropic_client: AnthropicClient | None = None
        self._openai_client: OpenAIClient | None = None

    @property
    def name(self) -> str:
        return "synthesizer"

    @property
    def role(self) -> str:
        return "Dual parallel synthesis of vertical analyses into investment thesis"

    async def _get_anthropic_client(self) -> AnthropicClient:
        """Get or create Anthropic client."""
        if self._anthropic_client is None:
            self._anthropic_client = AnthropicClient(
                api_key=self.settings.ANTHROPIC_API_KEY,
            )
        return self._anthropic_client

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
        discovery_output: DiscoveryOutput,
        vertical_analyses: list[VerticalAnalysis],
        **kwargs: Any,
    ) -> tuple[SynthesisOutput, SynthesisOutput]:
        """Execute Stage 4: Dual Synthesis.

        Runs Claude and GPT syntheses in parallel.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            discovery_output: Discovery findings from Stage 2.
            vertical_analyses: All vertical analyses from Stage 3.

        Returns:
            Tuple of (claude_synthesis, gpt_synthesis).
        """
        self.log_info(
            "Starting dual synthesis",
            ticker=run_state.ticker,
            vertical_count=len(vertical_analyses),
        )

        run_state.phase = Phase.SYNTHESIS

        # Build the shared prompt
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Format vertical analyses
        vertical_str = self._format_vertical_analyses(vertical_analyses)

        prompt = SYNTHESIS_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            company_context=company_context.to_prompt_string(max_tokens=10000),
            official_segments=", ".join(discovery_output.official_segments),
            cross_cutting_themes=", ".join(discovery_output.cross_cutting_themes),
            optionality_candidates=", ".join(discovery_output.optionality_candidates),
            vertical_analyses=vertical_str,
        )

        # Run both syntheses in parallel
        self.log_info("Running Claude and GPT syntheses in parallel", ticker=run_state.ticker)

        claude_task = self._run_claude_synthesis(prompt, company_context)
        gpt_task = self._run_gpt_synthesis(prompt, company_context)

        claude_synthesis, gpt_synthesis = await asyncio.gather(
            claude_task,
            gpt_task,
        )

        # Update run state
        run_state.synthesis_outputs = {
            "claude": {
                "investment_view": claude_synthesis.investment_view,
                "conviction": claude_synthesis.conviction,
                "confidence": claude_synthesis.overall_confidence,
            },
            "gpt": {
                "investment_view": gpt_synthesis.investment_view,
                "conviction": gpt_synthesis.conviction,
                "confidence": gpt_synthesis.overall_confidence,
            },
        }

        self.log_info(
            "Completed dual synthesis",
            ticker=run_state.ticker,
            claude_view=claude_synthesis.investment_view,
            gpt_view=gpt_synthesis.investment_view,
        )

        return claude_synthesis, gpt_synthesis

    def _format_vertical_analyses(
        self,
        analyses: list[VerticalAnalysis],
    ) -> str:
        """Format vertical analyses for the prompt."""
        sections = []
        for analysis in analyses:
            sections.append(f"""
### {analysis.vertical_name}

**Business Understanding:**
{analysis.business_understanding}

**Competitive Position:**
{analysis.competitive_position}

**Growth Drivers:**
{chr(10).join(f"- {d}" for d in analysis.growth_drivers)}

**Key Risks:**
{chr(10).join(f"- {r.name}: {r.description}" for r in analysis.key_risks)}

**Bull Case:**
{analysis.bull_case.thesis}
Key Assumptions: {", ".join(analysis.bull_case.key_assumptions)}

**Bear Case:**
{analysis.bear_case.thesis}
Key Assumptions: {", ".join(analysis.bear_case.key_assumptions)}

**Confidence:** {analysis.overall_confidence:.0%}
**Unanswered Questions:** {", ".join(analysis.unanswered_questions) if analysis.unanswered_questions else "None"}
""")
        return "\n".join(sections)

    async def _run_claude_synthesis(
        self,
        prompt: str,
        company_context: CompanyContext,
    ) -> SynthesisOutput:
        """Run Claude synthesis with extended thinking."""
        self.log_info("Starting Claude synthesis")

        anthropic = await self._get_anthropic_client()

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are a senior equity research analyst synthesizing investment insights."},
                {"role": "user", "content": prompt},
            ],
            model="claude-opus-4-5-20251101",
            max_tokens=16000,
        )

        response = await anthropic.complete_with_thinking(
            request,
            budget_tokens=15000,
        )

        # Record cost
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="anthropic",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="synthesis_claude",
            )

        self.log_info(
            "Completed Claude synthesis",
            thinking_tokens=response.metadata.get("thinking_tokens") if response.metadata else 0,
        )

        return self._parse_response(
            response.content,
            "claude",
            company_context.evidence_ids,
        )

    async def _run_gpt_synthesis(
        self,
        prompt: str,
        company_context: CompanyContext,
    ) -> SynthesisOutput:
        """Run GPT synthesis with high reasoning effort."""
        self.log_info("Starting GPT synthesis")

        openai = await self._get_openai_client()

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are a senior equity research analyst synthesizing investment insights."},
                {"role": "user", "content": prompt},
            ],
            model="gpt-5.2",
            max_tokens=8000,
        )

        response = await openai.complete_with_reasoning(
            request,
            reasoning_effort="xhigh",
        )

        # Record cost
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="openai",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="synthesis_gpt",
            )

        self.log_info(
            "Completed GPT synthesis",
            reasoning_tokens=response.metadata.get("reasoning_tokens") if response.metadata else 0,
        )

        return self._parse_response(
            response.content,
            "gpt",
            company_context.evidence_ids,
        )

    def _parse_response(
        self,
        content: str,
        synthesizer_model: str,
        base_evidence_ids: tuple[str, ...],
    ) -> SynthesisOutput:
        """Parse the LLM response into SynthesisOutput."""
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
            return SynthesisOutput(
                investment_view="HOLD",
                conviction="low",
                thesis_summary="Failed to parse synthesis response",
                scenarios={},
                key_debates=[],
                risk_factors=[],
                overall_confidence=0.0,
                evidence_gaps=["Parse error"],
                evidence_ids=list(base_evidence_ids),
                synthesizer_model=synthesizer_model,
            )

        # Parse scenarios
        scenarios = {}
        for name in ["bull", "base", "bear"]:
            s_data = data.get("scenarios", {}).get(name, {})
            scenarios[name] = Scenario(
                name=name,
                probability=s_data.get("probability", 0.33),
                narrative=s_data.get("narrative", ""),
                key_assumptions=s_data.get("key_assumptions", []),
            )

        # Parse key debates
        key_debates = []
        for d in data.get("key_debates", []):
            key_debates.append(
                KeyDebate(
                    topic=d.get("topic", ""),
                    bull_view=d.get("bull_view", ""),
                    bear_view=d.get("bear_view", ""),
                    our_view=d.get("our_view", ""),
                )
            )

        # Parse risk factors
        risk_factors = []
        for r in data.get("risk_factors", []):
            risk_factors.append(
                RiskFactor(
                    name=r.get("name", ""),
                    description=r.get("description", ""),
                    probability=r.get("probability", "medium"),
                    impact=r.get("impact", "medium"),
                    priced_in=r.get("priced_in", False),
                    mitigation=r.get("mitigation", ""),
                )
            )

        return SynthesisOutput(
            investment_view=data.get("investment_view", "HOLD"),
            conviction=data.get("conviction", "medium"),
            thesis_summary=data.get("thesis_summary", ""),
            scenarios=scenarios,
            key_debates=key_debates,
            risk_factors=risk_factors,
            overall_confidence=data.get("overall_confidence", 0.5),
            evidence_gaps=data.get("evidence_gaps", []),
            evidence_ids=list(base_evidence_ids),
            synthesizer_model=synthesizer_model,
        )

    async def close(self) -> None:
        """Close any open clients."""
        if self._anthropic_client:
            await self._anthropic_client.close()
            self._anthropic_client = None
        if self._openai_client:
            await self._openai_client.close()
            self._openai_client = None
