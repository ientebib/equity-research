"""
Judge Agent (Stage 5).

Compares Claude and GPT syntheses, identifies inconsistencies,
and produces the final unified equity research report.

Model: Claude Opus 4.5 (extended thinking, budget_tokens: 20000)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.anthropic_client import AnthropicClient
from er.llm.base import LLMRequest
from er.types import (
    CompanyContext,
    Inconsistency,
    JudgeVerdict,
    Phase,
    RunState,
    SynthesisOutput,
)


# Judge prompt template
JUDGE_PROMPT = """You are the Final Judge for an institutional equity research system.

TODAY'S DATE: {date}
COMPANY: {ticker} ({company_name})

## Your Role
You have received TWO independent synthesis reports from different AI models:
1. Claude Opus 4.5 (extended thinking)
2. GPT-5.2 (high reasoning effort)

Your job is to:
1. Compare both syntheses
2. Identify agreements and inconsistencies
3. Verify claims against the ground truth CompanyContext
4. Produce the FINAL unified investment thesis

## CompanyContext (Ground Truth)
{company_context}

## Claude Synthesis
Investment View: {claude_view} (Conviction: {claude_conviction})
Thesis: {claude_thesis}

Scenarios:
{claude_scenarios}

Key Debates:
{claude_debates}

Risk Factors:
{claude_risks}

Overall Confidence: {claude_confidence:.0%}
Evidence Gaps: {claude_gaps}

## GPT Synthesis
Investment View: {gpt_view} (Conviction: {gpt_conviction})
Thesis: {gpt_thesis}

Scenarios:
{gpt_scenarios}

Key Debates:
{gpt_debates}

Risk Factors:
{gpt_risks}

Overall Confidence: {gpt_confidence:.0%}
Evidence Gaps: {gpt_gaps}

## Your Analysis Tasks

### 1. Compare Syntheses
- Where do they AGREE? List specific points of agreement.
- Where do they DISAGREE? For each disagreement:
  - What does Claude say?
  - What does GPT say?
  - Who is right based on the evidence?

### 2. Fact Check Against CompanyContext
- Are there any claims that contradict the financial data?
- Are there any unsupported claims?
- Note: Both models could be wrong on the same point.

### 3. Resolve Conflicts
For each inconsistency:
- Evaluate the evidence for each position
- Determine which view is better supported
- If neither is well-supported, flag as uncertainty

### 4. Produce Final Verdict
- Final investment view with conviction
- Unified thesis statement
- Key risks, catalysts, and uncertainties

## Output Requirements

You MUST output valid JSON with this exact structure:

```json
{{
  "agreements": ["Point of agreement 1", "Point of agreement 2"],
  "inconsistencies": [
    {{
      "topic": "The topic of disagreement",
      "claude_view": "What Claude said",
      "gpt_view": "What GPT said",
      "resolution": "Your resolution with reasoning",
      "winner": "claude|gpt|neither"
    }}
  ],
  "preferred_synthesis": "claude|gpt|merged",
  "preference_reasoning": "Why you prefer this synthesis",
  "final_investment_view": "BUY|HOLD|SELL",
  "final_conviction": "high|medium|low",
  "final_thesis": "Your unified thesis statement (3-4 sentences)",
  "final_confidence": 0.7,
  "key_risks": ["Top risk 1", "Top risk 2", "Top risk 3"],
  "key_catalysts": ["Catalyst 1", "Catalyst 2"],
  "key_uncertainties": ["Uncertainty 1", "Uncertainty 2"]
}}
```

## Hard Rules

