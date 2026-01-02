"""
Judge Agent (Stage 5) - Editorial Review with Feedback Loop.

The Judge compares both synthesis reports (Claude and GPT), identifies:
1. Which synthesis is stronger
2. What's better in the other synthesis that should be incorporated
3. What errors or gaps need fixing

Instead of writing the final report itself, the Judge sends feedback
to the chosen Synthesizer, which revises its report. This preserves
the Synthesizer's chain of reasoning while incorporating the best
of both worlds.

Flow:
1. Judge reviews both full reports
2. Judge picks preferred synthesis + generates revision feedback
3. Feedback sent back to Synthesizer
4. Synthesizer produces revised final report

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
    EditorialFeedback,
    ErrorToFix,
    GapToAddress,
    InsightToIncorporate,
    Phase,
    RunState,
    SynthesisOutput,
)


# Judge prompt template - Editorial Review with Feedback
JUDGE_PROMPT = """You are the Editorial Judge for an institutional equity research system.

## TODAY'S DATE: {date}

## YOUR ROLE

You have received TWO full equity research reports (from Claude and GPT) analyzing the same company.
Your job is NOT to write the final report yourself. Instead, you will:

1. Read both full reports carefully
2. Decide which report is STRONGER overall
3. Identify what the OTHER report does BETTER that should be incorporated
4. Identify any ERRORS or GAPS in the chosen report
5. Generate SPECIFIC FEEDBACK for the chosen Synthesizer to revise its report

The final output will be the SYNTHESIZER'S revised report, not yours.
You are an editor, not an author.

## CLAUDE SYNTHESIS REPORT

{claude_synthesis}

## GPT SYNTHESIS REPORT

{gpt_synthesis}

## YOUR ANALYSIS PROCESS

### Step 1: Overall Assessment
Read both reports in full. Consider:
- Depth of analysis
- Quality of reasoning
- Use of evidence
- Clarity of investment thesis
- Completeness of risk assessment
- Internal consistency

### Step 2: Pick the Stronger Report
Which report is better overall? This will be the BASE for the final report.
The chosen Synthesizer will revise it based on your feedback.

### Step 3: Identify What the Other Report Does Better
The "losing" report may still have strengths worth incorporating:
- Better analysis of a specific segment?
- Identified a risk the other missed?
- Clearer explanation of something?
- More specific metrics or evidence?

### Step 4: Identify Errors and Gaps
In the CHOSEN report, what needs fixing?
- Factual errors
- Logical inconsistencies
- Missing considerations
- Overconfident claims
- Unclear reasoning

### Step 5: Generate Revision Feedback
Write specific, actionable feedback for the Synthesizer.
This is your main output - make it detailed and useful.

## OUTPUT FORMAT

```json
{{
  "preferred_synthesis": "claude|gpt",
  "preference_reasoning": "2-3 sentences explaining why this report is stronger overall",

  "overall_quality_assessment": {{
    "claude_score": 0.0,
    "gpt_score": 0.0,
    "key_differentiators": ["What made the winner better"]
  }},

  "incorporate_from_other": [
    {{
      "section": "Which section of the other report has something better",
      "what_to_incorporate": "QUOTE the specific passage or insight verbatim. Include the actual text so the Synthesizer can incorporate it directly without losing nuance.",
      "why": "Why this improves the report",
      "how_to_integrate": "Specific suggestion for where and how to add this"
    }}
  ],

  "errors_to_fix": [
    {{
      "location": "Where in the report (section name or quote)",
      "error": "What's wrong",
      "correction": "What it should say or how to fix it"
    }}
  ],

  "gaps_to_address": [
    {{
      "missing": "What's missing from the report",
      "why_important": "Why this matters for the investment thesis",
      "suggestion": "How to address it"
    }}
  ],

  "revision_instructions": "
    Detailed instructions for the Synthesizer to revise its report.
    Be specific:
    - 'In the Executive Summary, add...'
    - 'The Cloud segment analysis should incorporate...'
    - 'Strengthen the bear case by...'
    - 'The risk section is missing...'

    This should be 3-5 paragraphs of actionable feedback.
  ",

  "confidence_adjustment": {{
    "current_confidence": 0.0,
    "recommended_confidence": 0.0,
    "reasoning": "Why adjust confidence (or why keep it)"
  }},

  "meta": {{
    "analysis_quality": "high|medium|low",
    "key_strengths": ["What both reports did well"],
    "key_weaknesses": ["What both reports could improve"]
  }}
}}
```

## HARD RULES

