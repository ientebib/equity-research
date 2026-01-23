"""
Judge Agent (Stage 5) - Editorial Review with Feedback Loop.

The Judge reviews the synthesis report and identifies:
1. Quality assessment (thesis clarity, evidence usage, risk analysis)
2. Errors or contradictions with ground truth data
3. Gaps that need addressing
4. Specific revision instructions

Instead of writing the final report itself, the Judge sends feedback
to the Synthesizer, which revises its report. This preserves
the Synthesizer's chain of reasoning while incorporating improvements.

Flow:
1. Judge reviews the full synthesis report
2. Judge generates revision feedback
3. Feedback sent back to Synthesizer
4. Synthesizer produces revised final report

Model: Claude Opus 4.5 (extended thinking)
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
    VerifiedResearchPackage,
    VerificationStatus,
)


# Judge prompt template - Editorial Review with Feedback
JUDGE_PROMPT = """You are the Editorial Judge for an institutional equity research system.

## TODAY'S DATE: {date}

## YOUR ROLE

You have received an equity research report analyzing {company_name} ({ticker}).
Your job is NOT to write the final report yourself. Instead, you will:

1. Read the full report carefully
2. Assess the quality of thesis, evidence usage, and risk analysis
3. Identify any ERRORS or factual contradictions with ground truth data
4. Identify any GAPS that should be addressed
5. Generate SPECIFIC FEEDBACK for the Synthesizer to revise its report

The final output will be the SYNTHESIZER'S revised report, not yours.
You are an editor, not an author.

## SYNTHESIS REPORT

{synthesis_report}

## KEY FINANCIAL DATA (For Fact-Checking Claims)

Use this actual data to validate numerical claims in the report:

{key_metrics}

## VERIFIED FACTS (For Citation Checking)

These facts were verified against ground truth:

{verified_facts_summary}

## CRITICAL DATA GAPS

These data points were requested but not found:
{data_gaps}

## EVALUATION CRITERIA

### 1. Thesis Quality (0-10)
- Is the investment view (BUY/HOLD/SELL) clearly stated?
- Is conviction level appropriate given evidence?
- Is the thesis summary compelling and specific?

### 2. Evidence Usage (0-10)
- Are claims supported by specific evidence?
- Are sources properly cited?
- Are numerical claims accurate vs ground truth?

### 3. Risk Analysis (0-10)
- Are key risks identified?
- Are risks quantified where possible?
- Are mitigants discussed?

### 4. Report Structure (0-10)
- Is the report well-organized?
- Is the executive summary clear?
- Are sections appropriately detailed?

## OUTPUT FORMAT

Return a JSON object with this exact structure:
{{
  "quality_scores": {{
    "thesis_quality": 0,
    "evidence_usage": 0,
    "risk_analysis": 0,
    "report_structure": 0,
    "overall_score": 0.0
  }},
  "errors_to_fix": [
    {{
      "error_type": "factual|logical|citation|contradiction",
      "description": "What's wrong",
      "location": "Where in the report",
      "correction": "How to fix it"
    }}
  ],
  "gaps_to_address": [
    {{
      "gap_type": "missing_analysis|incomplete_section|data_gap",
      "description": "What's missing",
      "priority": "high|medium|low",
      "suggested_content": "What should be added"
    }}
  ],
  "revision_instructions": "Detailed instructions for the Synthesizer to revise the report. Be specific - quote sections that need changes and explain exactly what to modify."
}}

## IMPORTANT

1. **GROUND TRUTH WINS** - If the report contradicts the financial data provided above, that's an error.
2. **BE SPECIFIC** - Not "improve the risk section" but "add analysis of regulatory risk after current risk #3."
3. **QUOTE SECTIONS** - When referencing parts to change, quote them so the Synthesizer knows exactly where.
4. **PRESERVE GOOD PARTS** - Focus feedback on what needs improving, not rewriting good sections.
5. **CONSTRUCTIVE CRITICISM** - Provide actionable feedback, not just complaints.

