"""Tests for confidence calibration and tier policies."""

from __future__ import annotations

import pytest

from er.confidence.calibration import (
    ConfidenceCalibrator,
    CalibrationResult,
    SourceTier,
    calibrate_claim_batch,
)
from er.confidence.tier_policy import (
    EvidenceTierPolicy,
    TierAssignment,
    classify_sources,
)
from er.types import Claim, ClaimType, EntailmentStatus


class TestSourceTier:
    """Tests for SourceTier enum."""

    def test_tier_values(self) -> None:
        """Test tier enum values."""
        assert SourceTier.TIER_1.value == "tier_1"
        assert SourceTier.TIER_2.value == "tier_2"
        assert SourceTier.TIER_3.value == "tier_3"
        assert SourceTier.TIER_4.value == "tier_4"
        assert SourceTier.DERIVED.value == "derived"


class TestConfidenceCalibrator:
    """Tests for ConfidenceCalibrator."""

    @pytest.fixture
    def calibrator(self) -> ConfidenceCalibrator:
        """Create calibrator instance."""
        return ConfidenceCalibrator()

    @pytest.fixture
    def sample_claim(self) -> Claim:
        """Create sample claim."""
        return Claim(
            claim_id="clm_001",
            text="Revenue will grow 15% next year",
            claim_type=ClaimType.FORECAST,
            section="financial",
            cited_evidence_ids=[],
            linked_fact_ids=[],
            confidence=0.7,
        )

    def test_calibrate_claim_tier_1(
        self, calibrator: ConfidenceCalibrator, sample_claim: Claim
    ) -> None:
        """Test calibration with TIER_1 source."""
        result = calibrator.calibrate_claim(
            sample_claim, source_tier=SourceTier.TIER_1
        )

        assert isinstance(result, CalibrationResult)
        assert result.original_confidence == 0.7
        assert result.source_tier == SourceTier.TIER_1
        # TIER_1 has no discount, but forecast has penalty
        assert result.calibrated_confidence < result.original_confidence

    def test_calibrate_claim_tier_4(
        self, calibrator: ConfidenceCalibrator, sample_claim: Claim
    ) -> None:
        """Test calibration with TIER_4 source applies discount."""
        result = calibrator.calibrate_claim(
            sample_claim, source_tier=SourceTier.TIER_4
        )

        # TIER_4 has 0.5 multiplier
        assert result.calibrated_confidence < result.original_confidence * 0.6

    def test_calibrate_claim_recency(
        self, calibrator: ConfidenceCalibrator, sample_claim: Claim
    ) -> None:
        """Test recency adjustment."""
        # Recent data
        result_recent = calibrator.calibrate_claim(
            sample_claim, source_tier=SourceTier.TIER_1, recency_days=10
        )

        # Old data
        result_old = calibrator.calibrate_claim(
            sample_claim, source_tier=SourceTier.TIER_1, recency_days=400
        )

        # Recent should have higher confidence
        assert result_recent.calibrated_confidence > result_old.calibrated_confidence

    def test_calibrate_claim_entailment_boost(
        self, calibrator: ConfidenceCalibrator, sample_claim: Claim
    ) -> None:
        """Test entailment status affects calibration."""
        result_supported = calibrator.calibrate_claim(
            sample_claim,
            source_tier=SourceTier.TIER_1,
            entailment_status=EntailmentStatus.SUPPORTED,
        )

        result_contradicted = calibrator.calibrate_claim(
            sample_claim,
            source_tier=SourceTier.TIER_1,
            entailment_status=EntailmentStatus.CONTRADICTED,
        )

        assert result_supported.calibrated_confidence > result_contradicted.calibrated_confidence

    def test_calibrate_claim_corroboration(
        self, calibrator: ConfidenceCalibrator, sample_claim: Claim
    ) -> None:
        """Test corroboration bonus."""
        result_single = calibrator.calibrate_claim(
            sample_claim, source_tier=SourceTier.TIER_2, corroboration_count=0
        )

        result_corroborated = calibrator.calibrate_claim(
            sample_claim, source_tier=SourceTier.TIER_2, corroboration_count=3
        )

        assert result_corroborated.calibrated_confidence > result_single.calibrated_confidence

    def test_calibrate_claim_type_penalty(
        self, calibrator: ConfidenceCalibrator
    ) -> None:
        """Test claim type affects calibration."""
        fact_claim = Claim(
            claim_id="clm_fact",
            text="Revenue was $100B last quarter",
            claim_type=ClaimType.FACT,
            section="financial",
            confidence=0.7,
        )

        forecast_claim = Claim(
            claim_id="clm_forecast",
            text="Revenue will be $110B next quarter",
            claim_type=ClaimType.FORECAST,
            section="financial",
            confidence=0.7,
        )

        result_fact = calibrator.calibrate_claim(fact_claim, SourceTier.TIER_1)
        result_forecast = calibrator.calibrate_claim(forecast_claim, SourceTier.TIER_1)

        # Facts should have higher calibrated confidence than forecasts
        assert result_fact.calibrated_confidence > result_forecast.calibrated_confidence

    def test_calibrate_evidence(self, calibrator: ConfidenceCalibrator) -> None:
        """Test evidence calibration."""
        result = calibrator.calibrate_evidence(
            confidence=0.8,
            source_tier=SourceTier.TIER_2,
            recency_days=45,
        )

        assert result.original_confidence == 0.8
        assert result.source_tier == SourceTier.TIER_2
        assert result.recency_days == 45

    def test_calibration_clamping(self, calibrator: ConfidenceCalibrator) -> None:
        """Test confidence is clamped to valid range."""
        claim = Claim(
            claim_id="clm_high",
            text="Revenue growth certain to exceed expectations significantly",
            claim_type=ClaimType.FACT,
            section="financial",
            confidence=0.99,
        )

        result = calibrator.calibrate_claim(
            claim,
            source_tier=SourceTier.TIER_1,
            corroboration_count=5,
            entailment_status=EntailmentStatus.SUPPORTED,
        )

        assert result.calibrated_confidence <= 0.95  # max_confidence

    def test_aggregate_confidence(self, calibrator: ConfidenceCalibrator) -> None:
        """Test confidence aggregation."""
        confidences = [0.8, 0.6, 0.9]

        # Unweighted average
        result = calibrator.aggregate_confidence(confidences)
        assert abs(result - 0.767) < 0.01

        # Weighted average
        weights = [1.0, 0.5, 2.0]
        result_weighted = calibrator.aggregate_confidence(confidences, weights)
        # (0.8*1 + 0.6*0.5 + 0.9*2) / (1+0.5+2) = 2.9/3.5 = 0.829
        assert abs(result_weighted - 0.829) < 0.01

    def test_aggregate_confidence_empty(self, calibrator: ConfidenceCalibrator) -> None:
        """Test aggregation with empty list."""
        result = calibrator.aggregate_confidence([])
        assert result == 0.5

    def test_calibration_result_to_dict(self) -> None:
        """Test CalibrationResult serialization."""
        result = CalibrationResult(
            original_confidence=0.7,
            calibrated_confidence=0.6,
            adjustments=["Test adjustment"],
            source_tier=SourceTier.TIER_2,
            recency_days=30,
            corroboration_count=2,
        )

        d = result.to_dict()
        assert d["original_confidence"] == 0.7
        assert d["calibrated_confidence"] == 0.6
        assert d["source_tier"] == "tier_2"
        assert d["corroboration_count"] == 2


