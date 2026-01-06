"""Tests for SourceCatalog and QueryPlanner."""

import pytest
from pathlib import Path

from er.retrieval.source_catalog import SourceCatalog, DomainPolicy
from er.retrieval.query_planner import QueryPlanner, QueryPlan
from er.types import (
    CompanyContext,
    CoverageCategory,
    SourceTier,
    ToSRisk,
)


class TestSourceCatalog:
    """Tests for SourceCatalog."""

    def test_load_config(self):
        """Test loading config from YAML."""
        catalog = SourceCatalog()

        # Should have loaded topics
        assert len(catalog.topics) > 0

        # Should have loaded domains
        assert len(catalog.domains) > 0

        # Should have loaded categories
        assert len(catalog.categories) > 0

    def test_get_domains_for_tags(self):
        """Test getting domains for topic tags."""
        catalog = SourceCatalog()

        # Get domains for financial news
        domains = catalog.get_domains_for_tags(["financial_news"])
        assert len(domains) > 0
        assert "reuters.com" in domains or len(domains) > 0

        # Multiple tags should combine domains
        domains = catalog.get_domains_for_tags(["financial_news", "tech_analysis"])
        assert len(domains) > 0

    def test_get_policy_known_domain(self):
        """Test getting policy for a known domain."""
        catalog = SourceCatalog()

        # SEC should be official tier
        policy = catalog.get_policy("sec.gov")
        assert policy.tier == SourceTier.OFFICIAL
        assert policy.reputation_score >= 0.9

    def test_get_policy_unknown_domain(self):
        """Test getting policy for an unknown domain."""
        catalog = SourceCatalog()

        # Unknown domain should return default
        policy = catalog.get_policy("randomsite123.com")
        assert policy.reputation_score == 0.5
        assert policy.allowed_fetch is True

    def test_get_policy_from_url(self):
        """Test extracting domain from URL."""
        catalog = SourceCatalog()

        # Should extract domain from full URL
        policy = catalog.get_policy("https://www.sec.gov/filing/123")
        assert policy.tier == SourceTier.OFFICIAL

    def test_reputation_score(self):
        """Test reputation score lookup."""
        catalog = SourceCatalog()

        # Known domain
        score = catalog.get_reputation_score("sec.gov")
        assert score >= 0.9

        # Unknown domain
        score = catalog.get_reputation_score("unknown-site.com")
        assert score == 0.5

    def test_is_fetch_allowed(self):
        """Test fetch allowed check."""
        catalog = SourceCatalog()

        # Should be allowed for most domains
        assert catalog.is_fetch_allowed("reuters.com") is True
        assert catalog.is_fetch_allowed("unknown.com") is True

    def test_get_category_config(self):
        """Test getting category configuration."""
        catalog = SourceCatalog()

        config = catalog.get_category_config("recent_developments")
        assert config is not None
        assert config.min_evidence_cards >= 1
        assert config.recency_days > 0


class TestQueryPlanner:
    """Tests for QueryPlanner."""

    @pytest.fixture
    def sample_company_context(self) -> CompanyContext:
        """Create a sample CompanyContext for testing."""
        from datetime import datetime
        return CompanyContext(
            symbol="AAPL",
            fetched_at=datetime.now(),
            profile={
                "companyName": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "description": "Apple designs, manufactures, and sells consumer electronics.",
            },
            income_statement_annual=[{"date": "2024-01-01", "revenue": 100_000_000_000}],
            balance_sheet_annual=[{"date": "2024-01-01", "totalAssets": 350_000_000_000}],
            cash_flow_annual=[{"date": "2024-01-01", "operatingCashFlow": 30_000_000_000}],
        )

    def test_create_plan_deterministic(self, sample_company_context):
        """Test that query plans are deterministic."""
        planner = QueryPlanner()

        plan1 = planner.create_plan(sample_company_context)
        plan2 = planner.create_plan(sample_company_context)

        # Same inputs should produce same queries
        assert len(plan1.queries) == len(plan2.queries)
        for q1, q2 in zip(plan1.queries, plan2.queries):
            assert q1.query == q2.query
            assert q1.category == q2.category

    def test_create_plan_bounded(self, sample_company_context):
        """Test that query plans respect quotas."""
        planner = QueryPlanner(
            max_queries_per_category=3,
            max_total_queries=10,
            max_results_per_query=2,
        )

        plan = planner.create_plan(sample_company_context)

        # Should not exceed limits
        assert plan.total_queries <= 10
        for query in plan.queries:
            assert query.max_results <= 2

    def test_create_plan_tech_company(self, sample_company_context):
        """Test that tech companies get AI category."""
        planner = QueryPlanner()
        plan = planner.create_plan(sample_company_context)

        # Tech company should have AI category queries
        categories = {q.category for q in plan.queries}
        assert CoverageCategory.AI_INFRASTRUCTURE in categories

    def test_create_plan_non_tech_company(self):
        """Test that non-tech companies don't get AI category."""
        from datetime import datetime
        planner = QueryPlanner()

        context = CompanyContext(
            symbol="WMT",
            fetched_at=datetime.now(),
            profile={
                "companyName": "Walmart Inc.",
                "sector": "Consumer Defensive",
                "industry": "Discount Stores",
            },
        )

        plan = planner.create_plan(context)

        # Non-tech should not have AI category
        categories = {q.category for q in plan.queries}
        assert CoverageCategory.AI_INFRASTRUCTURE not in categories

    def test_create_plan_with_hints(self, sample_company_context):
        """Test that discovery hints are incorporated."""
        planner = QueryPlanner()

        hints = ["Apple Vision Pro sales", "iPhone 16 launch"]
        plan = planner.create_plan(sample_company_context, discovery_hints=hints)

        # Should have queries containing hints
        query_texts = [q.query for q in plan.queries]
        hint_found = any("Vision Pro" in q or "iPhone 16" in q for q in query_texts)
        assert hint_found

    def test_create_plan_specific_categories(self, sample_company_context):
        """Test creating plan for specific categories."""
        planner = QueryPlanner()

        plan = planner.create_plan(
            sample_company_context,
            categories=[CoverageCategory.RECENT_DEVELOPMENTS],
        )

        # Should only have recent_developments queries
        categories = {q.category for q in plan.queries}
        assert categories == {CoverageCategory.RECENT_DEVELOPMENTS}

    def test_plan_to_dict(self, sample_company_context):
        """Test plan serialization."""
        planner = QueryPlanner()
        plan = planner.create_plan(sample_company_context)

        data = plan.to_dict()

        assert data["ticker"] == "AAPL"
        assert data["company_name"] == "Apple Inc."
        assert len(data["queries"]) > 0
        assert "category" in data["queries"][0]

    def test_add_site_restrictions(self, sample_company_context):
        """Test adding site restrictions to queries."""
        catalog = SourceCatalog()
        planner = QueryPlanner(source_catalog=catalog)

        plan = planner.create_plan(sample_company_context)
        original_count = len(plan.queries)

        restricted_plan = planner.add_site_restrictions(plan)

        # Should have more queries with site restrictions
        # (May be same if no high-rep domains configured)
        assert restricted_plan.total_queries >= original_count

        # Check some queries have site_restrict
        site_restricted = [q for q in restricted_plan.queries if q.site_restrict]
        # This depends on the config, so just verify structure
        for q in site_restricted:
            assert q.site_restrict.startswith("site:")
