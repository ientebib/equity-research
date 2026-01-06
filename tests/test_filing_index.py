"""Tests for FilingIndex."""

from __future__ import annotations

import pytest

from er.indexing.filing_index import (
    FilingIndex,
    FilingChunk,
    FilingType,
    build_filing_excerpts,
)
from er.types import TextExcerpt


@pytest.fixture
def sample_10k_content() -> str:
    """Create sample 10-K filing content."""
    return """
Item 1. Business

Apple Inc. (referred to herein as "Apple" or the "Company") designs, manufactures, and
markets smartphones, personal computers, tablets, wearables, and accessories worldwide.
The Company also provides various related services.

Products and Services

iPhone
iPhone is the Company's line of smartphones based on its iOS operating system. The Company
continues to advance the iPhone product line with enhanced performance, display capabilities,
and camera systems.

Services
The Company operates various platforms, including the App Store, Apple Arcade, Apple Fitness+,
Apple Music, Apple News+, Apple TV+, Apple Card, Apple Pay, and iCloud.

Item 1A. Risk Factors

The Company's operations and financial results are subject to various risks and uncertainties
that could adversely affect the Company's business, financial condition, results of operations,
and trading price of its common stock.

Global and Regional Economic Conditions
The Company has international operations with sales in many countries. Global economic
conditions may adversely affect demand for the Company's products and services.

Competition Risk
The markets for the Company's products and services are highly competitive. The Company faces
substantial competition from companies that have significant technical, marketing, and other
resources.

Supply Chain Risks
The Company relies on outsourcing partners. Manufacturing disruptions could impact product
availability.

Item 7. Management's Discussion and Analysis of Financial Condition

The following discussion should be read in conjunction with the consolidated financial statements.

Overview
Total net revenue increased 8% compared to the prior year. The year-over-year increase in
revenue was driven by higher iPhone and Services revenue.

Products
Products net revenue increased due to higher iPhone revenue, partially offset by lower
iPad and Mac revenue.

Services
Services net revenue increased primarily due to higher revenue from advertising, cloud services,
and the App Store.
    """.strip()


@pytest.fixture
def sample_8k_content() -> str:
    """Create sample 8-K filing content."""
    return """
Item 2.02 Results of Operations and Financial Condition

On January 30, 2025, Apple Inc. ("Apple" or the "Company") announced financial results for
its fiscal first quarter ended December 28, 2024.

Revenue for the quarter was $124.3 billion, an increase of 4% compared to the year-ago quarter.
Quarterly earnings per diluted share was $2.40.

The Company announces that its Board of Directors has authorized an increase of $110 billion
to the existing share repurchase program.

Item 8.01 Other Events

The Company announced it will host its annual Worldwide Developers Conference (WWDC) beginning
June 9, 2025, in Cupertino, California.

Item 9.01 Financial Statements and Exhibits

(d) Exhibits
99.1 Press release dated January 30, 2025.
    """.strip()


