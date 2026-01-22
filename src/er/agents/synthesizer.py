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
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.anthropic_client import AnthropicClient
from er.llm.base import LLMRequest
from er.llm.openai_client import OpenAIClient
from er.types import (
    CompanyContext,
    CrossVerticalMap,
    DiscoveryOutput,
    EditorialFeedback,
    Fact,
    Phase,
    RunState,
    SynthesisOutput,
    VerifiedFact,
    VerifiedResearchPackage,
    VerificationStatus,
    VerticalAnalysis,
)


# Synthesis prompt template
SYNTHESIS_PROMPT = """You are a senior equity research synthesizer producing a comprehensive investment research report.

TODAY'S DATE: {date}
COMPANY: {ticker} ({company_name})

## YOUR INPUT: Deep Research Analyses

You have received detailed analyses from specialist Deep Research analysts who each focused on specific verticals/segments of the business. Each analyst had access to:
- Full company financials (income statement, balance sheet, cash flow)
- Segment revenue breakdowns
- Recent news and developments
- Web search for competitive intelligence

Your job is to SYNTHESIZE their work into a unified, comprehensive research report. Do NOT summarize or compress - PRESERVE the nuance and detail from their analyses while adding cross-vertical insights.

## Deep Research Analyst Reports

{vertical_analyses}

## YOUR TASK: Full Investment Research Report

Write a comprehensive equity research report (~15,000-20,000 words). This is the final deliverable for portfolio managers.

### Required Sections:

---

# {ticker} EQUITY RESEARCH REPORT
*Generated: {date}*

## EXECUTIVE SUMMARY
- Investment View: BUY / HOLD / SELL
- Conviction: High / Medium / Low
- 1-paragraph thesis (what's the core investment case?)

## FACT LEDGER (CITED)
List 25-50 key factual claims with evidence IDs. Format exactly:
- F1: fact statement [ev_xxx]
- F2: fact statement [ev_xxx]

Rules:
- Facts only (no opinions or predictions)
- Every line must include at least one evidence ID in brackets
- Use evidence IDs provided in the inputs; do not invent new ones

## INFERENCE MAP (FACT-BASED)
List 10-20 key inferences derived from the Fact Ledger. Format exactly:
- I1: inference statement (based on F1, F2, F7)
- I2: inference statement (based on F3, F9)

Rules:
- Inferences should NOT include evidence IDs
- Each inference must reference one or more Fact IDs

## COMPANY OVERVIEW
Synthesize what this company does across all verticals. How do the pieces fit together? What's the corporate strategy?

## SEGMENT ANALYSIS

For EACH vertical from the Deep Research reports:
- Preserve the key insights (don't compress)
- Add cross-references to other segments where relevant
- Highlight any conflicts or tensions between segments

### [Segment 1 Name]
[Full analysis preserving Deep Research insights]

### [Segment 2 Name]
[Full analysis preserving Deep Research insights]

[Continue for all segments...]

## CROSS-VERTICAL DYNAMICS
This is YOUR unique contribution - insights the individual analysts couldn't see:
- How do segments interact? (e.g., cannibalization, synergies, shared costs)
- Internal tensions (e.g., competing for same resources, conflicting strategies)
- Portfolio effects (e.g., diversification benefits, concentration risks)

## COMPETITIVE POSITION
Synthesize competitive insights across all verticals:
- Overall market position
- Key competitors by segment
- Moat assessment (strengthening or weakening?)

## INVESTMENT THESIS

### Bull Case (probability: X%)
- Key assumptions
- What has to go right
- Catalysts to watch
- Proof points that would confirm

### Base Case (probability: X%)
- Key assumptions
- Expected trajectory
- Key metrics to monitor

### Bear Case (probability: X%)
- Key assumptions
- What has to go wrong
- Warning signs to watch
- What would trigger downgrade

## KEY DEBATES & UNCERTAINTIES
Where the analyses conflict or highlight uncertainty:
For each debate:
- **The Question**: What's being debated?
- **Bull View**: The optimistic interpretation
- **Bear View**: The pessimistic interpretation
- **Our View**: Your synthesized assessment and why

## RISK ASSESSMENT
Top risks ranked by (probability × impact):
For each risk:
- Description
- Probability: High/Medium/Low
- Impact: High/Medium/Low
- Priced In?: Yes/No/Partially
- Mitigants
- Trigger events to watch

## UNANSWERED QUESTIONS
What couldn't the analysts determine? What data gaps remain?

## CONCLUSION
Final investment view with confidence level and key monitoring points.

---

## OUTPUT FORMAT

Write the full report in markdown prose FIRST (this is the main deliverable).

THEN, at the very end, include a JSON block with structured metadata:

```json
{{
  "investment_view": "BUY|HOLD|SELL",
  "conviction": "high|medium|low",
  "thesis_summary": "1-2 sentence summary",
  "scenarios": {{
    "bull": {{"probability": 0.XX, "headline": "..."}},
    "base": {{"probability": 0.XX, "headline": "..."}},
    "bear": {{"probability": 0.XX, "headline": "..."}}
  }},
  "top_risks": ["risk1", "risk2", "risk3"],
  "key_debates": ["debate1", "debate2"],
  "overall_confidence": 0.X,
  "evidence_gaps": ["gap1", "gap2"]
}}
```

## VERIFIED FACTS (pre-verified against ground truth)

{verified_facts_section}

## CROSS-VERTICAL MAP (dependencies and shared risks)

{cross_vertical_section}

## HARD RULES

1. **PRESERVE NUANCE** - Do not compress the Deep Research analyses. Your report should be 15-20K tokens, not 3K.
2. **CROSS-REFERENCE** - Your unique value is seeing connections between verticals. Add these insights.
3. **NO NEW RESEARCH** - Synthesize what the analysts provided. Don't invent new facts.
4. **CITE EVIDENCE IDs** - When making a factual claim, cite the evidence ID in brackets: [ev_xxxx]. Every major claim needs a citation.
5. **SCENARIOS SUM TO 1.0** - Bull + Base + Bear probabilities must total ~100%.
6. **NO DCF** - This is qualitative analysis only for V1.
7. **BE SPECIFIC** - Not "growth could slow" but "if Cloud growth drops below 20% YoY".
8. **USE VERIFIED FACTS** - Prioritize facts marked as VERIFIED. Note facts marked CONTRADICTED.
9. **ACKNOWLEDGE UNCERTAINTY** - If a claim is UNVERIFIABLE, say so in the report.
10. **FACT LEDGER REQUIRED** - Every factual claim must appear in the Fact Ledger with evidence IDs.
11. **INFERENCES MUST TRACE TO FACTS** - Use Fact IDs (F1, F2, ...) when stating inferences.
12. **CONCLUSIONS DON’T NEED CITATIONS** - Investment view should cite inference IDs, not evidence IDs.
"""


