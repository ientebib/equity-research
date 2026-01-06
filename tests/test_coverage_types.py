"""Tests for coverage, recency, claim, and valuation types."""

import json
import pytest

from er.types import (
    # Coverage types
    CoverageCategory,
    CoverageStatus,
    CoverageCategoryResult,
    CoverageScorecard,
    CoverageAction,
    # Recency types
    RecencyFinding,
    RecencyGuardOutput,
    # Claim types
    ClaimType,
    EntailmentStatus,
    Claim,
    ClaimGraph,
    EntailmentResult,
    EntailmentReport,
    # Excerpt types
    TextExcerpt,
    # Valuation types
    ProjectionInputs,
    WACCInputs,
    DCFResult,
    ReverseDCFResult,
    ValuationSummary,
)


class TestCoverageTypes:
    """Test coverage-related types."""

    def test_coverage_category_result_roundtrip(self):
        """Test CoverageCategoryResult serialization roundtrip."""
        result = CoverageCategoryResult(
            category=CoverageCategory.RECENT_DEVELOPMENTS,
            required_min_cards=3,
            found_cards=5,
            queries_run=["AAPL news 2024", "Apple product launch"],
            top_evidence_ids=["ev_123", "ev_456"],
            status=CoverageStatus.PASS,
            notes="Good coverage",
        )

        data = result.to_dict()
        assert data["category"] == "recent_developments"
        assert data["status"] == "pass"

        restored = CoverageCategoryResult.from_dict(data)
        assert restored.category == CoverageCategory.RECENT_DEVELOPMENTS
        assert restored.found_cards == 5
        assert restored.status == CoverageStatus.PASS

    def test_coverage_scorecard_roundtrip(self):
        """Test CoverageScorecard serialization roundtrip."""
        results = [
            CoverageCategoryResult(
                category=CoverageCategory.RECENT_DEVELOPMENTS,
                required_min_cards=3,
                found_cards=5,
                queries_run=["q1"],
                top_evidence_ids=["ev_1"],
                status=CoverageStatus.PASS,
            ),
            CoverageCategoryResult(
                category=CoverageCategory.COMPETITIVE_MOVES,
                required_min_cards=2,
                found_cards=1,
                queries_run=["q2"],
                top_evidence_ids=["ev_2"],
                status=CoverageStatus.FAIL,
            ),
        ]

        scorecard = CoverageScorecard(
            ticker="AAPL",
            as_of_date="2024-01-15",
            recency_days=90,
            results=results,
            overall_status=CoverageStatus.MARGINAL,
            pass_rate=0.5,
            total_evidence_cards=6,
            total_queries_run=2,
        )

        data = scorecard.to_dict()
        json_str = json.dumps(data)  # Ensure JSON serializable
        assert "AAPL" in json_str

        restored = CoverageScorecard.from_dict(data)
        assert restored.ticker == "AAPL"
        assert len(restored.results) == 2
        assert restored.overall_status == CoverageStatus.MARGINAL

    def test_coverage_action_roundtrip(self):
        """Test CoverageAction serialization roundtrip."""
        action = CoverageAction(
            category=CoverageCategory.REGULATORY_LITIGATION,
            query="AAPL DOJ antitrust",
            urls_fetched=["https://example.com/article"],
            evidence_ids=["ev_789"],
            success=True,
            notes="Found relevant article",
        )

        data = action.to_dict()
        restored = CoverageAction.from_dict(data)
        assert restored.category == CoverageCategory.REGULATORY_LITIGATION
        assert restored.success is True