Output ONLY valid JSON."""


class JudgeAgent(Agent):
    """Stage 5: Judge Agent (Editorial Review).

    Responsibilities:
    1. Reviewing synthesis report quality
    2. Checking factual accuracy against ground truth
    3. Identifying errors and gaps
    4. Generating specific revision feedback for Synthesizer

    Uses Claude Opus 4.5 with extended thinking for nuanced evaluation.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Judge.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)

    @property
    def name(self) -> str:
        return "judge"

    @property
    def role(self) -> str:
        return "Editorial review and feedback generation"

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        synthesis: SynthesisOutput,
        verified_package: VerifiedResearchPackage | None = None,
    ) -> EditorialFeedback:
        """Run editorial review of synthesis report.

        Args:
            run_state: Current run state.
            company_context: Company financial data (ground truth).
            synthesis: Synthesis report to review.
            verified_package: Optional verification results.

        Returns:
            EditorialFeedback with revision instructions.
        """
        run_state.phase = Phase.EDITORIAL_REVIEW
        ticker = run_state.ticker
        company_name = company_context.company_name

        self.log_info(
            "Starting editorial review",
            ticker=ticker,
            synthesis_view=synthesis.investment_view,
            synthesis_len=len(synthesis.full_report),
        )

        # Build the prompt
        key_metrics = self._build_key_metrics(company_context)
        verified_facts_summary = self._build_verified_facts_summary(verified_package)
        data_gaps = self._build_data_gaps(verified_package)

        prompt = JUDGE_PROMPT.format(
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            ticker=ticker,
            company_name=company_name,
            synthesis_report=synthesis.full_report,
            key_metrics=key_metrics,
            verified_facts_summary=verified_facts_summary,
            data_gaps=data_gaps,
        )

        # Call Opus with extended thinking
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="claude-opus-4-5-20251101",
            max_tokens=8000,
        )

        response = await self.anthropic_client.complete_with_extended_thinking(
            request,
            budget_tokens=15000,
        )

        # Record budget usage
        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="anthropic",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="editorial_review",
            )

        # Parse the response
        feedback = self._parse_response(
            response.content,
            ticker,
            synthesis,
        )

        # Store in WorkspaceStore
        if self.workspace_store:
            self.workspace_store.put_artifact(
                artifact_type="editorial_feedback",
                producer=self.name,
                json_obj=feedback.to_dict(),
                summary=f"Editorial review: score={feedback.claude_score:.1f}, errors={len(feedback.errors_to_fix)}, gaps={len(feedback.gaps_to_address)}",
                evidence_ids=[],
            )

        self.log_info(
            "Editorial review complete",
            ticker=ticker,
            overall_score=feedback.claude_score,
            errors_count=len(feedback.errors_to_fix),
            gaps_count=len(feedback.gaps_to_address),
        )

        return feedback

    def _build_key_metrics(self, company_context: CompanyContext) -> str:
        """Build key financial metrics summary for fact-checking."""
        lines = []

        # Latest quarterly income
        income_stmt = company_context.income_statement_quarterly
        if income_stmt:
            latest = income_stmt[0]
            lines.append(f"Latest Quarter Revenue: ${latest.get('revenue', 0):,.0f}")
            lines.append(f"Operating Income: ${latest.get('operatingIncome', 0):,.0f}")
            lines.append(f"Net Income: ${latest.get('netIncome', 0):,.0f}")

        # YoY growth if available
        if income_stmt and len(income_stmt) >= 5:
            current_rev = income_stmt[0].get("revenue", 0)
            year_ago_rev = income_stmt[4].get("revenue", 0)
            if year_ago_rev > 0:
                yoy_growth = ((current_rev / year_ago_rev) - 1) * 100
                lines.append(f"YoY Revenue Growth: {yoy_growth:.1f}%")

        # Balance sheet
        balance_sheet = company_context.balance_sheet_quarterly
        if balance_sheet:
            latest = balance_sheet[0]
            lines.append(f"Total Assets: ${latest.get('totalAssets', 0):,.0f}")
            lines.append(f"Total Debt: ${latest.get('totalDebt', 0):,.0f}")
            lines.append(f"Cash: ${latest.get('cashAndCashEquivalents', 0):,.0f}")

        return "\n".join(lines) if lines else "(No financial data available)"

    def _build_verified_facts_summary(self, package: VerifiedResearchPackage | None) -> str:
        """Build summary of verified facts."""
        if not package:
            return "(No verification data)"

        lines = [
            f"Total facts verified: {package.verified_count}/{package.total_facts}",
            f"Contradicted facts: {package.contradicted_count}",
            f"Unverifiable facts: {package.unverifiable_count}",
        ]

        # List critical issues
        if package.critical_issues:
            lines.append("\nCritical issues found:")
            for issue in package.critical_issues[:5]:
                lines.append(f"- {issue}")

        return "\n".join(lines)

    def _build_data_gaps(self, package: VerifiedResearchPackage | None) -> str:
        """Build list of data gaps."""
        if not package:
            return "(No data gap information)"

        # Collect gaps from all verification results
        gaps = []
        for vr in package.verification_results:
            for fact in vr.facts:
                if fact.verification_status == VerificationStatus.UNVERIFIABLE:
                    gaps.append(f"- {fact.original_statement[:100]}...")

        return "\n".join(gaps[:10]) if gaps else "(No data gaps identified)"

    def _parse_response(
        self,
        content: str,
        ticker: str,
        synthesis: SynthesisOutput,
    ) -> EditorialFeedback:
        """Parse Judge response into EditorialFeedback."""
        try:
            # Extract JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end]
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end]

            data = json.loads(content)

            # Parse quality scores
            quality = data.get("quality_scores", {})
            overall_score = quality.get("overall_score", 0.5)

            # Parse errors
            errors = []
            for err in data.get("errors_to_fix", []):
                errors.append(ErrorToFix(
                    error_type=err.get("error_type", "unknown"),
                    description=err.get("description", ""),
                    location=err.get("location", ""),
                    correction=err.get("correction", ""),
                ))

            # Parse gaps
            gaps = []
            for gap in data.get("gaps_to_address", []):
                gaps.append(GapToAddress(
                    gap_type=gap.get("gap_type", "unknown"),
                    description=gap.get("description", ""),
                    priority=gap.get("priority", "medium"),
                    suggested_content=gap.get("suggested_content", ""),
                ))

            return EditorialFeedback(
                preferred_synthesis="claude",  # Always Claude in Anthropic-only mode
                claude_score=overall_score,
                gpt_score=0.0,  # Not used in Anthropic-only mode
                incorporate_from_other=[],  # Not applicable
                errors_to_fix=errors,
                gaps_to_address=gaps,
                revision_instructions=data.get("revision_instructions", ""),
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as e:
            self.log_error("Failed to parse Judge response", error=str(e))
            return EditorialFeedback(
                preferred_synthesis="claude",
                claude_score=0.5,
                gpt_score=0.0,
                incorporate_from_other=[],
                errors_to_fix=[],
                gaps_to_address=[],
                revision_instructions="Unable to parse editorial feedback. Please review the synthesis manually.",
                timestamp=datetime.now(timezone.utc),
            )
