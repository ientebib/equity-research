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
from er.retrieval.service import WebResearchService
from er.types import (
    CompanyContext,
    CoverageScorecard,
    DiscoveredThread,
    RecencyFinding,
    RecencyGuardOutput,
    RunState,
    ThreadBrief,
)


# Maximum recency queries to generate
MAX_RECENCY_QUERIES = 10
MAX_THREAD_RECENCY_QUERIES = 8
MAX_THREAD_RECENCY_CARDS = 3


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
        self._web_research_service: WebResearchService | None = None

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
        threads: list[DiscoveredThread] | None = None,
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

        # Execute forced queries via evidence-first retrieval
        findings: list[RecencyFinding] = []
        evidence_ids: list[str] = []
        if forced_queries:
            try:
                web_service = await self._get_web_research_service()
                results = await web_service.research_batch(
                    queries=forced_queries[:MAX_RECENCY_QUERIES],
                    max_results_per_query=2,
                    recency_days=recency_days,
                    max_total_queries=MAX_RECENCY_QUERIES,
                )

                for hypothesis, query, result in zip(hypotheses[:MAX_RECENCY_QUERIES], forced_queries, results):
                    if result.evidence_cards:
                        top_card = result.evidence_cards[0]
                        finding_text = top_card.summary or "Recent evidence found"
                        status = "confirmed"
                        confidence = min(0.8, 0.5 + 0.05 * len(result.evidence_cards))
                    else:
                        finding_text = "No recent evidence found"
                        status = "inconclusive"
                        confidence = 0.4

                    findings.append(RecencyFinding(
                        hypothesis=hypothesis,
                        query=query,
                        finding=finding_text,
                        status=status,
                        evidence_ids=result.evidence_ids,
                        confidence=confidence,
                    ))
                    evidence_ids.extend(result.evidence_ids)
            except Exception as e:
                self.log_warning("Recency queries failed", error=str(e))

        if not findings:
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
            evidence_ids=list(set(evidence_ids)),
        )

        # Augment thread briefs with recent developments for deep research
        if thread_briefs and threads:
            await self._augment_thread_briefs_with_recency(
                company_context=company_context,
                thread_briefs=thread_briefs,
                threads=threads,
                recency_days=recency_days,
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

    async def _get_web_research_service(self) -> WebResearchService:
        """Get or create WebResearchService."""
        if self._web_research_service is None:
            self._web_research_service = WebResearchService(
                llm_router=self.llm_router,
                evidence_store=self.evidence_store,
                workspace_store=self.workspace_store,
            )
        return self._web_research_service

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

    async def _augment_thread_briefs_with_recency(
        self,
        company_context: CompanyContext,
        thread_briefs: list[ThreadBrief],
        threads: list[DiscoveredThread],
        recency_days: int,
    ) -> None:
        """Attach recent developments to thread briefs for downstream analysis."""
        if not thread_briefs or not threads:
            return

        brief_map = {tb.thread_id: tb for tb in thread_briefs}
        threads_by_priority = sorted(threads, key=lambda t: t.priority)
        target_threads = threads_by_priority[:MAX_THREAD_RECENCY_QUERIES]

        queries: list[str] = []
        thread_ids: list[str] = []
        for thread in target_threads:
            queries.append(self._build_thread_recency_query(company_context.company_name, thread))
            thread_ids.append(thread.thread_id)

        if not queries:
            return

        web_service = await self._get_web_research_service()
        results = await web_service.research_batch(
            queries=queries,
            max_results_per_query=2,
            recency_days=recency_days,
            max_total_queries=len(queries),
        )

        now = datetime.utcnow()
        for thread_id, thread, result in zip(thread_ids, target_threads, results):
            brief = brief_map.get(thread_id)
            if not brief or not result.evidence_cards:
                continue

            developments, evidence_ids = self._summarize_recency_cards(
                result.evidence_cards[:MAX_THREAD_RECENCY_CARDS],
                now,
            )
            if not developments:
                continue

            brief.recent_developments = developments
            brief.recency_evidence_ids = evidence_ids
            for eid in evidence_ids:
                if eid not in brief.key_evidence_ids:
                    brief.key_evidence_ids.append(eid)

            if not brief.recency_questions:
                brief.recency_questions = self._build_recency_questions(thread, developments)

    def _build_thread_recency_query(
        self,
        company_name: str,
        thread: DiscoveredThread,
    ) -> str:
        """Build a focused recency query for a thread."""
        year = datetime.now().year
        base = thread.name
        if thread.research_questions:
            base = thread.research_questions[0].rstrip("?")
        query = f"{company_name} {thread.name} {base} {year} updates"
        return query[:200]

    def _summarize_recency_cards(
        self,
        cards: list[Any],
        now: datetime,
    ) -> tuple[list[str], list[str]]:
        """Create recency bullets with 30/60/90-day buckets."""
        developments: list[str] = []
        evidence_ids: list[str] = []

        for card in cards:
            bucket = self._bucket_by_recency(card.published_date, now)
            title = (card.title or "").strip()
            source = (card.source or "").strip()
            detail = (card.summary or "").strip()
            if len(detail) > 160:
                detail = f"{detail[:157]}..."
            evidence_id = getattr(card, "raw_evidence_id", "")

            if evidence_id and evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)

            parts = [f"{bucket}: {title}"]
            if source:
                parts.append(f"({source})")
            if detail:
                parts.append(f"- {detail}")
            if evidence_id:
                parts.append(f"[{evidence_id}]")
            developments.append(" ".join(parts).strip())

        return developments, evidence_ids

    def _bucket_by_recency(self, published_date: str | None, now: datetime) -> str:
        """Bucket a published date into 30/60/90-day windows."""
        if published_date:
            try:
                published = datetime.fromisoformat(published_date)
                age_days = max(0, (now - published).days)
                if age_days <= 30:
                    return "30d"
                if age_days <= 60:
                    return "60d"
                if age_days <= 90:
                    return "90d"
            except ValueError:
                pass
        return "90d"

    def _build_recency_questions(
        self,
        thread: DiscoveredThread,
        developments: list[str],
    ) -> list[str]:
        """Build recency-focused questions to expand scope."""
        topic = developments[0] if developments else thread.name
        if ": " in topic:
            topic = topic.split(": ", 1)[1]
        if "[" in topic:
            topic = topic.split("[", 1)[0].strip()
        if len(topic) > 80:
            topic = f"{topic[:77]}..."

        return [
            f"What changed in the last 30-90 days for {thread.name}, and does it alter growth, margins, or adoption?",
            f"Which recent competitor, regulatory, or platform shifts materially affect {thread.name}?",
            f"Does the development '{topic}' change TAM, pricing, or unit economics for {thread.name}?",
        ]

    async def close(self) -> None:
        """Close any open resources."""
        pass