1. **YOU ARE AN EDITOR, NOT AN AUTHOR** - Your job is to guide the Synthesizer, not write the final report yourself.

2. **QUOTE, DON'T SUMMARIZE** - When extracting insights from the other report, QUOTE the actual text verbatim.
   The Synthesizer needs the exact language to incorporate the insight without losing nuance.
   BAD: "GPT had a good point about regulatory risk"
   GOOD: "GPT wrote: 'The DOJ antitrust case represents an underappreciated tail risk. If the court mandates structural remedies, the advertising business could face...' - incorporate this in your Risk Assessment section."

3. **BE SPECIFIC** - Not "improve the risk section" but "add the regulatory risk analysis from GPT's report (quoted above) after your current risk #3."

4. **TRANSFER BRILLIANCE** - Both reports may have unique brilliant insights. Your job is to ensure the winner's report includes the best of BOTH. Don't let good insights die with the losing report.

5. **PRIORITIZE** - Focus on what matters most. 3-5 key improvements, not 50 minor edits.

6. **PRESERVE THE THESIS** - Don't ask the Synthesizer to flip their investment view unless there's a critical error. The Synthesizer developed their thesis through reasoning - respect that.

7. **ACKNOWLEDGE UNCERTAINTY** - If evidence is thin, recommend lowering confidence rather than fabricating certainty.

8. **THINK ADVERSARIALLY** - What would a skeptic challenge? Ensure the final report addresses likely pushback.

Output ONLY the JSON. No preamble."""


# Revision prompt for the Synthesizer to incorporate Judge feedback
REVISION_PROMPT = """You are revising your equity research report based on editorial feedback.

## TODAY'S DATE: {date}
## COMPANY: {ticker}

## YOUR ORIGINAL REPORT

{original_report}

## EDITORIAL FEEDBACK FROM JUDGE

The Judge reviewed both your report and an alternative synthesis. They have selected YOUR report
as the stronger one, but have provided feedback to make it even better.

### What to incorporate from the other report:
{incorporate_from_other}

### Errors to fix:
{errors_to_fix}

### Gaps to address:
{gaps_to_address}

### Detailed revision instructions:
{revision_instructions}

### Confidence adjustment:
{confidence_adjustment}

## YOUR TASK

Revise your report incorporating the Judge's feedback. You should:

1. **PRESERVE your core thesis and reasoning** - The Judge selected your report because your analysis was strong. Don't abandon your reasoning.

2. **INCORPORATE the specific improvements** - Add the insights, fix the errors, address the gaps.

3. **MAINTAIN your voice and structure** - This is still YOUR report. Don't rewrite it from scratch.

4. **UPDATE the JSON metadata** at the end if the feedback affects investment view, conviction, or confidence.

## OUTPUT

Output your REVISED full report in the same format as before:
- Full prose research report (main content)
- JSON metadata block at the end