# Revision prompt for incorporating Judge feedback
REVISION_PROMPT = """You are revising your equity research report based on editorial feedback from a senior editor.

## TODAY'S DATE: {date}
## COMPANY: {ticker}

## YOUR ORIGINAL REPORT

{original_report}

## EDITORIAL FEEDBACK FROM SENIOR EDITOR

The editor reviewed both your report and an alternative synthesis. They selected YOUR report as the stronger one, but have provided feedback to make it even better.

### What to incorporate from the other report:
{incorporate_from_other}

### Errors to fix:
{errors_to_fix}

### Gaps to address:
{gaps_to_address}

### Detailed revision instructions:
{revision_instructions}

### Confidence adjustment:
Current confidence: {current_confidence}
Recommended confidence: {recommended_confidence}
Reasoning: {confidence_reasoning}

## YOUR TASK

Revise your report incorporating the editor's feedback. You should:

1. **PRESERVE your core thesis and reasoning** - The editor selected your report because your analysis was strong. Don't abandon your reasoning.

2. **INCORPORATE the specific improvements** - Add the insights from the other report (quoted above), fix the errors, address the gaps.

3. **MAINTAIN your voice and structure** - This is still YOUR report. Don't rewrite it from scratch.

4. **PRESERVE the Fact Ledger and Inference Map** - Update them if any factual claims change.

5. **UPDATE the JSON metadata** at the end if the feedback affects investment view, conviction, or confidence.

6. **KEEP THE FULL LENGTH** - Don't compress. The revised report should be similar length to the original (~15-20K words).

## OUTPUT

Output your REVISED full report in the same format as before:
- Full prose research report (main content)
- JSON metadata block at the end (```json ... ```)

The report should be improved but recognizably yours.
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
        verified_package: VerifiedResearchPackage | None = None,
        cross_vertical_map: CrossVerticalMap | None = None,
        **kwargs: Any,
    ) -> tuple[SynthesisOutput, SynthesisOutput]:
        """Execute Stage 4: Dual Synthesis.

        Runs Claude and GPT syntheses in parallel.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            discovery_output: Discovery findings from Stage 2.
            vertical_analyses: All vertical analyses from Stage 3.
            verified_package: Optional VerifiedResearchPackage from Verifier.
            cross_vertical_map: Optional CrossVerticalMap from Integrator.

        Returns:
            Tuple of (claude_synthesis, gpt_synthesis).
        """
        self.log_info(
            "Starting dual synthesis",
            ticker=run_state.ticker,
            vertical_count=len(vertical_analyses),
            has_verified_package=verified_package is not None,
            has_cross_vertical_map=cross_vertical_map is not None,
        )

        run_state.phase = Phase.SYNTHESIZE

        # Build the shared prompt
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Format vertical analyses - these contain full prose from Deep Research
        vertical_str = self._format_vertical_analyses(vertical_analyses)

        # Format verified facts section
        verified_facts_section = self._format_verified_facts(verified_package)

        # Format cross-vertical map section
        cross_vertical_section = self._format_cross_vertical_map(cross_vertical_map)

        # Note: We don't pass CompanyContext here because Deep Research already
        # incorporated all that data into their analyses. Passing it again would
        # be redundant and waste tokens.
        prompt = SYNTHESIS_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            vertical_analyses=vertical_str,
            verified_facts_section=verified_facts_section,
            cross_vertical_section=cross_vertical_section,
        )

        # Aggregate evidence IDs from company context and all vertical analyses
        all_evidence_ids: list[str] = list(company_context.evidence_ids)
        for va in vertical_analyses:
            for eid in va.evidence_ids:
                if eid not in all_evidence_ids:
                    all_evidence_ids.append(eid)
        aggregated_evidence_ids = tuple(all_evidence_ids)

        # Run both syntheses in parallel, save each as it completes
        self.log_info("Running Claude and GPT syntheses in parallel", ticker=run_state.ticker)

        import json
        from pathlib import Path

        claude_task = asyncio.create_task(self._run_claude_synthesis(prompt, aggregated_evidence_ids))
        gpt_task = asyncio.create_task(self._run_gpt_synthesis(prompt, aggregated_evidence_ids))

        claude_synthesis = None
        gpt_synthesis = None

        # Get output_dir from kwargs (passed by pipeline)
        output_dir = kwargs.get("output_dir")
        if output_dir is None:
            output_dir = Path(f"output/{run_state.run_id}")
        else:
            output_dir = Path(output_dir)

        # Wait for tasks and save as each completes
        pending = {claude_task, gpt_task}
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                try:
                    result = task.result()
                    if task == claude_task:
                        claude_synthesis = result
                        self.log_info("Claude synthesis completed, saving immediately")
                        # Save Claude synthesis immediately
                        claude_file = output_dir / "stage4_claude_synthesis.json"
                        claude_file.write_text(json.dumps({
                            "full_report": result.full_report,
                            "investment_view": result.investment_view,
                            "conviction": result.conviction,
                            "overall_confidence": result.overall_confidence,
                            "thesis_summary": result.thesis_summary,
                            "synthesizer_model": result.synthesizer_model,
                        }, indent=2))
                    else:
                        gpt_synthesis = result
                        self.log_info("GPT synthesis completed, saving immediately")
                        # Save GPT synthesis immediately
                        gpt_file = output_dir / "stage4_gpt_synthesis.json"
                        gpt_file.write_text(json.dumps({
                            "full_report": result.full_report,
                            "investment_view": result.investment_view,
                            "conviction": result.conviction,
                            "overall_confidence": result.overall_confidence,
                            "thesis_summary": result.thesis_summary,
                            "synthesizer_model": result.synthesizer_model,
                        }, indent=2))
                except Exception as e:
                    if task == claude_task:
                        self.log_error("Claude synthesis failed", error=str(e))
                        raise e
                    else:
                        self.log_warning("GPT synthesis failed, will use Claude for both", error=str(e))

        # If GPT failed, use Claude for both
        if gpt_synthesis is None:
            gpt_synthesis = claude_synthesis

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
        """Format vertical analyses for the prompt.

        Deep Research now outputs full prose analysis stored in business_understanding.
        We pass through the full prose to preserve all the nuanced analysis.
        """
        sections = []
        for analysis in analyses:
            # business_understanding contains the FULL prose analysis from Deep Research
            # It already has sections for Executive Summary, Competitive Position, etc.
            # Just pass it through with a header
            sections.append(f"""