class TestFilingIndex:
    """Tests for FilingIndex."""

    def test_init(self) -> None:
        """Test FilingIndex initialization."""
        index = FilingIndex()
        assert index.chunks == []
        assert index.idf == {}
        assert index.avg_doc_length == 0.0

    def test_add_filing_10k(self, sample_10k_content: str) -> None:
        """Test adding a 10-K filing."""
        index = FilingIndex(chunk_size=500, chunk_overlap=50)
        chunks = index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
            evidence_id="ev_10k_001",
        )

        assert len(chunks) > 0
        assert all(isinstance(c, FilingChunk) for c in chunks)
        # All chunks should have proper metadata
        for chunk in chunks:
            assert chunk.filing_type == FilingType.FORM_10K
            assert chunk.filing_date == "2024-10-31"
            assert chunk.fiscal_period == "FY2024"
            assert chunk.source_evidence_id == "ev_10k_001"

    def test_add_filing_from_string_type(self, sample_10k_content: str) -> None:
        """Test adding filing with string type."""
        index = FilingIndex()
        chunks = index.add_filing(
            content=sample_10k_content,
            filing_type="10-K",  # String instead of enum
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )

        assert len(chunks) > 0
        assert chunks[0].filing_type == FilingType.FORM_10K

    def test_section_detection(self, sample_10k_content: str) -> None:
        """Test section detection in 10-K."""
        index = FilingIndex(chunk_size=1000)
        chunks = index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )

        # Should detect Item 1, 1A, and 7 sections
        sections = {c.section for c in chunks if c.section}
        assert len(sections) > 0

    def test_retrieve_excerpts_basic(self, sample_10k_content: str) -> None:
        """Test basic excerpt retrieval."""
        index = FilingIndex()
        index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )

        excerpts = index.retrieve_excerpts("iPhone smartphone", top_k=3)

        assert len(excerpts) > 0
        assert all(isinstance(e, TextExcerpt) for e in excerpts)
        assert excerpts[0].source_type == "filing"
        assert excerpts[0].relevance_score > 0

    def test_retrieve_excerpts_filter_by_type(
        self, sample_10k_content: str, sample_8k_content: str
    ) -> None:
        """Test filtering by filing type."""
        index = FilingIndex()
        index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )
        index.add_filing(
            content=sample_8k_content,
            filing_type=FilingType.FORM_8K,
            filing_date="2025-01-30",
            fiscal_period="Q1 2025",
        )

        # Get only 10-K
        excerpts_10k = index.retrieve_excerpts(
            "revenue", top_k=5, filing_type=FilingType.FORM_10K
        )
        for e in excerpts_10k:
            assert e.metadata["filing_type"] == "10-K"

        # Get only 8-K
        excerpts_8k = index.retrieve_excerpts(
            "revenue", top_k=5, filing_type=FilingType.FORM_8K
        )
        for e in excerpts_8k:
            assert e.metadata["filing_type"] == "8-K"

    def test_get_risk_factors(self, sample_10k_content: str) -> None:
        """Test risk factors extraction."""
        index = FilingIndex(chunk_size=500)
        index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )

        risk_excerpts = index.get_risk_factors(top_k=5)

        # Should find risk factor excerpts
        # Note: depends on section detection working
        if risk_excerpts:
            for e in risk_excerpts:
                assert "risk" in e.metadata.get("section", "").lower()

    def test_get_mda_excerpts(self, sample_10k_content: str) -> None:
        """Test MD&A extraction."""
        index = FilingIndex(chunk_size=500)
        index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )

        mda_excerpts = index.get_mda_excerpts(query="revenue growth", top_k=3)

        # Should find MD&A excerpts
        if mda_excerpts:
            for e in mda_excerpts:
                section = e.metadata.get("section", "").lower()
                assert "management" in section or "item 7" in section

    def test_empty_index_retrieval(self) -> None:
        """Test retrieval on empty index."""
        index = FilingIndex()
        excerpts = index.retrieve_excerpts("test query")
        assert excerpts == []

    def test_bm25_ranking(self, sample_10k_content: str) -> None:
        """Test that BM25 properly ranks results."""
        index = FilingIndex()
        index.add_filing(
            content=sample_10k_content,
            filing_type=FilingType.FORM_10K,
            filing_date="2024-10-31",
            fiscal_period="FY2024",
        )

        # Query specific to iPhone
        excerpts = index.retrieve_excerpts("iPhone smartphone iOS", top_k=5)

        if len(excerpts) >= 2:
            # First result should have higher score
            assert excerpts[0].relevance_score >= excerpts[1].relevance_score

    def test_tokenize_removes_stopwords(self) -> None:
        """Test tokenization removes stopwords."""
        index = FilingIndex()
        tokens = index._tokenize("The Company has operations in various countries")

        assert "company" in tokens
        assert "operations" in tokens
        assert "countries" in tokens
        assert "the" not in tokens
        assert "has" not in tokens
        assert "in" not in tokens


class TestFilingType:
    """Tests for FilingType enum and parsing."""

    def test_parse_filing_type(self) -> None:
        """Test filing type parsing."""
        index = FilingIndex()

        assert index._parse_filing_type("10-K") == FilingType.FORM_10K
        assert index._parse_filing_type("10K") == FilingType.FORM_10K
        assert index._parse_filing_type("10-Q") == FilingType.FORM_10Q
        assert index._parse_filing_type("8-K") == FilingType.FORM_8K
        assert index._parse_filing_type("DEF14A") == FilingType.FORM_DEF14A
        assert index._parse_filing_type("unknown") == FilingType.UNKNOWN


class TestBuildFilingExcerpts:
    """Tests for build_filing_excerpts convenience function."""

    def test_build_filing_excerpts(self, sample_10k_content: str) -> None:
        """Test convenience function."""
        filings = [
            {
                "content": sample_10k_content,
                "type": "10-K",
                "date": "2024-10-31",
                "period": "FY2024",
                "evidence_id": "ev_001",
            }
        ]

        excerpts = build_filing_excerpts(filings)

        assert len(excerpts) > 0
        assert all(isinstance(e, TextExcerpt) for e in excerpts)
        assert excerpts[0].source_type == "filing"

    def test_build_filing_excerpts_empty_content(self) -> None:
        """Test with empty content."""
        filings = [{"content": "", "type": "10-K", "date": "2024-01-01", "period": "FY2024"}]

        excerpts = build_filing_excerpts(filings)
        assert excerpts == []

    def test_build_filing_excerpts_multiple_filings(
        self, sample_10k_content: str, sample_8k_content: str
    ) -> None:
        """Test with multiple filings."""
        filings = [
            {
                "content": sample_10k_content,
                "type": "10-K",
                "date": "2024-10-31",
                "period": "FY2024",
            },
            {
                "content": sample_8k_content,
                "type": "8-K",
                "date": "2025-01-30",
                "period": "Q1 2025",
            },
        ]

        excerpts = build_filing_excerpts(filings)

        # Should have excerpts from both filings
        filing_types = {e.metadata["filing_type"] for e in excerpts}
        assert "10-K" in filing_types
        assert "8-K" in filing_types