The report should be improved but recognizably yours."""


class JudgeAgent(Agent):
    """Stage 5: Editorial Judge with Feedback Loop.

    Responsible for:
    1. Comparing Claude and GPT synthesis REPORTS (full prose)
    2. Selecting the stronger report
    3. Identifying improvements from the other report to incorporate
    4. Generating specific revision feedback
    5. Sending feedback back to the chosen Synthesizer

    The final output is the SYNTHESIZER'S revised report, not the Judge's.
    This preserves the chain of reasoning while getting best of both worlds.

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
        return "Editorial review of syntheses with feedback for revision"

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
    ) -> EditorialFeedback:
        """Execute Stage 5: Editorial Review.

        Compares both synthesis reports and generates editorial feedback
        for the winning Synthesizer to revise their report.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            claude_synthesis: Synthesis from Claude (Stage 4) with full_report.
            gpt_synthesis: Synthesis from GPT (Stage 4) with full_report.

        Returns:
            EditorialFeedback with revision instructions.
        """
        self.log_info(
            "Starting editorial review",
            ticker=run_state.ticker,
            claude_view=claude_synthesis.investment_view,
            claude_report_len=len(claude_synthesis.full_report),
            gpt_view=gpt_synthesis.investment_view,
            gpt_report_len=len(gpt_synthesis.full_report),
        )

        run_state.phase = Phase.DELIBERATE

        # Build the prompt with FULL REPORTS (not JSON summaries)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        prompt = JUDGE_PROMPT.format(
            date=today,
            claude_synthesis=claude_synthesis.full_report,
            gpt_synthesis=gpt_synthesis.full_report,
        )

        # Get Anthropic client
        anthropic = await self._get_anthropic_client()

        # Run editorial review with extended thinking
        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior equity research editor reviewing two synthesis reports. Your job is to pick the stronger one and provide specific feedback for revision.",
                },
                {"role": "user", "content": prompt},
            ],
            model="claude-opus-4-5-20251101",
            max_tokens=16000,  # Feedback doesn't need to be as long as the reports
        )

        self.log_info("Calling Claude for editorial review...")

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
                phase="judge_editorial",
            )

        self.log_info(
            "Received editorial response",
            response_len=len(response.content),
            thinking_tokens=response.metadata.get("thinking_tokens") if response.metadata else 0,
        )

        # Parse the editorial feedback
        feedback = self._parse_editorial_feedback(response.content)

        # Update run state
        run_state.final_verdict = {
            "preferred_synthesis": feedback.preferred_synthesis,
            "claude_score": feedback.claude_score,
            "gpt_score": feedback.gpt_score,
            "insights_to_incorporate": len(feedback.incorporate_from_other),
            "errors_to_fix": len(feedback.errors_to_fix),
            "gaps_to_address": len(feedback.gaps_to_address),
        }

        self.log_info(
            "Completed editorial review",
            ticker=run_state.ticker,
            preferred=feedback.preferred_synthesis,
            claude_score=feedback.claude_score,
            gpt_score=feedback.gpt_score,
            insights_count=len(feedback.incorporate_from_other),
            errors_count=len(feedback.errors_to_fix),
        )

        return feedback

    def _parse_editorial_feedback(self, content: str) -> EditorialFeedback:
        """Parse the LLM response into EditorialFeedback."""
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
            self.log_warning(f"Failed to parse editorial feedback JSON: {e}")
            # Return minimal feedback
            return EditorialFeedback(
                preferred_synthesis="claude",
                preference_reasoning="Failed to parse response - defaulting to Claude",
                claude_score=0.5,
                gpt_score=0.5,
                key_differentiators=["Parse error"],
                incorporate_from_other=[],
                errors_to_fix=[],
                gaps_to_address=[],
                revision_instructions="Unable to parse editorial feedback. Review reports manually.",
                current_confidence=0.5,
                recommended_confidence=0.5,
                confidence_reasoning="Parse error",
                analysis_quality="low",
                key_strengths=[],
                key_weaknesses=["Failed to complete editorial review"],
            )

        # Parse quality assessment
        quality = data.get("overall_quality_assessment", {})

        # Parse insights to incorporate
        incorporate = []
        for item in data.get("incorporate_from_other", []):
            incorporate.append(
                InsightToIncorporate(
                    section=item.get("section", ""),
                    what_to_incorporate=item.get("what_to_incorporate", ""),
                    why=item.get("why", ""),
                    how_to_integrate=item.get("how_to_integrate", ""),
                )
            )

        # Parse errors to fix
        errors = []
        for item in data.get("errors_to_fix", []):
            errors.append(
                ErrorToFix(
                    location=item.get("location", ""),
                    error=item.get("error", ""),
                    correction=item.get("correction", ""),
                )
            )

        # Parse gaps to address
        gaps = []
        for item in data.get("gaps_to_address", []):
            gaps.append(
                GapToAddress(
                    missing=item.get("missing", ""),
                    why_important=item.get("why_important", ""),
                    suggestion=item.get("suggestion", ""),
                )
            )

        # Parse confidence adjustment
        conf = data.get("confidence_adjustment", {})

        # Parse meta
        meta = data.get("meta", {})

        return EditorialFeedback(
            preferred_synthesis=data.get("preferred_synthesis", "claude"),
            preference_reasoning=data.get("preference_reasoning", ""),
            claude_score=quality.get("claude_score", 0.5),
            gpt_score=quality.get("gpt_score", 0.5),
            key_differentiators=quality.get("key_differentiators", []),
            incorporate_from_other=incorporate,
            errors_to_fix=errors,
            gaps_to_address=gaps,
            revision_instructions=data.get("revision_instructions", ""),
            current_confidence=conf.get("current_confidence", 0.5),
            recommended_confidence=conf.get("recommended_confidence", 0.5),
            confidence_reasoning=conf.get("reasoning", ""),
            analysis_quality=meta.get("analysis_quality", "medium"),
            key_strengths=meta.get("key_strengths", []),
            key_weaknesses=meta.get("key_weaknesses", []),
        )

    async def close(self) -> None:
        """Close any open clients."""
        if self._anthropic_client:
            await self._anthropic_client.close()
            self._anthropic_client = None