---
## Vertical: {analysis.vertical_name}
---

{analysis.business_understanding}

**Analysis Confidence:** {analysis.overall_confidence:.0%}
""")
        return "\n".join(sections)

    def _format_verified_facts(
        self,
        package: VerifiedResearchPackage | None,
    ) -> str:
        """Format verified facts for the synthesis prompt.

        Groups facts by verification status and includes evidence IDs.
        """
        if not package or not package.all_verified_facts:
            return "(No verified facts available)"

        lines = []

        def _format_evidence_refs(fact: Fact) -> str:
            evidence_ids = fact.evidence_ids or ([fact.evidence_id] if fact.evidence_id else [])
            if not evidence_ids:
                return "[no_evidence]"
            return f"[{', '.join(evidence_ids[:3])}]"

        # Group by status
        verified = [vf for vf in package.all_verified_facts if vf.status == VerificationStatus.VERIFIED]
        partial = [vf for vf in package.all_verified_facts if vf.status == VerificationStatus.PARTIAL]
        contradicted = [vf for vf in package.all_verified_facts if vf.status == VerificationStatus.CONTRADICTED]
        unverifiable = [vf for vf in package.all_verified_facts if vf.status == VerificationStatus.UNVERIFIABLE]

        # Verified facts (highest priority for citations)
        if verified:
            lines.append("### VERIFIED FACTS (cite these with confidence)")
            for vf in verified[:15]:  # Limit to top 15
                evidence_ref = _format_evidence_refs(vf.original_fact)
                lines.append(f"- {evidence_ref} {vf.original_fact.statement} (conf: {vf.adjusted_confidence:.0%})")

        # Partial facts
        if partial:
            lines.append("\n### PARTIALLY VERIFIED (use with caution)")
            for vf in partial[:10]:
                evidence_ref = _format_evidence_refs(vf.original_fact)
                lines.append(f"- {evidence_ref} {vf.original_fact.statement}")

        # Contradicted facts (warn about these)
        if contradicted:
            lines.append("\n### CONTRADICTED (DO NOT USE - conflicts with ground truth)")
            for vf in contradicted:
                evidence_ref = _format_evidence_refs(vf.original_fact)
                lines.append(f"- {evidence_ref} {vf.original_fact.statement}")
                lines.append(f"  ** Contradiction: {vf.verification_notes}")

        # Critical issues
        if package.critical_issues:
            lines.append("\n### CRITICAL ISSUES TO ADDRESS")
            for issue in package.critical_issues[:5]:
                lines.append(f"- {issue}")

        # Add summaries from workspace artifacts when available
        extra_sections = []
        summary = self._get_latest_artifact_summary("claim_graph")
        if summary:
            extra_sections.append(f"- Claim graph: {summary}")
        summary = self._get_latest_artifact_summary("entailment_report")
        if summary:
            extra_sections.append(f"- Entailment: {summary}")
        summary = self._get_latest_artifact_summary("coverage_scorecard")
        if summary:
            extra_sections.append(f"- Coverage audit: {summary}")
        summary = self._get_latest_artifact_summary("recency_guard")
        if summary:
            extra_sections.append(f"- Recency guard: {summary}")

        if extra_sections:
            lines.append("\n### ADDITIONAL VALIDATION SIGNALS")
            lines.extend(extra_sections)

        return "\n".join(lines)

    def _get_latest_artifact_summary(self, artifact_type: str) -> str | None:
        """Get the latest workspace artifact summary for a type."""
        if not self.workspace_store:
            return None
        artifacts = self.workspace_store.list_artifacts(artifact_type)
        if not artifacts:
            return None
        summary = artifacts[0].get("summary")
        return summary or None

    def _format_cross_vertical_map(
        self,
        cross_map: CrossVerticalMap | None,
    ) -> str:
        """Format cross-vertical map for the synthesis prompt.

        Includes dependencies, shared risks, and key insights.
        """
        if not cross_map:
            return "(No cross-vertical analysis available)"

        lines = []

        # Foundational verticals
        if cross_map.foundational_verticals:
            lines.append(f"**Foundational Verticals:** {', '.join(cross_map.foundational_verticals)}")
            lines.append("(Other verticals depend on these - prioritize in analysis)")

        # Key dependencies
        if cross_map.key_dependencies:
            lines.append("\n### KEY DEPENDENCIES")
            for dep in cross_map.key_dependencies:
                lines.append(f"- {dep}")

        # Relationships
        if cross_map.relationships:
            lines.append("\n### VERTICAL RELATIONSHIPS")
            for rel in cross_map.relationships[:10]:
                lines.append(f"- {rel.source_vertical} -> {rel.target_vertical} ({rel.relationship_type.value}, {rel.strength})")
                lines.append(f"  {rel.description}")

        # Shared risks
        if cross_map.shared_risks:
            lines.append("\n### SHARED RISKS (affect multiple verticals)")
            for sr in cross_map.shared_risks:
                lines.append(f"- **{sr.risk_description}** ({sr.severity} severity, {sr.probability} probability)")
                lines.append(f"  Affects: {', '.join(sr.affected_verticals)}")

        # Cross-vertical insights
        if cross_map.cross_vertical_insights:
            lines.append("\n### CROSS-VERTICAL INSIGHTS")
            for cvi in cross_map.cross_vertical_insights:
                lines.append(f"- {cvi.insight}")
                lines.append(f"  Implication: {cvi.implication} (conf: {cvi.confidence:.0%})")

        return "\n".join(lines) if lines else "(No cross-vertical patterns identified)"

    async def _run_claude_synthesis(
        self,
        prompt: str,
        aggregated_evidence_ids: tuple[str, ...],
    ) -> SynthesisOutput:
        """Run Claude synthesis with extended thinking."""
        self.log_info("Starting Claude synthesis")

        anthropic = await self._get_anthropic_client()

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are a senior equity research analyst producing comprehensive investment research reports."},
                {"role": "user", "content": prompt},
            ],
            model="claude-opus-4-5-20251101",
            # Note: max_tokens is computed by complete_with_thinking from budget + expected output
        )

        response = await anthropic.complete_with_thinking(
            request,
            budget_tokens=15000,  # Thinking budget for complex synthesis
            expected_output_tokens=25000,  # Full research report needs ~20K words
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
            aggregated_evidence_ids,
        )

    async def _run_gpt_synthesis(
        self,
        prompt: str,
        aggregated_evidence_ids: tuple[str, ...],
    ) -> SynthesisOutput:
        """Run GPT synthesis with high reasoning effort."""
        self.log_info("Starting GPT synthesis")

        openai = await self._get_openai_client()

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are a senior equity research analyst producing comprehensive investment research reports."},
                {"role": "user", "content": prompt},
            ],
            model="gpt-5.2",
            max_tokens=32000,  # Allow 20K+ output for full research report
        )

        response = await openai.complete_with_reasoning(
            request,
            reasoning_effort="medium",  # Use medium to avoid timeouts
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
            aggregated_evidence_ids,
        )

    def _parse_response(
        self,
        content: str,
        synthesizer_model: str,
        base_evidence_ids: tuple[str, ...],
    ) -> SynthesisOutput:
        """Parse the LLM response into SynthesisOutput.

        Extracts investment_view, conviction, confidence, and thesis_summary from the JSON block.
        """
        import json
        import re

        investment_view = "HOLD"
        conviction = "medium"
        overall_confidence = 0.5
        thesis_summary = ""

        # Try to extract JSON block from the end of the response
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                metadata = json.loads(json_match.group(1))
                investment_view = metadata.get("investment_view", "HOLD").upper()
                conviction = metadata.get("conviction", "medium").lower()
                overall_confidence = float(metadata.get("overall_confidence", 0.5))
                thesis_summary = metadata.get("thesis_summary", "")
            except (json.JSONDecodeError, ValueError):
                self.log_warning("Failed to parse JSON metadata from synthesis response")

        return SynthesisOutput(
            full_report=content,
            investment_view=investment_view,
            conviction=conviction,
            overall_confidence=overall_confidence,
            thesis_summary=thesis_summary,
            synthesizer_model=synthesizer_model,
            evidence_ids=list(base_evidence_ids),
        )

    async def revise(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        original_synthesis: SynthesisOutput,
        feedback: EditorialFeedback,
    ) -> SynthesisOutput:
        """Revise a synthesis report based on Judge editorial feedback.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            original_synthesis: The original SynthesisOutput to revise.
            feedback: EditorialFeedback from the Judge.

        Returns:
            Revised SynthesisOutput with incorporated feedback.
        """
        self.log_info(
            "Starting synthesis revision",
            ticker=run_state.ticker,
            original_model=original_synthesis.synthesizer_model,
            insights_to_incorporate=len(feedback.incorporate_from_other),
            errors_to_fix=len(feedback.errors_to_fix),
            gaps_to_address=len(feedback.gaps_to_address),
        )

        # Format the feedback sections
        incorporate_str = self._format_incorporate_feedback(feedback.incorporate_from_other)
        errors_str = self._format_errors_feedback(feedback.errors_to_fix)
        gaps_str = self._format_gaps_feedback(feedback.gaps_to_address)

        # Build the revision prompt
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prompt = REVISION_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            original_report=original_synthesis.full_report,
            incorporate_from_other=incorporate_str,
            errors_to_fix=errors_str,
            gaps_to_address=gaps_str,
            revision_instructions=feedback.revision_instructions,
            current_confidence=f"{feedback.current_confidence:.0%}",
            recommended_confidence=f"{feedback.recommended_confidence:.0%}",
            confidence_reasoning=feedback.confidence_reasoning,
        )

        # Use the same model that produced the original synthesis
        # Pass evidence IDs from original synthesis (which should already be aggregated)
        evidence_ids = tuple(original_synthesis.evidence_ids)
        if original_synthesis.synthesizer_model == "claude":
            revised = await self._run_claude_revision(prompt, evidence_ids)
        else:
            revised = await self._run_gpt_revision(prompt, evidence_ids)

        self.log_info(
            "Completed synthesis revision",
            ticker=run_state.ticker,
            revised_view=revised.investment_view,
            revised_confidence=revised.overall_confidence,
            revised_report_len=len(revised.full_report),
        )

        return revised

    async def resynthesis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
        vertical_analyses: list[VerticalAnalysis],
        feedback: EditorialFeedback,
        verified_package: VerifiedResearchPackage | None = None,
        cross_vertical_map: CrossVerticalMap | None = None,
    ) -> SynthesisOutput:
        """Re-synthesize after Judge rejects both reports.

        When both Claude and GPT syntheses are rejected, we re-run synthesis
        with the rejection reason as additional guidance.

        Args:
            run_state: Current run state.
            company_context: CompanyContext from Stage 1.
            discovery_output: Discovery findings from Stage 2.
            vertical_analyses: All vertical analyses from Stage 3.
            feedback: EditorialFeedback with rejection_reason.
            verified_package: Optional VerifiedResearchPackage from Verifier.
            cross_vertical_map: Optional CrossVerticalMap from Integrator.

        Returns:
            New SynthesisOutput from re-synthesis.
        """
        self.log_info(
            "Starting re-synthesis after Judge rejection",
            ticker=run_state.ticker,
            rejection_reason=feedback.rejection_reason,
        )

        # Build the shared prompt with rejection context prepended
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Format vertical analyses - these contain full prose from Deep Research
        vertical_str = self._format_vertical_analyses(vertical_analyses)

        # Format verified facts section
        verified_facts_section = self._format_verified_facts(verified_package)

        # Format cross-vertical map section
        cross_vertical_section = self._format_cross_vertical_map(cross_vertical_map)

        # Build rejection context
        rejection_context = f"""
