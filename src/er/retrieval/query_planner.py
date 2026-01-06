"""
Query Planner for systematic web research.

Generates deterministic query plans based on company context and discovery hints.
Ensures reproducible, bounded web research.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from er.retrieval.source_catalog import SourceCatalog
from er.types import (
    CompanyContext,
    CoverageCategory,
)


@dataclass
class PlannedQuery:
    """A single planned search query."""

    query: str
    category: CoverageCategory
    recency_days: int | None = None
    site_restrict: str | None = None  # e.g., "site:reuters.com"
    max_results: int = 3
    priority: int = 1  # 1 = highest


@dataclass
class QueryPlan:
    """A complete query plan for web research."""

    ticker: str
    company_name: str
    created_at: str
    queries: list[PlannedQuery]
    total_queries: int = 0
    max_results_total: int = 0

    # Quota enforcement
    max_queries_per_category: int = 5
    max_total_queries: int = 25
    max_results_per_query: int = 3

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "created_at": self.created_at,
            "queries": [
                {
                    "query": q.query,
                    "category": q.category.value,
                    "recency_days": q.recency_days,
                    "site_restrict": q.site_restrict,
                    "max_results": q.max_results,
                    "priority": q.priority,
                }
                for q in self.queries
            ],
            "total_queries": self.total_queries,
            "max_results_total": self.max_results_total,
        }


class QueryPlanner:
    """Generates deterministic query plans for web research.

    Given a CompanyContext and optional discovery hints, produces
    a bounded, reproducible set of search queries organized by
    coverage category.
    """

    # Default quotas
    DEFAULT_MAX_QUERIES_PER_CATEGORY = 5
    DEFAULT_MAX_TOTAL_QUERIES = 25
    DEFAULT_MAX_RESULTS_PER_QUERY = 3
    DEFAULT_RECENCY_DAYS = 90

    def __init__(
        self,
        source_catalog: SourceCatalog | None = None,
        max_queries_per_category: int = DEFAULT_MAX_QUERIES_PER_CATEGORY,
        max_total_queries: int = DEFAULT_MAX_TOTAL_QUERIES,
        max_results_per_query: int = DEFAULT_MAX_RESULTS_PER_QUERY,
    ) -> None:
        """Initialize the query planner.

        Args:
            source_catalog: Source catalog for domain lookups. Uses default if None.
            max_queries_per_category: Maximum queries per coverage category.
            max_total_queries: Maximum total queries in the plan.
            max_results_per_query: Maximum results per query.
        """
        self.source_catalog = source_catalog or SourceCatalog()
        self.max_queries_per_category = max_queries_per_category
        self.max_total_queries = max_total_queries
        self.max_results_per_query = max_results_per_query

    def create_plan(
        self,
        company_context: CompanyContext,
        discovery_hints: list[str] | None = None,
        categories: list[CoverageCategory] | None = None,
    ) -> QueryPlan:
        """Create a deterministic query plan.

        Args:
            company_context: Company context with profile and financials.
            discovery_hints: Optional hints from discovery (e.g., specific topics to research).
            categories: Optional list of categories to cover. Uses all if None.

        Returns:
            QueryPlan with bounded set of queries.
        """
        ticker = company_context.symbol
        company_name = company_context.company_name
        sector = company_context.profile.get("sector", "") if company_context.profile else ""
        industry = company_context.profile.get("industry", "") if company_context.profile else ""

        # Determine which categories to cover
        if categories is None:
            categories = self._get_applicable_categories(sector, industry)

        queries: list[PlannedQuery] = []

        # Generate queries for each category
        for category in categories:
            category_queries = self._generate_category_queries(
                ticker=ticker,
                company_name=company_name,
                sector=sector,
                industry=industry,
                category=category,
                hints=discovery_hints,
            )
            queries.extend(category_queries[: self.max_queries_per_category])

        # Add hint-based queries if provided
        if discovery_hints:
            hint_queries = self._generate_hint_queries(
                ticker=ticker,
                company_name=company_name,
                hints=discovery_hints,
            )
            queries.extend(hint_queries)

        # Enforce total query limit
        queries = queries[: self.max_total_queries]

        # Calculate totals
        total_queries = len(queries)
        max_results_total = sum(q.max_results for q in queries)

        return QueryPlan(
            ticker=ticker,
            company_name=company_name,
            created_at=datetime.utcnow().isoformat(),
            queries=queries,
            total_queries=total_queries,
            max_results_total=max_results_total,
            max_queries_per_category=self.max_queries_per_category,
            max_total_queries=self.max_total_queries,
            max_results_per_query=self.max_results_per_query,
        )

    def _get_applicable_categories(
        self,
        sector: str,
        industry: str,
    ) -> list[CoverageCategory]:
        """Get applicable coverage categories based on sector/industry.

        Args:
            sector: Company sector.
            industry: Company industry.

        Returns:
            List of applicable coverage categories.
        """
        # Base categories that apply to all companies
        categories = [
            CoverageCategory.RECENT_DEVELOPMENTS,
            CoverageCategory.COMPETITIVE_MOVES,
            CoverageCategory.CAPITAL_ALLOCATION,
            CoverageCategory.SEGMENT_ECONOMICS,
            CoverageCategory.MANAGEMENT_TONE,
        ]

        # Add regulatory for all (important across sectors)
        categories.append(CoverageCategory.REGULATORY_LITIGATION)

        # Add product roadmap for certain sectors
        if sector in ["Technology", "Consumer Cyclical", "Healthcare"]:
            categories.append(CoverageCategory.PRODUCT_ROADMAP)

        # Add AI/infra for tech-related companies
        if sector in ["Technology", "Communication Services"]:
            categories.append(CoverageCategory.AI_INFRASTRUCTURE)

        return categories

    def _generate_category_queries(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        industry: str,
        category: CoverageCategory,
        hints: list[str] | None = None,
    ) -> list[PlannedQuery]:
        """Generate queries for a specific category.

        Args:
            ticker: Stock ticker.
            company_name: Company name.
            sector: Company sector.
            industry: Company industry.
            category: Coverage category.
            hints: Optional discovery hints.

        Returns:
            List of planned queries.
        """
        queries: list[PlannedQuery] = []

        # Get category config
        cat_config = self.source_catalog.get_category_config(category.value)
        recency_days = cat_config.recency_days if cat_config else self.DEFAULT_RECENCY_DAYS

        # Generate base queries based on category
        if category == CoverageCategory.RECENT_DEVELOPMENTS:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} news {datetime.now().year}",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{ticker} earnings results analysis",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} announcement {datetime.now().year}",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.COMPETITIVE_MOVES:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} competitors market share",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} vs competition analysis",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.PRODUCT_ROADMAP:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} product launch {datetime.now().year}",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} new features roadmap",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.REGULATORY_LITIGATION:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} regulatory investigation",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} lawsuit antitrust",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.CAPITAL_ALLOCATION:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} buyback dividend capital return",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} M&A acquisition",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.SEGMENT_ECONOMICS:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} segment revenue breakdown analysis",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} margin profitability by segment",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.AI_INFRASTRUCTURE:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} AI artificial intelligence strategy",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
                PlannedQuery(
                    query=f"{company_name} GPU TPU infrastructure investment",
                    category=category,
                    recency_days=recency_days,
                    priority=2,
                ),
            ])

        elif category == CoverageCategory.MANAGEMENT_TONE:
            queries.extend([
                PlannedQuery(
                    query=f"{company_name} CEO CFO guidance outlook",
                    category=category,
                    recency_days=recency_days,
                    priority=1,
                ),
            ])

        # Set max_results for all queries
        for q in queries:
            q.max_results = self.max_results_per_query

        return queries

    def _generate_hint_queries(
        self,
        ticker: str,
        company_name: str,
        hints: list[str],
    ) -> list[PlannedQuery]:
        """Generate queries from discovery hints.

        Args:
            ticker: Stock ticker.
            company_name: Company name.
            hints: Discovery hints (e.g., specific topics to research).

        Returns:
            List of planned queries.
        """
        queries: list[PlannedQuery] = []

        for hint in hints[:5]:  # Limit hint queries
            # Create a query from the hint
            query = f"{company_name} {hint}"
            queries.append(PlannedQuery(
                query=query,
                category=CoverageCategory.RECENT_DEVELOPMENTS,  # Default category
                recency_days=90,
                max_results=self.max_results_per_query,
                priority=2,
            ))

        return queries

    def add_site_restrictions(
        self,
        plan: QueryPlan,
        categories_to_restrict: list[CoverageCategory] | None = None,
    ) -> QueryPlan:
        """Add site restrictions to queries based on source catalog.

        This creates additional queries with site: restrictions for high-quality sources.

        Args:
            plan: Existing query plan.
            categories_to_restrict: Categories to add site restrictions. All if None.

        Returns:
            Updated query plan with site-restricted queries added.
        """
        new_queries: list[PlannedQuery] = []

        for query in plan.queries:
            # Add the original query
            new_queries.append(query)

            # Check if we should add site-restricted variants
            if categories_to_restrict is None or query.category in categories_to_restrict:
                # Get preferred domains for this category
                domains = self.source_catalog.get_preferred_domains_for_category(query.category.value)

                # Add up to 2 site-restricted queries for high-rep domains
                for domain in domains[:2]:
                    policy = self.source_catalog.get_policy(domain)
                    if policy.reputation_score >= 0.8:
                        site_query = PlannedQuery(
                            query=query.query,
                            category=query.category,
                            recency_days=query.recency_days,
                            site_restrict=f"site:{domain}",
                            max_results=2,  # Fewer results for site-restricted
                            priority=query.priority,
                        )
                        new_queries.append(site_query)

        # Enforce total limit
        new_queries = new_queries[: self.max_total_queries]

        return QueryPlan(
            ticker=plan.ticker,
            company_name=plan.company_name,
            created_at=plan.created_at,
            queries=new_queries,
            total_queries=len(new_queries),
            max_results_total=sum(q.max_results for q in new_queries),
            max_queries_per_category=plan.max_queries_per_category,
            max_total_queries=plan.max_total_queries,
            max_results_per_query=plan.max_results_per_query,
        )
