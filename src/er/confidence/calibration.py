"""
Confidence Calibration for claims and evidence.

Provides systematic calibration of confidence scores based on:
1. Source quality and recency
2. Evidence strength and corroboration
3. Claim type and verification status
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from er.types import Claim, ClaimType, EntailmentStatus


class SourceTier(str, Enum):
    """Quality tiers for evidence sources."""

    TIER_1 = "tier_1"  # Primary: Filings, transcripts, official releases
    TIER_2 = "tier_2"  # Secondary: Analyst reports, institutional research
    TIER_3 = "tier_3"  # Tertiary: News, trade publications
    TIER_4 = "tier_4"  # Quaternary: Blogs, social, unverified
    DERIVED = "derived"  # Computed from other evidence


@dataclass
class CalibrationResult:
    """Result of confidence calibration for a claim or evidence item."""

    original_confidence: float
    calibrated_confidence: float
    adjustments: list[str] = field(default_factory=list)
    source_tier: SourceTier | None = None
    recency_days: int | None = None
    corroboration_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "original_confidence": self.original_confidence,
            "calibrated_confidence": self.calibrated_confidence,
            "adjustments": self.adjustments,
            "source_tier": self.source_tier.value if self.source_tier else None,
            "recency_days": self.recency_days,
            "corroboration_count": self.corroboration_count,
        }


class ConfidenceCalibrator:
    """Calibrates confidence scores based on evidence quality and context.

    Applies systematic adjustments based on:
    - Source tier (primary sources get higher weight)
    - Recency (newer evidence weighted higher)
    - Corroboration (multiple sources increase confidence)
    - Claim type (forecasts penalized vs. facts)
    - Verification status (supported claims boosted)
    """

    # Tier-based confidence multipliers
    TIER_MULTIPLIERS = {
        SourceTier.TIER_1: 1.0,    # Full confidence for primary sources
        SourceTier.TIER_2: 0.85,   # Slight discount for secondary
        SourceTier.TIER_3: 0.7,    # Larger discount for tertiary
        SourceTier.TIER_4: 0.5,    # Significant discount for unverified
        SourceTier.DERIVED: 0.9,   # Computed values get slight discount
    }

    # Recency decay factors (days -> multiplier)
    RECENCY_THRESHOLDS = [
        (30, 1.0),    # < 30 days: full confidence
        (90, 0.95),   # 30-90 days: slight decay
        (180, 0.85),  # 90-180 days: moderate decay
        (365, 0.7),   # 180-365 days: significant decay
        (730, 0.5),   # 1-2 years: large decay
    ]

    # Claim type confidence adjustments
    CLAIM_TYPE_ADJUSTMENTS = {
        ClaimType.FACT: 0.0,        # No adjustment for facts
        ClaimType.INFERENCE: -0.05,  # Slight penalty for inferences
        ClaimType.FORECAST: -0.15,   # Larger penalty for forecasts
        ClaimType.OPINION: -0.10,    # Moderate penalty for opinions
    }

    # Entailment status adjustments
    ENTAILMENT_ADJUSTMENTS = {
        EntailmentStatus.SUPPORTED: 0.15,
        EntailmentStatus.WEAK: 0.05,
        EntailmentStatus.UNSUPPORTED: -0.10,
        EntailmentStatus.CONTRADICTED: -0.25,
    }

    def __init__(
        self,
        min_confidence: float = 0.1,
        max_confidence: float = 0.95,
    ) -> None:
        """Initialize the calibrator.

        Args:
            min_confidence: Minimum allowed confidence score.
            max_confidence: Maximum allowed confidence score.
        """
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence

    def calibrate_claim(
        self,
        claim: Claim,
        source_tier: SourceTier = SourceTier.TIER_2,
        recency_days: int | None = None,
        corroboration_count: int = 0,
        entailment_status: EntailmentStatus | None = None,
    ) -> CalibrationResult:
        """Calibrate confidence for a claim.

        Args:
            claim: The claim to calibrate.
            source_tier: Quality tier of the source.
            recency_days: Days since evidence was collected.
            corroboration_count: Number of corroborating sources.
            entailment_status: Result of entailment verification.

        Returns:
            CalibrationResult with calibrated confidence.
        """
        adjustments = []
        confidence = claim.confidence

        # Apply source tier adjustment
        tier_mult = self.TIER_MULTIPLIERS.get(source_tier, 0.7)
        if tier_mult != 1.0:
            old_conf = confidence
            confidence *= tier_mult
            adjustments.append(
                f"Source tier ({source_tier.value}): {old_conf:.2f} -> {confidence:.2f}"
            )

        # Apply recency adjustment
        if recency_days is not None:
            recency_mult = self._get_recency_multiplier(recency_days)
            if recency_mult != 1.0:
                old_conf = confidence
                confidence *= recency_mult
                adjustments.append(
                    f"Recency ({recency_days}d): {old_conf:.2f} -> {confidence:.2f}"
                )

        # Apply claim type adjustment
        type_adj = self.CLAIM_TYPE_ADJUSTMENTS.get(claim.claim_type, 0.0)
        if type_adj != 0.0:
            old_conf = confidence
            confidence += type_adj
            adjustments.append(
                f"Claim type ({claim.claim_type.value}): {old_conf:.2f} -> {confidence:.2f}"
            )

        # Apply entailment adjustment
        if entailment_status:
            ent_adj = self.ENTAILMENT_ADJUSTMENTS.get(entailment_status, 0.0)
            if ent_adj != 0.0:
                old_conf = confidence
                confidence += ent_adj
                adjustments.append(
                    f"Entailment ({entailment_status.value}): {old_conf:.2f} -> {confidence:.2f}"
                )

        # Apply corroboration bonus
        if corroboration_count > 0:
            # Diminishing returns: each source adds less
            bonus = min(0.2, 0.05 * corroboration_count)
            old_conf = confidence
            confidence += bonus
            adjustments.append(
                f"Corroboration ({corroboration_count}): {old_conf:.2f} -> {confidence:.2f}"
            )

        # Clamp to valid range
        confidence = max(self.min_confidence, min(self.max_confidence, confidence))

        return CalibrationResult(
            original_confidence=claim.confidence,
            calibrated_confidence=confidence,
            adjustments=adjustments,
            source_tier=source_tier,
            recency_days=recency_days,
            corroboration_count=corroboration_count,
        )

    def calibrate_evidence(
        self,
        confidence: float,
        source_tier: SourceTier,
        recency_days: int | None = None,
    ) -> CalibrationResult:
        """Calibrate confidence for raw evidence.

        Args:
            confidence: Initial confidence score.
            source_tier: Quality tier of the source.
            recency_days: Days since evidence was collected.

        Returns:
            CalibrationResult with calibrated confidence.
        """
        adjustments = []
        original = confidence

        # Apply source tier adjustment
        tier_mult = self.TIER_MULTIPLIERS.get(source_tier, 0.7)
        confidence *= tier_mult
        adjustments.append(f"Source tier ({source_tier.value}): mult={tier_mult:.2f}")

        # Apply recency adjustment
        if recency_days is not None:
            recency_mult = self._get_recency_multiplier(recency_days)
            confidence *= recency_mult
            adjustments.append(f"Recency ({recency_days}d): mult={recency_mult:.2f}")

        # Clamp to valid range
        confidence = max(self.min_confidence, min(self.max_confidence, confidence))

        return CalibrationResult(
            original_confidence=original,
            calibrated_confidence=confidence,
            adjustments=adjustments,
            source_tier=source_tier,
            recency_days=recency_days,
        )

    def _get_recency_multiplier(self, days: int) -> float:
        """Get recency multiplier based on days since collection."""
        for threshold, multiplier in self.RECENCY_THRESHOLDS:
            if days <= threshold:
                return multiplier
        return 0.4  # Very old data

    def aggregate_confidence(
        self,
        confidences: list[float],
        weights: list[float] | None = None,
    ) -> float:
        """Aggregate multiple confidence scores.

        Uses weighted average with optional weights.

        Args:
            confidences: List of confidence scores.
            weights: Optional weights for each score.

        Returns:
            Aggregated confidence score.
        """
        if not confidences:
            return 0.5

        if weights is None:
            weights = [1.0] * len(confidences)

        # Weighted average
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.5

        weighted_sum = sum(c * w for c, w in zip(confidences, weights))
        return weighted_sum / total_weight


def calibrate_claim_batch(
    claims: list[Claim],
    source_tier: SourceTier = SourceTier.TIER_2,
) -> list[tuple[Claim, CalibrationResult]]:
    """Calibrate a batch of claims.

    Args:
        claims: Claims to calibrate.
        source_tier: Default source tier.

    Returns:
        List of (claim, calibration_result) tuples.
    """
    calibrator = ConfidenceCalibrator()
    results = []

    for claim in claims:
        result = calibrator.calibrate_claim(claim, source_tier=source_tier)
        results.append((claim, result))

    return results