## CRITICAL: PREVIOUS SYNTHESES REJECTED

The Judge reviewed two previous synthesis attempts and rejected BOTH.
You must address the following critical issues:

**Rejection Reason:**
{feedback.rejection_reason or "No specific rejection reason provided."}

**Errors to Fix ({len(feedback.errors_to_fix)}):**
{self._format_errors_feedback(feedback.errors_to_fix)}

**Gaps to Address ({len(feedback.gaps_to_address)}):**
{self._format_gaps_feedback(feedback.gaps_to_address)}

**Revision Instructions:**
{feedback.revision_instructions}

---
"""

        # Build the full prompt with rejection context
        prompt = rejection_context + SYNTHESIS_PROMPT.format(
            date=today,
            ticker=company_context.symbol,
            company_name=company_context.company_name,
            vertical_analyses=vertical_str,
            verified_facts_section=verified_facts_section,
            cross_vertical_section=cross_vertical_section,
        )

        # Re-run synthesis with Claude (default)
        result = await self._run_claude_synthesis(prompt, company_context)

        self.log_info(
            "Completed re-synthesis",
            ticker=run_state.ticker,
            view=result.investment_view,
            confidence=result.overall_confidence,
        )

        return result

    def _format_incorporate_feedback(self, items: list) -> str:
        """Format insights to incorporate from other synthesis."""
        if not items:
            return "No additional insights to incorporate."

        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"""