1. DO NOT blindly average or merge - think critically about each conflict
2. If both syntheses agree on something that contradicts CompanyContext, call it out
3. Final confidence should reflect unresolved uncertainties
4. Key risks should be specific and actionable
5. If you can't confidently resolve a conflict, it becomes a "key_uncertainty"
"""


class JudgeAgent(Agent):
    """Stage 5: Final Judge.

    Responsible for:
    1. Comparing Claude and GPT syntheses
    2. Identifying inconsistencies and resolving conflicts
    3. Fact-checking against CompanyContext
    4. Producing the final unified investment thesis

    Uses Claude Opus 4.5 with extended thinking (budget_tokens: 20000).
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Judge.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._anthropic_client: AnthropicClient | None = None

    @property
    def name(self) -> str:
        return "judge"

    @property
    def role(self) -> str:
        return "Compare syntheses and produce final unified verdict"

    async def _get_anthropic_client(self) -> AnthropicClient:
        """Get or create Anthropic client."""
        if self._anthropic_client is None:
            self._anthropic_client = AnthropicClient(
                api_key=self.settings.ANTHROPIC_API_KEY,
            )
        return self._anthropic_client

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        claude_synthesis: SynthesisOutput,
        gpt_synthesis: SynthesisOutput,
        **kwargs: Any,
    ) -> JudgeVerdict:
        """Execute Stage 5: Final Judgment.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            claude_synthesis: Synthesis from Claude (Stage 4).
            gpt_synthesis: Synthesis from GPT (Stage 4).

        Returns:
            JudgeVerdict with final unified thesis.
        """
        self.log_info(
            "Starting final judgment",
            ticker=run_state.ticker,
            claude_view=claude_synthesis.investment_view,
            gpt_view=gpt_synthesis.investment_view,
        )

        run_state.phase = Phase.JUDGE

        # Build the prompt
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        prompt = JUDGE_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            company_context=company_context.to_prompt_string(max_tokens=8000),
            # Claude synthesis
            claude_view=claude_synthesis.investment_view,
            claude_conviction=claude_synthesis.conviction,
            claude_thesis=claude_synthesis.thesis_summary,
            claude_scenarios=self._format_scenarios(claude_synthesis.scenarios),
            claude_debates=self._format_debates(claude_synthesis.key_debates),
            claude_risks=self._format_risk_factors(claude_synthesis.risk_factors),
            claude_confidence=claude_synthesis.overall_confidence,
            claude_gaps=", ".join(claude_synthesis.evidence_gaps),
            # GPT synthesis
            gpt_view=gpt_synthesis.investment_view,
            gpt_conviction=gpt_synthesis.conviction,
            gpt_thesis=gpt_synthesis.thesis_summary,
            gpt_scenarios=self._format_scenarios(gpt_synthesis.scenarios),
            gpt_debates=self._format_debates(gpt_synthesis.key_debates),
            gpt_risks=self._format_risk_factors(gpt_synthesis.risk_factors),
            gpt_confidence=gpt_synthesis.overall_confidence,
            gpt_gaps=", ".join(gpt_synthesis.evidence_gaps),
        )

        # Get Anthropic client
        anthropic = await self._get_anthropic_client()

        # Run judgment with extended thinking (max budget)
        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are a senior equity research analyst acting as the final judge between two independent analyses."},
                {"role": "user", "content": prompt},
            ],
            model="claude-opus-4-5-20251101",
            max_tokens=24000,
        )

        response = await anthropic.complete_with_thinking(
            request,
            budget_tokens=20000,
        )

        # Record cost
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="anthropic",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="judge",
            )

        # Parse the response
        verdict = self._parse_response(
            response.content,
            company_context.evidence_ids,
        )

        # Update run state
        run_state.final_verdict = {
            "investment_view": verdict.final_investment_view,
            "conviction": verdict.final_conviction,
            "confidence": verdict.final_confidence,
            "preferred_synthesis": verdict.preferred_synthesis,
            "inconsistency_count": len(verdict.inconsistencies),
        }

        self.log_info(
            "Completed final judgment",
            ticker=run_state.ticker,
            final_view=verdict.final_investment_view,
            final_conviction=verdict.final_conviction,
            final_confidence=verdict.final_confidence,
            preferred=verdict.preferred_synthesis,
            inconsistencies=len(verdict.inconsistencies),
            thinking_tokens=response.metadata.get("thinking_tokens") if response.metadata else 0,
        )

        return verdict

    def _format_scenarios(self, scenarios: dict[str, Any]) -> str:
        """Format scenarios for the prompt."""
        lines = []
        for name in ["bull", "base", "bear"]:
            if name in scenarios:
                s = scenarios[name]
                lines.append(f"- {name.title()} ({s.probability:.0%}): {s.narrative}")
        return "\n".join(lines) if lines else "No scenarios provided"

    def _format_debates(self, debates: list[Any]) -> str:
        """Format key debates for the prompt."""
        if not debates:
            return "No debates identified"
        lines = []
        for d in debates:
            lines.append(f"- {d.topic}: Bull says '{d.bull_view[:100]}...' vs Bear says '{d.bear_view[:100]}...'")
        return "\n".join(lines)

    def _format_risk_factors(self, risks: list[Any]) -> str:
        """Format risk factors for the prompt."""
        if not risks:
            return "No risks identified"
        lines = []
        for r in risks:
            lines.append(f"- {r.name} ({r.probability} prob, {r.impact} impact): {r.description[:100]}...")
        return "\n".join(lines)

    def _parse_response(
        self,
        content: str,
        base_evidence_ids: tuple[str, ...],
    ) -> JudgeVerdict:
        """Parse the LLM response into JudgeVerdict."""
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
            return JudgeVerdict(
                agreements=[],
                inconsistencies=[],
                preferred_synthesis="neither",
                preference_reasoning="Failed to parse judge response",
                final_investment_view="HOLD",
                final_conviction="low",
                final_thesis="Failed to parse judge response",
                final_confidence=0.0,
                key_risks=["Parse error"],
                key_catalysts=[],
                key_uncertainties=["Failed to complete judgment"],
                evidence_ids=list(base_evidence_ids),
            )

        # Parse inconsistencies
        inconsistencies = []
        for inc in data.get("inconsistencies", []):
            inconsistencies.append(
                Inconsistency(
                    topic=inc.get("topic", ""),
                    claude_view=inc.get("claude_view", ""),
                    gpt_view=inc.get("gpt_view", ""),
                    resolution=inc.get("resolution", ""),
                    winner=inc.get("winner", "neither"),
                )
            )

        return JudgeVerdict(
            agreements=data.get("agreements", []),
            inconsistencies=inconsistencies,
            preferred_synthesis=data.get("preferred_synthesis", "merged"),
            preference_reasoning=data.get("preference_reasoning", ""),
            final_investment_view=data.get("final_investment_view", "HOLD"),
            final_conviction=data.get("final_conviction", "medium"),
            final_thesis=data.get("final_thesis", ""),
            final_confidence=data.get("final_confidence", 0.5),
            key_risks=data.get("key_risks", []),
            key_catalysts=data.get("key_catalysts", []),
            key_uncertainties=data.get("key_uncertainties", []),
            evidence_ids=list(base_evidence_ids),
        )

    async def close(self) -> None:
        """Close any open clients."""
        if self._anthropic_client:
            await self._anthropic_client.close()
            self._anthropic_client = None
