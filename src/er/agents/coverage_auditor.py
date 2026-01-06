"""
Coverage Auditor Agent.

Audits research coverage across required categories and triggers
bounded second-pass retrieval when thresholds are not met.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from er.agents.base import Agent, AgentContext
from er.retrieval.query_planner import QueryPlanner, QueryPlan
from er.retrieval.source_catalog import SourceCatalog
from er.types import (
    CompanyContext,
    CoverageAction,
    CoverageCategory,
    CoverageCategoryResult,
    CoverageScorecard,
    CoverageStatus,
    RunState,
)


# Default thresholds for coverage
DEFAULT_MIN_CARDS = {
    CoverageCategory.RECENT_DEVELOPMENTS: 3,
    CoverageCategory.COMPETITIVE_MOVES: 2,
    CoverageCategory.PRODUCT_ROADMAP: 2,
    CoverageCategory.REGULATORY_LITIGATION: 2,
    CoverageCategory.CAPITAL_ALLOCATION: 2,
    CoverageCategory.SEGMENT_ECONOMICS: 2,
    CoverageCategory.AI_INFRASTRUCTURE: 2,
    CoverageCategory.MANAGEMENT_TONE: 1,
}

# Maximum second-pass queries
MAX_SECOND_PASS_QUERIES = 10


class CoverageAuditor(Agent):
    """Audits research coverage and triggers second-pass retrieval.

    Responsibilities:
    1. Compute CoverageScorecard from evidence cards
    2. Identify coverage gaps
    3. Trigger bounded second-pass retrieval if needed
    4. Store artifacts in WorkspaceStore
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Coverage Auditor.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self.source_catalog = SourceCatalog()
        self.query_planner = QueryPlanner(source_catalog=self.source_catalog)

    @property
    def name(self) -> str:
        return "coverage_auditor"

    @property
    def role(self) -> str:
        return "Audit research coverage and fill gaps"

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        evidence_cards: list[dict[str, Any]],
        query_plan: QueryPlan | None = None,
        recency_days: int = 90,
        **kwargs: Any,
    ) -> tuple[CoverageScorecard, list[CoverageAction]]:
        """Run the coverage audit.

        Args:
            run_state: Current run state.
            company_context: Company context.
            evidence_cards: List of evidence card dicts from discovery.
            query_plan: Optional existing query plan.
            recency_days: Recency window for coverage check.

        Returns:
            Tuple of (CoverageScorecard, list of CoverageActions taken).
        """
        self.log_info(
            "Starting coverage audit",
            ticker=run_state.ticker,
            evidence_cards=len(evidence_cards),
        )

        # Determine applicable categories
        sector = company_context.profile.get("sector", "") if company_context.profile else ""
        categories = self._get_applicable_categories(sector)

        # Compute initial scorecard
        scorecard = self._compute_scorecard(
            ticker=run_state.ticker,
            evidence_cards=evidence_cards,
            categories=categories,
            recency_days=recency_days,
        )

        self.log_info(
            "Initial coverage computed",
            ticker=run_state.ticker,
            overall_status=scorecard.overall_status.value,
            pass_rate=scorecard.pass_rate,
        )

        # Check if second pass needed
        actions: list[CoverageAction] = []
        if scorecard.overall_status == CoverageStatus.FAIL:
            self.log_info("Coverage below threshold, running second pass")

            # Run bounded second pass
            actions = await self._run_second_pass(
                run_state=run_state,
                company_context=company_context,
                scorecard=scorecard,
                evidence_cards=evidence_cards,
            )

            # Recompute scorecard with new evidence
            if actions:
                # Collect new evidence IDs
                new_evidence_ids = []
                for action in actions:
                    new_evidence_ids.extend(action.evidence_ids)

                # Recompute (in a real impl, would fetch new cards)
                scorecard = self._compute_scorecard(
                    ticker=run_state.ticker,
                    evidence_cards=evidence_cards,  # Would include new cards
                    categories=categories,
                    recency_days=recency_days,
                )

        # Store artifacts
        if self.workspace_store:
            self.workspace_store.put_artifact(
                artifact_type="coverage_scorecard",
                producer=self.name,
                json_obj=scorecard.to_dict(),
                summary=f"Coverage: {scorecard.overall_status.value}, {scorecard.pass_rate:.0%} pass rate",
            )

            if actions:
                actions_dict = {
                    "actions": [a.to_dict() for a in actions],
                    "total_queries": len(actions),
                }
                self.workspace_store.put_artifact(
                    artifact_type="coverage_actions",
                    producer=self.name,
                    json_obj=actions_dict,
                    summary=f"{len(actions)} gap-filling actions taken",
                )

        self.log_info(
            "Coverage audit complete",
            ticker=run_state.ticker,
            final_status=scorecard.overall_status.value,
            actions_taken=len(actions),
        )

        return scorecard, actions

    def _get_applicable_categories(self, sector: str) -> list[CoverageCategory]:
        """Get applicable coverage categories based on sector."""
        categories = [
            CoverageCategory.RECENT_DEVELOPMENTS,
            CoverageCategory.COMPETITIVE_MOVES,
            CoverageCategory.CAPITAL_ALLOCATION,
            CoverageCategory.SEGMENT_ECONOMICS,
            CoverageCategory.MANAGEMENT_TONE,
            CoverageCategory.REGULATORY_LITIGATION,
        ]

        if sector in ["Technology", "Consumer Cyclical", "Healthcare"]:
            categories.append(CoverageCategory.PRODUCT_ROADMAP)

        if sector in ["Technology", "Communication Services"]:
            categories.append(CoverageCategory.AI_INFRASTRUCTURE)

        return categories

    def _compute_scorecard(
        self,
        ticker: str,
        evidence_cards: list[dict[str, Any]],
        categories: list[CoverageCategory],
        recency_days: int,
    ) -> CoverageScorecard:
        """Compute coverage scorecard from evidence cards."""
        results: list[CoverageCategoryResult] = []
        total_cards = len(evidence_cards)
        total_queries = 0
        passes = 0

        for category in categories:
            # Count cards matching this category
            # In practice, would use more sophisticated matching
            matching_cards = self._count_matching_cards(evidence_cards, category)
            required = DEFAULT_MIN_CARDS.get(category, 2)

            # Determine status
            if matching_cards >= required:
                status = CoverageStatus.PASS
                passes += 1
            elif matching_cards >= required // 2:
                status = CoverageStatus.MARGINAL
            else:
                status = CoverageStatus.FAIL

            # Get evidence IDs from matching cards
            evidence_ids = self._get_matching_evidence_ids(evidence_cards, category)[:5]

            results.append(CoverageCategoryResult(
                category=category,
                required_min_cards=required,
                found_cards=matching_cards,
                queries_run=[],  # Would track from query plan
                top_evidence_ids=evidence_ids,
                status=status,
            ))

        # Compute overall status
        pass_rate = passes / len(categories) if categories else 0.0
        if pass_rate >= 0.8:
            overall_status = CoverageStatus.PASS
        elif pass_rate >= 0.5:
            overall_status = CoverageStatus.MARGINAL
        else:
            overall_status = CoverageStatus.FAIL

        return CoverageScorecard(
            ticker=ticker,
            as_of_date=datetime.utcnow().isoformat(),
            recency_days=recency_days,
            results=results,
            overall_status=overall_status,
            pass_rate=pass_rate,
            total_evidence_cards=total_cards,
            total_queries_run=total_queries,
        )

    def _count_matching_cards(
        self,
        evidence_cards: list[dict[str, Any]],
        category: CoverageCategory,
    ) -> int:
        """Count evidence cards matching a category.

        Uses simple keyword matching. In practice would use more sophisticated
        classification.
        """
        keywords = self._get_category_keywords(category)
        count = 0

        for card in evidence_cards:
            text = (
                card.get("summary", "") +
                " " +
                card.get("title", "") +
                " " +
                " ".join(card.get("key_facts", []))
            ).lower()

            if any(kw in text for kw in keywords):
                count += 1

        return count

    def _get_matching_evidence_ids(
        self,
        evidence_cards: list[dict[str, Any]],
        category: CoverageCategory,
    ) -> list[str]:
        """Get evidence IDs for cards matching a category."""
        keywords = self._get_category_keywords(category)
        ids = []

        for card in evidence_cards:
            text = (
                card.get("summary", "") +
                " " +
                card.get("title", "")
            ).lower()

            if any(kw in text for kw in keywords):
                if "raw_evidence_id" in card:
                    ids.append(card["raw_evidence_id"])
                elif "card_id" in card:
                    ids.append(card["card_id"])

        return ids

    def _get_category_keywords(self, category: CoverageCategory) -> list[str]:
        """Get keywords for category matching."""
        keyword_map = {
            CoverageCategory.RECENT_DEVELOPMENTS: ["news", "announce", "launch", "update"],
            CoverageCategory.COMPETITIVE_MOVES: ["competitor", "market share", "rivalry", "versus"],
            CoverageCategory.PRODUCT_ROADMAP: ["product", "roadmap", "feature", "release"],
            CoverageCategory.REGULATORY_LITIGATION: ["lawsuit", "regulatory", "antitrust", "investigation"],
            CoverageCategory.CAPITAL_ALLOCATION: ["buyback", "dividend", "acquisition", "m&a"],
            CoverageCategory.SEGMENT_ECONOMICS: ["segment", "revenue", "margin", "profitability"],
            CoverageCategory.AI_INFRASTRUCTURE: ["ai", "artificial intelligence", "gpu", "machine learning"],
            CoverageCategory.MANAGEMENT_TONE: ["guidance", "outlook", "ceo", "cfo", "earnings call"],
        }
        return keyword_map.get(category, [])

    async def _run_second_pass(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        scorecard: CoverageScorecard,
        evidence_cards: list[dict[str, Any]],
    ) -> list[CoverageAction]:
        """Run bounded second-pass retrieval for failing categories."""
        actions: list[CoverageAction] = []
        queries_remaining = MAX_SECOND_PASS_QUERIES

        # Get failing categories
        failing = [
            r for r in scorecard.results
            if r.status == CoverageStatus.FAIL
        ]

        for result in failing:
            if queries_remaining <= 0:
                break

            # Generate targeted query for this category
            query = self._generate_gap_query(
                company_name=company_context.company_name,
                category=result.category,
            )

            # In a real implementation, would call WebResearchService here
            # For now, record the action
            action = CoverageAction(
                category=result.category,
                query=query,
                urls_fetched=[],  # Would be populated by actual fetch
                evidence_ids=[],  # Would be populated by actual fetch
                success=True,
                notes="Second-pass query generated",
            )
            actions.append(action)
            queries_remaining -= 1

        return actions

    def _generate_gap_query(
        self,
        company_name: str,
        category: CoverageCategory,
    ) -> str:
        """Generate a query to fill a coverage gap."""
        query_templates = {
            CoverageCategory.RECENT_DEVELOPMENTS: f"{company_name} latest news developments 2024",
            CoverageCategory.COMPETITIVE_MOVES: f"{company_name} competitive landscape market share",
            CoverageCategory.PRODUCT_ROADMAP: f"{company_name} product launch roadmap 2024",
            CoverageCategory.REGULATORY_LITIGATION: f"{company_name} regulatory antitrust lawsuit",
            CoverageCategory.CAPITAL_ALLOCATION: f"{company_name} capital allocation buyback M&A",
            CoverageCategory.SEGMENT_ECONOMICS: f"{company_name} segment revenue breakdown analysis",
            CoverageCategory.AI_INFRASTRUCTURE: f"{company_name} AI artificial intelligence strategy",
            CoverageCategory.MANAGEMENT_TONE: f"{company_name} earnings call management guidance",
        }
        return query_templates.get(category, f"{company_name} {category.value}")

    async def close(self) -> None:
        """Close any open resources."""
        pass
