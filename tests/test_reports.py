"""Tests for report compilation."""

import pytest
from datetime import datetime

from er.reports.compiler import (
    ReportCompiler,
    CompiledReport,
    ReportSection,
    InvestmentView,
    Conviction,
    Citation,
    ReportClaim,
    SectionContent,
)
from er.types import ClaimType, VerificationStatus


class TestReportSection:
    """Tests for ReportSection enum."""

    def test_all_sections_defined(self):
        """Test all expected sections are defined."""
        assert ReportSection.EXECUTIVE_SUMMARY.value == "executive_summary"
        assert ReportSection.VALUATION.value == "valuation"
        assert ReportSection.RISKS.value == "risks"


class TestCitation:
    """Tests for Citation dataclass."""

    def test_citation_to_dict(self):
        """Test citation serialization."""
        citation = Citation(
            citation_id="[1]",
            source_type="10-K",
            source_date="2024-03-01",
            source_url="https://sec.gov/filing",
            excerpt="Revenue grew 15%",
        )

        d = citation.to_dict()

        assert d["citation_id"] == "[1]"
        assert d["source_type"] == "10-K"
        assert d["source_url"] == "https://sec.gov/filing"


class TestReportClaim:
    """Tests for ReportClaim dataclass."""

    def test_report_claim_to_dict(self):
        """Test report claim serialization."""
        claim = ReportClaim(
            text="Revenue increased 15%",
            claim_type=ClaimType.FACT,
            section=ReportSection.FINANCIALS,
            verification_status=VerificationStatus.VERIFIED,
            confidence=0.9,
        )

        d = claim.to_dict()

        assert d["text"] == "Revenue increased 15%"
        assert d["claim_type"] == "fact"
        assert d["section"] == "financial_analysis"
        assert d["confidence"] == 0.9


class TestSectionContent:
    """Tests for SectionContent dataclass."""

    def test_section_content_to_dict(self):
        """Test section content serialization."""
        section = SectionContent(
            section=ReportSection.EXECUTIVE_SUMMARY,
            title="Executive Summary",
            content="This is a test summary.",
            word_count=5,
        )

        d = section.to_dict()

        assert d["section"] == "executive_summary"
        assert d["title"] == "Executive Summary"
        assert d["word_count"] == 5


class TestCompiledReport:
    """Tests for CompiledReport dataclass."""

    @pytest.fixture
    def sample_report(self):
        """Create sample report."""
        return CompiledReport(
            ticker="AAPL",
            company_name="Apple Inc.",
            generated_at=datetime(2024, 1, 15, 10, 0, 0),
            investment_view=InvestmentView.BUY,
            conviction=Conviction.HIGH,
            target_price=200.0,
            current_price=180.0,
            sections=[
                SectionContent(
                    section=ReportSection.EXECUTIVE_SUMMARY,
                    title="Executive Summary",
                    content="Apple is a buy.",
                    word_count=4,
                ),
            ],
            total_claims=10,
            verified_claims=8,
            total_word_count=100,
        )

    def test_report_to_dict(self, sample_report):
        """Test report serialization."""
        d = sample_report.to_dict()

        assert d["ticker"] == "AAPL"
        assert d["investment_view"] == "BUY"
        assert d["conviction"] == "High"
        assert d["target_price"] == 200.0
        assert d["verification_rate"] == 0.8

    def test_get_section(self, sample_report):
        """Test getting section by type."""
        section = sample_report.get_section(ReportSection.EXECUTIVE_SUMMARY)

        assert section is not None
        assert section.title == "Executive Summary"

        missing = sample_report.get_section(ReportSection.VALUATION)
        assert missing is None

    def test_to_markdown(self, sample_report):
        """Test markdown export."""
        md = sample_report.to_markdown()

        assert "# AAPL Equity Research Report" in md
        assert "**Investment View:** BUY" in md
        assert "**Target Price:** $200.00" in md
        assert "## Executive Summary" in md