**{i}. From section: {item.section}**

> {item.what_to_incorporate}

*Why:* {item.why}
*How to integrate:* {item.how_to_integrate}
""")
        return "\n".join(lines)

    def _format_errors_feedback(self, items: list) -> str:
        """Format errors to fix."""
        if not items:
            return "No errors identified."

        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"""
**{i}. Location:** {item.location}
- **Error:** {item.error}
- **Correction:** {item.correction}
""")
        return "\n".join(lines)

    def _format_gaps_feedback(self, items: list) -> str:
        """Format gaps to address."""
        if not items:
            return "No gaps identified."

        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"""
**{i}. Missing:** {item.missing}
- **Why important:** {item.why_important}
- **Suggestion:** {item.suggestion}
""")
        return "\n".join(lines)

    async def _run_claude_revision(
        self,
        prompt: str,
        evidence_ids: tuple[str, ...],
    ) -> SynthesisOutput:
        """Run Claude revision of the synthesis report."""
        self.log_info("Starting Claude revision")

        anthropic = await self._get_anthropic_client()

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are revising your equity research report based on editorial feedback. Preserve your core thesis while incorporating the improvements."},
                {"role": "user", "content": prompt},
            ],
            model="claude-opus-4-5-20251101",
            # Note: max_tokens is computed by complete_with_thinking from budget + expected output
        )

        response = await anthropic.complete_with_thinking(
            request,
            budget_tokens=12000,  # Less thinking needed for revision
            expected_output_tokens=25000,  # Revised report still needs full output
        )

        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="anthropic",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="revision_claude",
            )

        self.log_info(
            "Completed Claude revision",
            thinking_tokens=response.metadata.get("thinking_tokens") if response.metadata else 0,
        )

        return self._parse_response(response.content, "claude", evidence_ids)

    async def _run_gpt_revision(
        self,
        prompt: str,
        evidence_ids: tuple[str, ...],
    ) -> SynthesisOutput:
        """Run GPT revision of the synthesis report."""
        self.log_info("Starting GPT revision")

        openai = await self._get_openai_client()

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are revising your equity research report based on editorial feedback. Preserve your core thesis while incorporating the improvements."},
                {"role": "user", "content": prompt},
            ],
            model="gpt-5.2",
            max_tokens=32000,
        )

        response = await openai.complete_with_reasoning(
            request,
            reasoning_effort="high",
        )

        if self.budget_tracker:
            self.budget_tracker.record_usage(
                provider="openai",
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                agent=self.name,
                phase="revision_gpt",
            )

        self.log_info(
            "Completed GPT revision",
            reasoning_tokens=response.metadata.get("reasoning_tokens") if response.metadata else 0,
        )

        return self._parse_response(response.content, "gpt", evidence_ids)

    async def close(self) -> None:
        """Close any open clients."""
        if self._anthropic_client:
            await self._anthropic_client.close()
            self._anthropic_client = None
        if self._openai_client:
            await self._openai_client.close()
            self._openai_client = None