class TestRecencyTypes:
    """Test recency-related types."""

    def test_recency_finding_roundtrip(self):
        """Test RecencyFinding serialization roundtrip."""
        finding = RecencyFinding(
            hypothesis="Apple may have launched new M4 chip",
            query="Apple M4 chip launch 2024",
            finding="M4 launched in November 2024",
            status="confirmed",
            evidence_ids=["ev_123"],
            confidence=0.9,
        )

        data = finding.to_dict()
        restored = RecencyFinding.from_dict(data)
        assert restored.hypothesis == finding.hypothesis
        assert restored.status == "confirmed"
        assert restored.confidence == 0.9

    def test_recency_guard_output_roundtrip(self):
        """Test RecencyGuardOutput serialization roundtrip."""
        findings = [
            RecencyFinding(
                hypothesis="Test hypothesis",
                query="Test query",
                finding="Test finding",
                status="confirmed",
            )
        ]

        output = RecencyGuardOutput(
            ticker="AAPL",
            as_of_date="2024-01-15",
            outdated_priors_checked=["prior1", "prior2"],
            findings=findings,
            forced_queries=["forced query 1"],
            evidence_ids=["ev_1", "ev_2"],
        )

        data = output.to_dict()
        json_str = json.dumps(data)
        assert "AAPL" in json_str

        restored = RecencyGuardOutput.from_dict(data)
        assert restored.ticker == "AAPL"
        assert len(restored.findings) == 1


class TestClaimTypes:
    """Test claim and entailment types."""

    def test_claim_roundtrip(self):
        """Test Claim serialization roundtrip."""
        claim = Claim(
            claim_id="claim_001",
            text="Apple's revenue grew 15% YoY",
            claim_type=ClaimType.FACT,
            section="Financial Overview",
            cited_evidence_ids=["ev_123"],
            linked_fact_ids=["fact_001"],
            confidence=0.85,
        )

        data = claim.to_dict()
        assert data["claim_type"] == "fact"

        restored = Claim.from_dict(data)
        assert restored.claim_type == ClaimType.FACT
        assert restored.confidence == 0.85

    def test_claim_graph_roundtrip(self):
        """Test ClaimGraph serialization roundtrip."""
        claims = [
            Claim(
                claim_id="claim_001",
                text="Test claim",
                claim_type=ClaimType.INFERENCE,
                section="Analysis",
            )
        ]

        graph = ClaimGraph(
            ticker="AAPL",
            source="synthesis",
            claims=claims,
            total_claims=1,
            cited_claims=1,
            uncited_claims=0,
        )

        data = graph.to_dict()
        restored = ClaimGraph.from_dict(data)
        assert restored.ticker == "AAPL"
        assert len(restored.claims) == 1

    def test_entailment_result_roundtrip(self):
        """Test EntailmentResult serialization roundtrip."""
        result = EntailmentResult(
            claim_id="claim_001",
            status=EntailmentStatus.SUPPORTED,
            rationale="Evidence directly states this fact",
            evidence_snippets=["Revenue increased 15%..."],
            confidence=0.9,
        )

        data = result.to_dict()
        assert data["status"] == "supported"

        restored = EntailmentResult.from_dict(data)
        assert restored.status == EntailmentStatus.SUPPORTED

    def test_entailment_report_roundtrip(self):
        """Test EntailmentReport serialization roundtrip."""
        results = [
            EntailmentResult(
                claim_id="claim_001",
                status=EntailmentStatus.SUPPORTED,
                rationale="Good evidence",
            ),
            EntailmentResult(
                claim_id="claim_002",
                status=EntailmentStatus.WEAK,
                rationale="Partial support",
            ),
        ]

        report = EntailmentReport(
            ticker="AAPL",
            total_claims=2,
            supported_count=1,
            weak_count=1,
            unsupported_count=0,
            contradicted_count=0,
            results=results,
            overall_score=0.75,
        )

        data = report.to_dict()
        json_str = json.dumps(data)
        assert "overall_score" in json_str

        restored = EntailmentReport.from_dict(data)
        assert restored.supported_count == 1
        assert len(restored.results) == 2


