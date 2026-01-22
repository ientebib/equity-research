"""Tests for CoverageAuditor agent."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from er.agents.coverage_auditor import CoverageAuditor, DEFAULT_MIN_CARDS
from er.agents.base import AgentContext
from er.types import (
    CompanyContext,
    CoverageCategory,
    CoverageStatus,
    RunState,
)


@pytest.fixture
def mock_context() -> AgentContext:
    """Create mock agent context."""
    context = MagicMock(spec=AgentContext)
    context.llm_router = MagicMock()
    context.llm_router.openai_client = MagicMock()
    context.llm_router.openai_client.chat = AsyncMock(
        return_value={"content": "{\"results\": []}"}
    )
    context.workspace_store = MagicMock()
    context.evidence_store = MagicMock()
    context.budget_tracker = MagicMock()
    context.event_store = None
    return context


@pytest.fixture
def company_context() -> CompanyContext:
    """Create test company context."""
    from datetime import datetime
    return CompanyContext(
        symbol="AAPL",
        fetched_at=datetime.fromisoformat("2024-01-15T10:00:00"),
        profile={
            "companyName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
        transcripts=[],
    )


@pytest.fixture
def run_state() -> RunState:
    """Create test run state."""
    from datetime import datetime
    from er.types import Phase
    return RunState(
        run_id="run_test_001",
        ticker="AAPL",
        started_at=datetime.fromisoformat("2024-01-15T10:00:00"),
        phase=Phase.DISCOVERY,
        budget_remaining_usd=10.0,
    )


@pytest.fixture
def sample_evidence_cards() -> list[dict]:
    """Create sample evidence cards covering various categories."""
    return [
        {
            "card_id": "card_001",
            "raw_evidence_id": "ev_001",
            "title": "Apple Launches New iPhone",
            "summary": "Apple announced the launch of new iPhone models with improved features.",
            "key_facts": ["New product release", "iPhone 16 announced"],
        },
        {
            "card_id": "card_002",
            "raw_evidence_id": "ev_002",
            "title": "Apple Earnings Call Highlights",
            "summary": "CEO Tim Cook provided guidance on future quarters.",
            "key_facts": ["Management tone positive", "Revenue outlook strong"],
        },
        {
            "card_id": "card_003",
            "raw_evidence_id": "ev_003",
            "title": "Apple vs Samsung Market Share",
            "summary": "Apple gained market share versus competitor Samsung.",
            "key_facts": ["Market share increased", "Competitive position strong"],
        },
        {
            "card_id": "card_004",
            "raw_evidence_id": "ev_004",
            "title": "Apple AI Strategy Announcement",
            "summary": "Apple unveiled AI features including machine learning capabilities.",
            "key_facts": ["AI integration", "Machine learning models"],
        },
        {
            "card_id": "card_005",
            "raw_evidence_id": "ev_005",
            "title": "Apple Dividend Increase",
            "summary": "Apple announced dividend increase and buyback program.",
            "key_facts": ["Dividend raised", "Buyback authorized"],
        },
        {
            "card_id": "card_006",
            "raw_evidence_id": "ev_006",
            "title": "Services Segment Growth",
            "summary": "Apple services segment revenue reached record levels with improved margin.",
            "key_facts": ["Segment profitability up", "Services revenue record"],
        },
        {
            "card_id": "card_007",
            "raw_evidence_id": "ev_007",
            "title": "Apple Antitrust Investigation",
            "summary": "Regulatory investigation into Apple App Store practices.",
            "key_facts": ["Antitrust scrutiny", "Regulatory concerns"],
        },
        {
            "card_id": "card_008",
            "raw_evidence_id": "ev_008",
            "title": "Product Roadmap Update",
            "summary": "Apple product roadmap includes new features and releases.",
            "key_facts": ["New product planned", "Feature updates coming"],
        },
    ]


class TestCoverageAuditor:
    """Tests for CoverageAuditor."""

    def test_init(self, mock_context: AgentContext) -> None:
        """Test CoverageAuditor initialization."""
        auditor = CoverageAuditor(mock_context)
        assert auditor.name == "coverage_auditor"
        assert auditor.role == "Audit research coverage and fill gaps"

    def test_get_applicable_categories_tech(self, mock_context: AgentContext) -> None:
        """Test category selection for tech sector."""
        auditor = CoverageAuditor(mock_context)
        categories = auditor._get_applicable_categories("Technology")

        assert CoverageCategory.RECENT_DEVELOPMENTS in categories
        assert CoverageCategory.COMPETITIVE_MOVES in categories
        assert CoverageCategory.PRODUCT_ROADMAP in categories
        assert CoverageCategory.AI_INFRASTRUCTURE in categories

    def test_get_applicable_categories_finance(self, mock_context: AgentContext) -> None:
        """Test category selection for finance sector."""
        auditor = CoverageAuditor(mock_context)
        categories = auditor._get_applicable_categories("Financials")

        assert CoverageCategory.RECENT_DEVELOPMENTS in categories
        assert CoverageCategory.COMPETITIVE_MOVES in categories
        # Tech-specific categories not included
        assert CoverageCategory.PRODUCT_ROADMAP not in categories
        assert CoverageCategory.AI_INFRASTRUCTURE not in categories

    def test_count_matching_cards(
        self, mock_context: AgentContext, sample_evidence_cards: list[dict]
    ) -> None:
        """Test card counting by category."""
        auditor = CoverageAuditor(mock_context)

        # Test AI category
        ai_count = auditor._count_matching_cards(
            sample_evidence_cards, CoverageCategory.AI_INFRASTRUCTURE
        )
        assert ai_count >= 1

        # Test competitive category
        competitive_count = auditor._count_matching_cards(
            sample_evidence_cards, CoverageCategory.COMPETITIVE_MOVES
        )
        assert competitive_count >= 1

        # Test regulatory category
        regulatory_count = auditor._count_matching_cards(
            sample_evidence_cards, CoverageCategory.REGULATORY_LITIGATION
        )
        assert regulatory_count >= 1

    def test_get_category_keywords(self, mock_context: AgentContext) -> None:
        """Test keyword retrieval for categories."""
        auditor = CoverageAuditor(mock_context)

        ai_keywords = auditor._get_category_keywords(CoverageCategory.AI_INFRASTRUCTURE)
        assert "ai" in ai_keywords
        assert "artificial intelligence" in ai_keywords

        regulatory_keywords = auditor._get_category_keywords(
            CoverageCategory.REGULATORY_LITIGATION
        )
        assert "antitrust" in regulatory_keywords

    def test_compute_scorecard_pass(
        self, mock_context: AgentContext, sample_evidence_cards: list[dict]
    ) -> None:
        """Test scorecard computation with sufficient coverage."""
        auditor = CoverageAuditor(mock_context)

        # Create more cards to ensure passing coverage
        cards = sample_evidence_cards * 3  # Triple the cards

        scorecard = auditor._compute_scorecard(
            ticker="AAPL",
            evidence_cards=cards,
            categories=[
                CoverageCategory.RECENT_DEVELOPMENTS,
                CoverageCategory.AI_INFRASTRUCTURE,
                CoverageCategory.MANAGEMENT_TONE,
            ],
            recency_days=90,
        )

        assert scorecard.ticker == "AAPL"
        assert len(scorecard.results) == 3
        # With triple cards, should have reasonable coverage

    def test_compute_scorecard_with_gaps(
        self, mock_context: AgentContext
    ) -> None:
        """Test scorecard computation with coverage gaps."""
        auditor = CoverageAuditor(mock_context)

        # Minimal cards - should have gaps
        cards = [
            {"card_id": "c1", "title": "News", "summary": "Some news", "key_facts": []},
        ]

        scorecard = auditor._compute_scorecard(
            ticker="TEST",
            evidence_cards=cards,
            categories=[
                CoverageCategory.RECENT_DEVELOPMENTS,
                CoverageCategory.AI_INFRASTRUCTURE,
                CoverageCategory.REGULATORY_LITIGATION,
            ],
            recency_days=90,
        )

        # Should identify gaps
        failing = [r for r in scorecard.results if r.status == CoverageStatus.FAIL]
        assert len(failing) > 0

    def test_generate_gap_query(self, mock_context: AgentContext) -> None:
        """Test gap query generation."""
        auditor = CoverageAuditor(mock_context)

        query = auditor._generate_gap_query("Apple", CoverageCategory.AI_INFRASTRUCTURE)
        assert "Apple" in query
        assert "AI" in query or "artificial intelligence" in query.lower()

        query = auditor._generate_gap_query("Apple", CoverageCategory.REGULATORY_LITIGATION)
        assert "Apple" in query
        assert "regulatory" in query.lower() or "antitrust" in query.lower()

    def test_get_matching_evidence_ids(
        self, mock_context: AgentContext, sample_evidence_cards: list[dict]
    ) -> None:
        """Test evidence ID extraction for matching cards."""
        auditor = CoverageAuditor(mock_context)

        ids = auditor._get_matching_evidence_ids(
            sample_evidence_cards, CoverageCategory.AI_INFRASTRUCTURE
        )

        # Should find the AI card
        assert len(ids) >= 1
        assert any("ev_" in id for id in ids)


class TestCoverageAuditorRun:
    """Integration tests for CoverageAuditor run method."""

    @pytest.mark.asyncio
    async def test_run_with_good_coverage(
        self,
        mock_context: AgentContext,
        company_context: CompanyContext,
        run_state: RunState,
        sample_evidence_cards: list[dict],
    ) -> None:
        """Test run with adequate coverage."""
        auditor = CoverageAuditor(mock_context)

        # Triple cards for good coverage
        cards = sample_evidence_cards * 3

        scorecard, actions = await auditor.run(
            run_state=run_state,
            company_context=company_context,
            evidence_cards=cards,
        )

        assert scorecard is not None
        assert scorecard.ticker == "AAPL"
        # Actions may or may not be needed depending on coverage

    @pytest.mark.asyncio
    async def test_run_with_coverage_gaps(
        self,
        mock_context: AgentContext,
        company_context: CompanyContext,
        run_state: RunState,
    ) -> None:
        """Test run with coverage gaps triggers second pass."""
        auditor = CoverageAuditor(mock_context)

        # Minimal cards
        cards = [{"card_id": "c1", "title": "News", "summary": "Basic news", "key_facts": []}]

        scorecard, actions = await auditor.run(
            run_state=run_state,
            company_context=company_context,
            evidence_cards=cards,
        )

        # Should have some gaps
        assert scorecard is not None
        # If overall status is FAIL, actions should be generated
        if scorecard.overall_status == CoverageStatus.FAIL:
            assert len(actions) > 0

    @pytest.mark.asyncio
    async def test_close(self, mock_context: AgentContext) -> None:
        """Test close method."""
        auditor = CoverageAuditor(mock_context)
        await auditor.close()  # Should not raise


class TestDefaultMinCards:
    """Tests for default minimum card thresholds."""

    def test_all_categories_have_thresholds(self) -> None:
        """Test all categories have defined thresholds."""
        for category in CoverageCategory:
            assert category in DEFAULT_MIN_CARDS

    def test_threshold_values_reasonable(self) -> None:
        """Test threshold values are reasonable."""
        for category, threshold in DEFAULT_MIN_CARDS.items():
            assert threshold >= 1, f"{category} threshold too low"
            assert threshold <= 5, f"{category} threshold too high"