class TestReportCompiler:
    """Tests for ReportCompiler."""

    @pytest.fixture
    def compiler(self):
        """Create compiler instance."""
        return ReportCompiler()

    @pytest.fixture
    def sample_synthesis(self):
        """Sample synthesis text."""
        return """
# AAPL EQUITY RESEARCH REPORT

## EXECUTIVE SUMMARY
- Investment View: BUY
- Conviction: High

Apple continues to demonstrate strong performance.

## COMPANY OVERVIEW

Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide.

## SEGMENT ANALYSIS

### iPhone
The iPhone segment remains the largest revenue driver.

### Services
Services continues to grow at double-digit rates.

## FINANCIAL ANALYSIS

Revenue grew 10% year-over-year to $89 billion.
Operating margin improved to 30%.

## VALUATION

Based on our DCF analysis, we arrive at a target price of $200.

## RISKS

- Regulatory pressure in Europe
- Supply chain concentration in China
- Competition from Android manufacturers

## CATALYSTS

- AI integration announcements
- New product categories
- Emerging markets expansion

## RECOMMENDATION

We rate Apple a BUY with high conviction and a $200 price target.
"""

    def test_compile_extracts_view(self, compiler, sample_synthesis):
        """Test investment view extraction."""
        report = compiler.compile(
            synthesis_text=sample_synthesis,
            ticker="AAPL",
            company_name="Apple Inc.",
        )

        assert report.investment_view == InvestmentView.BUY

    def test_compile_extracts_conviction(self, compiler, sample_synthesis):
        """Test conviction extraction."""
        report = compiler.compile(
            synthesis_text=sample_synthesis,
            ticker="AAPL",
            company_name="Apple Inc.",
        )

        assert report.conviction == Conviction.HIGH

    def test_compile_extracts_target_price(self, compiler, sample_synthesis):
        """Test target price extraction."""
        report = compiler.compile(
            synthesis_text=sample_synthesis,
            ticker="AAPL",
            company_name="Apple Inc.",
        )

        assert report.target_price == 200.0

    def test_compile_extracts_sections(self, compiler, sample_synthesis):
        """Test section extraction."""
        report = compiler.compile(
            synthesis_text=sample_synthesis,
            ticker="AAPL",
            company_name="Apple Inc.",
        )

        assert len(report.sections) > 0

        section_types = [s.section for s in report.sections]
        assert ReportSection.EXECUTIVE_SUMMARY in section_types
        assert ReportSection.FINANCIALS in section_types
        assert ReportSection.RISKS in section_types

    def test_compile_calculates_word_count(self, compiler, sample_synthesis):
        """Test word count calculation."""
        report = compiler.compile(
            synthesis_text=sample_synthesis,
            ticker="AAPL",
            company_name="Apple Inc.",
        )

        assert report.total_word_count > 0

    def test_compile_with_current_price(self, compiler, sample_synthesis):
        """Test passing current price."""
        report = compiler.compile(
            synthesis_text=sample_synthesis,
            ticker="AAPL",
            company_name="Apple Inc.",
            current_price=180.0,
        )

        assert report.current_price == 180.0

    def test_extract_target_price_various_formats(self, compiler):
        """Test target price extraction from various formats."""
        texts = [
            ("Target price: $150", 150.0),
            ("Price target: $200.50", 200.5),
            ("PT: $175", 175.0),
            ("target price $1,250", 1250.0),
        ]

        for text, expected in texts:
            result = compiler._extract_target_price(text)
            assert result == expected, f"Failed for: {text}"

    def test_extract_investment_view_sell(self, compiler):
        """Test sell recommendation extraction."""
        text = "## Executive Summary\nWe recommend SELL due to declining fundamentals."

        view = compiler._extract_investment_view(text)

        assert view == InvestmentView.SELL

    def test_extract_investment_view_hold(self, compiler):
        """Test hold recommendation extraction."""
        text = "## Executive Summary\nWe maintain a HOLD rating."

        view = compiler._extract_investment_view(text)

        assert view == InvestmentView.HOLD

    def test_extract_conviction_low(self, compiler):
        """Test low conviction extraction."""
        text = "## Executive Summary\nLow conviction given uncertainty."

        conv = compiler._extract_conviction(text)

        assert conv == Conviction.LOW

    def test_extract_conviction_medium(self, compiler):
        """Test medium conviction extraction."""
        text = "## Executive Summary\nModerate confidence in our thesis."

        conv = compiler._extract_conviction(text)

        assert conv == Conviction.MEDIUM

    def test_compile_empty_synthesis(self, compiler):
        """Test handling of empty synthesis."""
        report = compiler.compile(
            synthesis_text="",
            ticker="TEST",
            company_name="Test Corp",
        )

        assert report.ticker == "TEST"
        assert report.investment_view == InvestmentView.HOLD  # Default
        assert report.conviction == Conviction.MEDIUM  # Default