class TestExcerptTypes:
    """Test text excerpt types."""

    def test_text_excerpt_roundtrip(self):
        """Test TextExcerpt serialization roundtrip."""
        excerpt = TextExcerpt(
            excerpt_id="exc_001",
            source_evidence_id="ev_transcript_001",
            source_type="transcript",
            text="We expect continued growth in services...",
            start_offset=1500,
            end_offset=2000,
            metadata={"speaker": "Tim Cook", "date": "2024-01-25"},
            relevance_score=0.85,
        )

        data = excerpt.to_dict()
        assert data["source_type"] == "transcript"

        restored = TextExcerpt.from_dict(data)
        assert restored.source_type == "transcript"
        assert restored.metadata["speaker"] == "Tim Cook"


class TestValuationTypes:
    """Test valuation-related types."""

    def test_projection_inputs_serialization(self):
        """Test ProjectionInputs serialization."""
        inputs = ProjectionInputs(
            ticker="AAPL",
            base_year=2024,
            projection_years=5,
            revenue_growth_rates=[0.08, 0.07, 0.06, 0.05, 0.04],
            gross_margin=0.44,
            operating_margin=0.30,
            tax_rate=0.21,
            capex_to_revenue=0.05,
            nwc_to_revenue=0.10,
            depreciation_to_capex=0.80,
            terminal_growth=0.025,
            assumptions_source="analyst consensus",
        )

        data = inputs.to_dict()
        assert data["ticker"] == "AAPL"
        assert len(data["revenue_growth_rates"]) == 5

    def test_wacc_inputs_serialization(self):
        """Test WACCInputs serialization."""
        inputs = WACCInputs(
            risk_free_rate=0.045,
            equity_risk_premium=0.05,
            beta=1.2,
            cost_of_debt=0.05,
            tax_rate=0.21,
            debt_to_capital=0.15,
            size_premium=0.0,
            industry_adjustment=0.0,
        )

        data = inputs.to_dict()
        assert data["beta"] == 1.2

    def test_dcf_result_serialization(self):
        """Test DCFResult serialization."""
        result = DCFResult(
            enterprise_value=3_000_000_000_000,
            equity_value=2_900_000_000_000,
            per_share_value=185.50,
            wacc=0.09,
            terminal_value=2_500_000_000_000,
            pv_fcf=500_000_000_000,
            pv_terminal=2_000_000_000_000,
            shares_outstanding=15_600_000_000,
            net_debt=100_000_000_000,
        )

        data = result.to_dict()
        assert data["per_share_value"] == 185.50

    def test_reverse_dcf_result_serialization(self):
        """Test ReverseDCFResult serialization."""
        result = ReverseDCFResult(
            current_price=175.00,
            implied_growth_rate=0.07,
            implied_terminal_growth=0.03,
            implied_margin=0.28,
            sensitivity_to_growth=12.5,
            sensitivity_to_margin=8.3,
        )

        data = result.to_dict()
        assert data["current_price"] == 175.00

    def test_valuation_summary_serialization(self):
        """Test ValuationSummary serialization."""
        reverse_dcf = ReverseDCFResult(
            current_price=175.00,
            implied_growth_rate=0.07,
            implied_terminal_growth=0.03,
            implied_margin=0.28,
            sensitivity_to_growth=12.5,
            sensitivity_to_margin=8.3,
        )

        summary = ValuationSummary(
            ticker="AAPL",
            as_of_date="2024-01-15",
            current_price=175.00,
            dcf_value=185.50,
            dcf_upside=0.06,
            reverse_dcf=reverse_dcf,
            sensitivity_range=(165.00, 205.00),
            comps_median=180.00,
            comps_range=(170.00, 195.00),
            sotp_value=None,
            key_assumptions=["8% revenue growth", "30% operating margin"],
            key_sensitivities=["WACC +/-1% = $15 impact"],
            valuation_view="fairly_valued",
        )

        data = summary.to_dict()
        json_str = json.dumps(data)
        assert "AAPL" in json_str
        assert "dcf_value" in json_str
        assert data["reverse_dcf"] is not None
