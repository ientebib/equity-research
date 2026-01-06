"""
Recency Guard Agent.

Systematic knowledge-cutoff neutralization.
Generates hypotheses about potentially outdated priors and forces
targeted recency queries to confirm/deny those priors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.router import AgentRole
from er.types import (
    CompanyContext,
    CoverageScorecard,
    RecencyFinding,
    RecencyGuardOutput,
    RunState,
    ThreadBrief,
)


# Maximum recency queries to generate
MAX_RECENCY_QUERIES = 10


class RecencyGuardAgent(Agent):
    """Neutralizes knowledge-cutoff risks through forced recency checks.

    Responsibilities:
    1. Generate hypotheses about potentially outdated priors
    2. Force targeted recency queries (<= 90 days)
    3. Confirm or deny priors with fresh evidence
    4. Update ThreadBriefs or produce RecencyFindings
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Recency Guard.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)

    @property
    def name(self) -> str:
        return "recency_guard"

    @property
    def role(self) -> str:
        return "Check for outdated priors and force recency queries"

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        coverage_scorecard: CoverageScorecard | None = None,
        thread_briefs: list[ThreadBrief] | None = None,
        recency_days: int = 90,
        **kwargs: Any,
    ) -> RecencyGuardOutput:
        """Run the recency guard check.

        Args:
            run_state: Current run state.
            company_context: Company context.
            coverage_scorecard: Optional coverage scorecard.
            thread_briefs: Optional thread briefs from discovery.
            recency_days: Recency window for checks.

        Returns:
            RecencyGuardOutput with findings and forced queries.
        """
        self.log_info(
            "Starting recency guard",
            ticker=run_state.ticker,
            recency_days=recency_days,
        )

        # Generate hypotheses about potentially outdated priors
        hypotheses = await self._generate_outdated_prior_hypotheses(
            company_context=company_context,
            thread_briefs=thread_briefs,
        )

        self.log_info(
            "Generated outdated prior hypotheses",
            count=len(hypotheses),
        )

        # Generate forced recency queries
        forced_queries = self._generate_recency_queries(
            company_name=company_context.company_name,
            hypotheses=hypotheses,
            recency_days=recency_days,
        )

        # In a real implementation, would execute queries and get findings
        # For now, create placeholder findings
        findings = [
            RecencyFinding(
                hypothesis=h,
                query=q,
                finding="Pending verification",
                status="inconclusive",
                evidence_ids=[],
                confidence=0.5,
            )
            for h, q in zip(hypotheses[:MAX_RECENCY_QUERIES], forced_queries)
        ]

        output = RecencyGuardOutput(
            ticker=run_state.ticker,
            as_of_date=datetime.utcnow().isoformat(),
            outdated_priors_checked=hypotheses,
            findings=findings,
            forced_queries=forced_queries,
            evidence_ids=[],
        )

        # Store artifact
        if self.workspace_store:
            self.workspace_store.put_artifact(
                artifact_type="recency_guard",
                producer=self.name,
                json_obj=output.to_dict(),
                summary=f"Checked {len(hypotheses)} priors, {len(forced_queries)} queries",
            )

        self.log_info(
            "Recency guard complete",
            ticker=run_state.ticker,
            hypotheses=len(hypotheses),
            forced_queries=len(forced_queries),
        )

        return output

    async def _generate_outdated_prior_hypotheses(
        self,
        company_context: CompanyContext,
        thread_briefs: list[ThreadBrief] | None = None,
    ) -> list[str]:
        """Generate hypotheses about potentially outdated priors.

        Uses LLM to identify what information might be stale.
        """
        # Build context
        company_name = company_context.company_name
        sector = company_context.profile.get("sector", "") if company_context.profile else ""
        industry = company_context.profile.get("industry", "") if company_context.profile else ""

        # Include thread briefs if available
        threads_context = ""
        if thread_briefs:
            threads_context = "\n".join([
                f"- {tb.rationale}" for tb in thread_briefs[:5]
            ])

        prompt = f"""You are a research analyst checking for potentially outdated information.

Company: {company_name}
Sector: {sector}
Industry: {industry}

Research threads being investigated:
{threads_context if threads_context else "(None provided)"}

Generate a list of 5-10 specific hypotheses about information that might be outdated or
might have changed recently. These should be:

1. Material to investment analysis
2. Likely to have changed in the last 90 days
3. Specific enough to verify with a targeted search

Examples:
- "Product X launch timeline may have changed"
- "Guidance for next quarter may have been updated"
- "Competitive dynamics with [competitor] may have shifted"
- "Regulatory status of [issue] may have evolved"

Format: Return a JSON array of strings, each being a hypothesis.
Example: ["hypothesis 1", "hypothesis 2", ...]

Output ONLY valid JSON."""

        try:
            response = await self.llm_router.call(
                role=AgentRole.WORKHORSE,  # Use cheap model
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                response_format={"type": "json_object"},
            )

            content = response.get("content", "")
            # Parse JSON
            import json

            # Extract JSON from response
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            # Try to parse as array directly or as object with array
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    return parsed[:MAX_RECENCY_QUERIES]
                elif isinstance(parsed, dict):
                    # Look for an array in the dict
                    for v in parsed.values():
                        if isinstance(v, list):
                            return v[:MAX_RECENCY_QUERIES]
            except json.JSONDecodeError:
                pass

        except Exception as e:
            self.log_warning(f"Failed to generate hypotheses: {e}")

        # Fallback hypotheses
        return self._generate_fallback_hypotheses(company_name, sector)

    def _generate_fallback_hypotheses(
        self,
        company_name: str,
        sector: str,
    ) -> list[str]:
        """Generate fallback hypotheses when LLM fails."""
        hypotheses = [
            f"{company_name} may have updated guidance or outlook",
            f"{company_name} may have announced new products or services",
            f"{company_name} competitive position may have changed",
            f"{company_name} may have new regulatory or legal developments",
            f"{company_name} capital allocation strategy may have changed",
        ]

        if sector in ["Technology", "Communication Services"]:
            hypotheses.extend([
                f"{company_name} AI strategy or investments may have evolved",
                f"{company_name} may have new infrastructure announcements",
            ])

        return hypotheses[:MAX_RECENCY_QUERIES]

    def _generate_recency_queries(
        self,
        company_name: str,
        hypotheses: list[str],
        recency_days: int,
    ) -> list[str]:
        """Generate targeted search queries from hypotheses."""
        queries = []

        for hypothesis in hypotheses[:MAX_RECENCY_QUERIES]:
            # Convert hypothesis to search query
            # Remove common phrases and make it search-friendly
            query = hypothesis.replace("may have", "").replace("might have", "")
            query = query.replace("could have", "").replace("has ", "")

            # Add company name if not present
            if company_name.lower() not in query.lower():
                query = f"{company_name} {query}"

            # Add recency indicator
            year = datetime.now().year
            query = f"{query} {year}"

            queries.append(query.strip())

        return queries

    async def close(self) -> None:
        """Close any open resources."""
        pass