class TestCalibrateBatch:
    """Tests for batch calibration."""

    def test_calibrate_claim_batch(self) -> None:
        """Test batch calibration."""
        claims = [
            Claim(
                claim_id="clm_1",
                text="Revenue grew 10%",
                claim_type=ClaimType.FACT,
                section="financial",
                confidence=0.8,
            ),
            Claim(
                claim_id="clm_2",
                text="Margins will expand",
                claim_type=ClaimType.FORECAST,
                section="financial",
                confidence=0.6,
            ),
        ]

        results = calibrate_claim_batch(claims, source_tier=SourceTier.TIER_2)

        assert len(results) == 2
        assert results[0][0].claim_id == "clm_1"
        assert isinstance(results[0][1], CalibrationResult)


class TestEvidenceTierPolicy:
    """Tests for EvidenceTierPolicy."""

    @pytest.fixture
    def policy(self) -> EvidenceTierPolicy:
        """Create policy instance."""
        return EvidenceTierPolicy()

    def test_assign_tier_by_source_type(self, policy: EvidenceTierPolicy) -> None:
        """Test tier assignment by source type."""
        # SEC filing -> TIER_1
        result = policy.assign_tier(source_type="10-K")
        assert result.tier == SourceTier.TIER_1

        # Transcript -> TIER_1
        result = policy.assign_tier(source_type="transcript")
        assert result.tier == SourceTier.TIER_1

        # News -> TIER_3
        result = policy.assign_tier(source_type="news")
        assert result.tier == SourceTier.TIER_3

    def test_assign_tier_by_domain(self, policy: EvidenceTierPolicy) -> None:
        """Test tier assignment by domain."""
        # SEC.gov -> TIER_1
        result = policy.assign_tier(source_url="https://www.sec.gov/filing/12345")
        assert result.tier == SourceTier.TIER_1

        # Bloomberg -> TIER_3
        result = policy.assign_tier(source_url="https://www.bloomberg.com/article/xyz")
        assert result.tier == SourceTier.TIER_3

        # Seeking Alpha -> TIER_4
        result = policy.assign_tier(source_url="https://seekingalpha.com/article/123")
        assert result.tier == SourceTier.TIER_4

    def test_assign_tier_unknown_source(self, policy: EvidenceTierPolicy) -> None:
        """Test unknown source defaults to TIER_4."""
        result = policy.assign_tier(source_url="https://random-blog.com/post")
        assert result.tier == SourceTier.TIER_4

    def test_assign_tier_custom_domains(self) -> None:
        """Test custom domain configuration."""
        policy = EvidenceTierPolicy(
            custom_tier_1={"mycompany.com"},
        )

        result = policy.assign_tier(source_url="https://investor.mycompany.com/report")
        assert result.tier == SourceTier.TIER_1

    def test_extract_domain(self, policy: EvidenceTierPolicy) -> None:
        """Test domain extraction from URLs."""
        assert policy._extract_domain("https://www.sec.gov/filing") == "sec.gov"
        assert policy._extract_domain("http://bloomberg.com/article") == "bloomberg.com"
        assert policy._extract_domain("sec.gov/filing") == "sec.gov"

    def test_tier_policy_description(self, policy: EvidenceTierPolicy) -> None:
        """Test getting tier descriptions."""
        desc = policy.get_tier_policy_description(SourceTier.TIER_1)
        assert "Primary sources" in desc
        assert "SEC filings" in desc

    def test_should_require_corroboration(self, policy: EvidenceTierPolicy) -> None:
        """Test corroboration requirements."""
        assert not policy.should_require_corroboration(SourceTier.TIER_1)
        assert not policy.should_require_corroboration(SourceTier.TIER_2)
        assert policy.should_require_corroboration(SourceTier.TIER_3)
        assert policy.should_require_corroboration(SourceTier.TIER_4)

    def test_minimum_sources_for_claim(self, policy: EvidenceTierPolicy) -> None:
        """Test minimum source requirements."""
        assert policy.get_minimum_sources_for_claim(SourceTier.TIER_1) == 1
        assert policy.get_minimum_sources_for_claim(SourceTier.TIER_2) == 1
        assert policy.get_minimum_sources_for_claim(SourceTier.TIER_3) == 2
        assert policy.get_minimum_sources_for_claim(SourceTier.TIER_4) == 3

    def test_tier_assignment_to_dict(self) -> None:
        """Test TierAssignment serialization."""
        assignment = TierAssignment(
            source_url="https://sec.gov/filing",
            source_type="10-K",
            tier=SourceTier.TIER_1,
            domain="sec.gov",
            reason="Primary source",
            reputation_score=1.0,
        )

        d = assignment.to_dict()
        assert d["tier"] == "tier_1"
        assert d["reputation_score"] == 1.0


class TestClassifySources:
    """Tests for batch source classification."""

    def test_classify_sources(self) -> None:
        """Test batch classification."""
        sources = [
            {"url": "https://sec.gov/filing/abc", "type": "10-K"},
            {"url": "https://bloomberg.com/article/xyz", "type": "news"},
            {"url": "https://seekingalpha.com/article/123", "type": "blog"},
        ]

        assignments = classify_sources(sources)

        assert len(assignments) == 3
        assert assignments[0].tier == SourceTier.TIER_1
        assert assignments[1].tier == SourceTier.TIER_3
        assert assignments[2].tier == SourceTier.TIER_4
