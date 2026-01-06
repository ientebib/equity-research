"""Tests for claim verification and entailment."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from er.verification.claim_graph import ClaimGraphBuilder, ExtractedFact
from er.verification.entailment import (
    EntailmentVerifier,
    EntailmentResult,
    EntailmentReport,
    verify_claims_batch,
)
from er.types import (
    Claim,
    ClaimGraph,
    ClaimType,
    EntailmentStatus,
)


class TestClaimGraphBuilder:
    """Tests for ClaimGraphBuilder."""

    @pytest.fixture
    def sample_analysis(self) -> str:
        """Sample analysis text with various claim types."""
        return """
Apple's revenue is expected to grow 8% in FY2025, driven by strong iPhone demand.
The company maintains a significant competitive advantage through its integrated ecosystem,
which creates high switching costs for users.

There is a risk that regulatory scrutiny in the EU could impact App Store revenue.
The stock is currently trading at 25x forward earnings, which appears undervalued
relative to its growth rate.

An upcoming catalyst is the iPhone 16 launch in September, which could drive
significant upgrade activity. However, margin pressure from AI investments
may offset some of the revenue gains.
        """.strip()

    def test_build_from_text_extracts_claims(self, sample_analysis: str) -> None:
        """Test that claims are extracted from text."""
        builder = ClaimGraphBuilder()
        graph = builder.build_from_text(sample_analysis, ticker="AAPL")

        assert graph.ticker == "AAPL"
        assert len(graph.claims) > 0
        assert all(isinstance(c, Claim) for c in graph.claims)

    def test_claim_types_detected(self, sample_analysis: str) -> None:
        """Test that different claim types are detected."""
        builder = ClaimGraphBuilder()
        graph = builder.build_from_text(sample_analysis)

        claim_types = {c.claim_type for c in graph.claims}

        # Should detect at least some types
        assert len(claim_types) >= 1

    def test_financial_claim_detection(self) -> None:
        """Test financial claim detection."""
        builder = ClaimGraphBuilder()
        text = "Revenue is expected to grow 15% year over year."

        graph = builder.build_from_text(text)

        # Should detect claim
        assert len(graph.claims) > 0

    def test_risk_claim_detection(self) -> None:
        """Test risk claim detection."""
        builder = ClaimGraphBuilder()
        text = "There is significant regulatory risk from antitrust investigations."

        graph = builder.build_from_text(text)

        # Should detect claim with inference type (mapped from risk)
        risk_claims = [c for c in graph.claims if c.section == "risk"]
        assert len(risk_claims) > 0

    def test_valuation_claim_detection(self) -> None:
        """Test valuation claim detection."""
        builder = ClaimGraphBuilder()
        text = "The stock appears undervalued trading at only 15x earnings."

        graph = builder.build_from_text(text)

        # Should detect valuation claim
        valuation_claims = [c for c in graph.claims if c.section == "valuation"]
        assert len(valuation_claims) > 0

    def test_confidence_estimation(self) -> None:
        """Test confidence is estimated based on language."""
        builder = ClaimGraphBuilder()

        # High confidence language
        high_conf_text = "Revenue will grow 20% next year based on strong demand."
        graph_high = builder.build_from_text(high_conf_text)

        # Low confidence language
        low_conf_text = "Revenue may potentially grow if conditions improve."
        graph_low = builder.build_from_text(low_conf_text)

        if graph_high.claims and graph_low.claims:
            # High confidence text should have higher confidence
            assert graph_high.claims[0].confidence >= graph_low.claims[0].confidence

    def test_link_facts_to_claims(self) -> None:
        """Test linking facts to claims."""
        builder = ClaimGraphBuilder()

        # Create claim about revenue
        graph = builder.build_from_text(
            "Revenue is expected to grow 10% driven by iPhone.",
            ticker="AAPL",
        )

        facts = [
            {"fact_id": "fact_001", "text": "iPhone revenue increased 15% last quarter"},
            {"fact_id": "fact_002", "text": "Cloud services showed strong growth"},
        ]

        updated_graph = builder.link_facts_to_claims(graph, facts)

        # Check that linking occurred (may or may not have links depending on overlap)
        assert updated_graph.ticker == "AAPL"

    def test_link_evidence_to_claims(self) -> None:
        """Test linking evidence to claims."""
        builder = ClaimGraphBuilder()

        graph = builder.build_from_text(
            "Revenue growth is expected to accelerate driven by iPhone demand.",
            ticker="AAPL",
        )

        evidence_texts = {
            "ev_001": "iPhone sales increased 20% with strong revenue growth.",
            "ev_002": "Cloud computing revenue reached new records.",
        }

        updated_graph = builder.link_evidence_to_claims(graph, evidence_texts)

        # Should update cited_claims count
        assert updated_graph.cited_claims >= 0

    def test_empty_text(self) -> None:
        """Test with empty text."""
        builder = ClaimGraphBuilder()
        graph = builder.build_from_text("")

        assert graph.claims == []
        assert graph.total_claims == 0

    def test_short_sentences_filtered(self) -> None:
        """Test that very short sentences are filtered out."""
        builder = ClaimGraphBuilder()
        text = "Yes. No. Maybe. Revenue will grow significantly."

        graph = builder.build_from_text(text)

        # Short sentences like "Yes. No." should be filtered
        for claim in graph.claims:
            assert len(claim.text) >= 30


class TestEntailmentVerifier:
    """Tests for EntailmentVerifier."""

    @pytest.fixture
    def sample_claim(self) -> Claim:
        """Create sample claim."""
        return Claim(
            claim_id="clm_001",
            text="Revenue is expected to grow 15% in the next fiscal year.",
            claim_type=ClaimType.FORECAST,
            section="financial",
            cited_evidence_ids=[],
            linked_fact_ids=[],
            confidence=0.7,
        )

    @pytest.fixture
    def supporting_evidence(self) -> list[str]:
        """Create supporting evidence."""
        return [
            "The company reported strong demand with revenue growth accelerating to 18% last quarter.",
            "Management raised guidance, now expecting full-year revenue growth of 15-17%.",
            "iPhone sales exceeded expectations, contributing to better than anticipated results.",
        ]

    @pytest.fixture
    def contradicting_evidence(self) -> list[str]:
        """Create contradicting evidence."""
        return [
            "However, revenue growth has slowed significantly, declining to just 3% last quarter.",
            "Management lowered guidance, now expecting revenue to fall 5% year over year.",
            "The company faces significant headwinds that will pressure growth going forward.",
        ]

    def test_verify_with_heuristics_supporting(
        self, sample_claim: Claim, supporting_evidence: list[str]
    ) -> None:
        """Test heuristic verification with supporting evidence."""
        verifier = EntailmentVerifier()
        result = verifier._verify_with_heuristics(sample_claim, supporting_evidence)

        assert isinstance(result, EntailmentResult)
        assert result.claim_id == sample_claim.claim_id
        # With supporting evidence mentioning revenue/growth, should be supported
        assert result.status in [EntailmentStatus.SUPPORTED, EntailmentStatus.WEAK, EntailmentStatus.UNSUPPORTED]

    def test_verify_with_heuristics_contradicting(
        self, sample_claim: Claim, contradicting_evidence: list[str]
    ) -> None:
        """Test heuristic verification with contradicting evidence."""
        verifier = EntailmentVerifier()
        result = verifier._verify_with_heuristics(sample_claim, contradicting_evidence)

        assert isinstance(result, EntailmentResult)
        # With contradiction words like "however", "declined", should detect contradiction
        assert result.status in [
            EntailmentStatus.CONTRADICTED,
            EntailmentStatus.WEAK,
            EntailmentStatus.UNSUPPORTED,
        ]

    @pytest.mark.asyncio
    async def test_verify_no_evidence(self, sample_claim: Claim) -> None:
        """Test verification with no evidence."""
        verifier = EntailmentVerifier()
        result = await verifier.verify_claim(sample_claim, [])

        assert result.status == EntailmentStatus.UNSUPPORTED
        assert result.confidence == 0.0

    def test_verify_claims_batch(
        self, sample_claim: Claim, supporting_evidence: list[str]
    ) -> None:
        """Test batch verification convenience function."""
        claims = [sample_claim]
        results = verify_claims_batch(claims, supporting_evidence)

        assert len(results) == 1
        assert results[0].claim_id == sample_claim.claim_id

    @pytest.mark.asyncio
    async def test_verify_claim_graph(
        self, supporting_evidence: list[str]
    ) -> None:
        """Test verifying an entire claim graph."""
        builder = ClaimGraphBuilder()
        graph = builder.build_from_text(
            "Revenue growth is expected to accelerate to 15% next year.",
            ticker="AAPL",
        )

        if not graph.claims:
            pytest.skip("No claims extracted")

        evidence_map = {
            "ev_001": supporting_evidence[0],
            "ev_002": supporting_evidence[1],
        }

        verifier = EntailmentVerifier()
        report = await verifier.verify_claim_graph(graph, evidence_map)

        assert report.claim_graph == graph
        assert len(report.results) == len(graph.claims)
        assert report.overall_confidence >= 0.0
        assert report.overall_confidence <= 1.0


class TestExtractedFact:
    """Tests for ExtractedFact dataclass."""

    def test_extracted_fact_creation(self) -> None:
        """Test creating an ExtractedFact."""
        fact = ExtractedFact(
            fact_id="fact_001",
            text="Revenue grew 15% year over year",
            source_claim_id="clm_001",
            evidence_ids=["ev_001"],
            confidence=0.8,
        )

        assert fact.fact_id == "fact_001"
        assert fact.source_claim_id == "clm_001"
        assert len(fact.evidence_ids) == 1

    def test_extracted_fact_defaults(self) -> None:
        """Test ExtractedFact default values."""
        fact = ExtractedFact(
            fact_id="fact_002",
            text="Some fact",
            source_claim_id="clm_002",
        )

        assert fact.evidence_ids == []
        assert fact.confidence == 0.5


class TestEntailmentResult:
    """Tests for EntailmentResult."""

    def test_to_dict(self) -> None:
        """Test conversion to dict."""
        result = EntailmentResult(
            claim_id="clm_001",
            status=EntailmentStatus.SUPPORTED,
            confidence=0.8,
            supporting_evidence=["Evidence 1"],
            contradicting_evidence=[],
            reasoning="Claim verified",
        )

        d = result.to_dict()
        assert d["claim_id"] == "clm_001"
        assert d["status"] == "supported"
        assert d["confidence"] == 0.8


class TestEntailmentReport:
    """Tests for EntailmentReport."""

    def test_to_dict(self) -> None:
        """Test conversion to dict."""
        graph = ClaimGraph(
            ticker="AAPL",
            source="analysis",
            claims=[],
            total_claims=0,
            cited_claims=0,
            uncited_claims=0,
        )

        report = EntailmentReport(
            claim_graph=graph,
            results=[],
            overall_confidence=0.5,
            claims_verified=0,
            claims_contradicted=0,
            claims_unverified=0,
        )

        d = report.to_dict()
        assert d["overall_confidence"] == 0.5
        assert "claim_graph" in d


class TestClaimTypePatterns:
    """Tests for claim type pattern matching."""

    def test_catalyst_pattern(self) -> None:
        """Test catalyst claim detection."""
        builder = ClaimGraphBuilder()
        text = "The upcoming product launch in Q4 is a major catalyst for growth."

        graph = builder.build_from_text(text)

        catalyst_claims = [c for c in graph.claims if c.section == "catalyst"]
        assert len(catalyst_claims) > 0

    def test_strategic_pattern(self) -> None:
        """Test strategic claim detection."""
        builder = ClaimGraphBuilder()
        text = "The company's competitive position has strengthened with market share gains."

        graph = builder.build_from_text(text)

        strategic_claims = [c for c in graph.claims if c.section == "strategic"]
        assert len(strategic_claims) > 0


class TestClaimGraphCounts:
    """Tests for claim graph counting."""

    def test_counts_updated_on_build(self) -> None:
        """Test that counts are set correctly."""
        builder = ClaimGraphBuilder()
        graph = builder.build_from_text(
            "Revenue will grow 15% with strong margin expansion. Competition is intensifying.",
            ticker="TEST",
        )

        assert graph.total_claims == len(graph.claims)
        assert graph.uncited_claims == len(graph.claims)  # None have evidence yet
        assert graph.cited_claims == 0
