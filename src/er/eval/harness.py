"""
Evaluation Harness for Pipeline Testing.

Provides:
1. Deterministic evaluation using pinned fixtures
2. Metrics calculation for claim accuracy, coverage, etc.
3. Regression detection between runs
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import orjson

from er.eval.fixtures import PinnedFixture, FixtureLoader
from er.types import (
    Claim,
    ClaimType,
)


class EvalStatus(str, Enum):
    """Evaluation run status."""

    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass
class ClaimMatch:
    """A match between expected and actual claims."""

    expected_claim: str
    actual_claim: str | None
    match_score: float  # 0.0 to 1.0
    is_exact: bool
    claim_type_match: bool


@dataclass
class EvalMetrics:
    """Evaluation metrics for a single run."""

    # Claim metrics
    total_expected_claims: int = 0
    total_actual_claims: int = 0
    matched_claims: int = 0
    exact_matches: int = 0
    missing_claims: int = 0
    extra_claims: int = 0

    # Claim type accuracy
    claim_type_accuracy: float = 0.0

    # Verification metrics
    verified_claims: int = 0
    verification_rate: float = 0.0

    # Coverage metrics
    fact_coverage: float = 0.0  # % of expected facts found
    section_coverage: float = 0.0  # % of sections with content

    # Quality metrics
    avg_confidence: float = 0.0
    recommendation_match: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "total_expected_claims": self.total_expected_claims,
            "total_actual_claims": self.total_actual_claims,
            "matched_claims": self.matched_claims,
            "exact_matches": self.exact_matches,
            "missing_claims": self.missing_claims,
            "extra_claims": self.extra_claims,
            "claim_type_accuracy": round(self.claim_type_accuracy, 3),
            "verified_claims": self.verified_claims,
            "verification_rate": round(self.verification_rate, 3),
            "fact_coverage": round(self.fact_coverage, 3),
            "section_coverage": round(self.section_coverage, 3),
            "avg_confidence": round(self.avg_confidence, 3),
            "recommendation_match": self.recommendation_match,
        }

    @property
    def precision(self) -> float:
        """Calculate precision (matched / actual)."""
        if self.total_actual_claims == 0:
            return 0.0
        return self.matched_claims / self.total_actual_claims

    @property
    def recall(self) -> float:
        """Calculate recall (matched / expected)."""
        if self.total_expected_claims == 0:
            return 0.0
        return self.matched_claims / self.total_expected_claims

    @property
    def f1_score(self) -> float:
        """Calculate F1 score."""
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)


@dataclass
class EvalResult:
    """Result of a single evaluation run."""

    fixture_id: str
    ticker: str
    run_at: datetime
    status: EvalStatus
    metrics: EvalMetrics
    claim_matches: list[ClaimMatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "fixture_id": self.fixture_id,
            "ticker": self.ticker,
            "run_at": self.run_at.isoformat(),
            "status": self.status.value,
            "metrics": self.metrics.to_dict(),
            "claim_matches": [
                {
                    "expected": m.expected_claim,
                    "actual": m.actual_claim,
                    "score": m.match_score,
                    "exact": m.is_exact,
                }
                for m in self.claim_matches
            ],
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 2),
            "f1_score": round(self.metrics.f1_score, 3),
        }


class EvalHarness:
    """Evaluation harness for pipeline testing.

    Usage:
        harness = EvalHarness()
        result = await harness.evaluate("aapl_2024q4")
        print(f"F1 Score: {result.metrics.f1_score}")
    """

    # Thresholds for pass/fail
    MIN_RECALL = 0.7  # Must find 70% of expected claims
    MIN_PRECISION = 0.5  # At least 50% of claims should be expected
    MIN_VERIFICATION_RATE = 0.6  # 60% of claims should be verified

    def __init__(
        self,
        fixtures_dir: Path | None = None,
        results_dir: Path | None = None,
    ) -> None:
        """Initialize harness.

        Args:
            fixtures_dir: Directory containing fixtures.
            results_dir: Directory to save results.
        """
        self.fixture_loader = FixtureLoader(fixtures_dir)
        self.results_dir = results_dir or Path("eval_results")

    async def evaluate(
        self,
        fixture_id: str,
        actual_claims: list[Claim] | None = None,
        actual_facts: list[dict[str, Any]] | None = None,
        actual_recommendation: str | None = None,
    ) -> EvalResult:
        """Evaluate pipeline output against a pinned fixture.

        Args:
            fixture_id: ID of fixture to evaluate against.
            actual_claims: Claims extracted by pipeline.
            actual_facts: Facts discovered by pipeline.
            actual_recommendation: Final recommendation.

        Returns:
            EvalResult with metrics and matches.
        """
        from er.types import utc_now
        import time

        start_time = time.time()

        fixture = self.fixture_loader.load(fixture_id)
        if fixture is None:
            return EvalResult(
                fixture_id=fixture_id,
                ticker="UNKNOWN",
                run_at=utc_now(),
                status=EvalStatus.ERROR,
                metrics=EvalMetrics(),
                errors=[f"Fixture not found: {fixture_id}"],
            )

        # Verify fixture integrity
        if not fixture.verify_integrity():
            return EvalResult(
                fixture_id=fixture_id,
                ticker=fixture.ticker,
                run_at=utc_now(),
                status=EvalStatus.ERROR,
                metrics=EvalMetrics(),
                errors=["Fixture integrity check failed - content may have changed"],
            )

        errors: list[str] = []
        actual_claims = actual_claims or []
        actual_facts = actual_facts or []

        # Match claims
        claim_matches = self._match_claims(
            expected=[c["text"] for c in fixture.expected_claims],
            actual=[c.text for c in actual_claims],
        )

        # Calculate metrics
        metrics = self._calculate_metrics(
            fixture=fixture,
            actual_claims=actual_claims,
            actual_facts=actual_facts,
            actual_recommendation=actual_recommendation,
            claim_matches=claim_matches,
        )

        # Determine status
        status = self._determine_status(metrics)

        duration = time.time() - start_time

        return EvalResult(
            fixture_id=fixture_id,
            ticker=fixture.ticker,
            run_at=utc_now(),
            status=status,
            metrics=metrics,
            claim_matches=claim_matches,
            errors=errors,
            duration_seconds=duration,
        )

    def _match_claims(
        self,
        expected: list[str],
        actual: list[str],
    ) -> list[ClaimMatch]:
        """Match expected claims to actual claims."""
        matches: list[ClaimMatch] = []
        used_actual: set[int] = set()

        for exp_claim in expected:
            best_match: ClaimMatch | None = None
            best_idx: int = -1

            for i, act_claim in enumerate(actual):
                if i in used_actual:
                    continue

                score = self._calculate_similarity(exp_claim, act_claim)
                is_exact = exp_claim.lower().strip() == act_claim.lower().strip()

                if best_match is None or score > best_match.match_score:
                    best_match = ClaimMatch(
                        expected_claim=exp_claim,
                        actual_claim=act_claim,
                        match_score=score,
                        is_exact=is_exact,
                        claim_type_match=True,  # Would need claim types to check
                    )
                    best_idx = i

            if best_match and best_match.match_score >= 0.5:
                matches.append(best_match)
                used_actual.add(best_idx)
            else:
                # No match found
                matches.append(
                    ClaimMatch(
                        expected_claim=exp_claim,
                        actual_claim=None,
                        match_score=0.0,
                        is_exact=False,
                        claim_type_match=False,
                    )
                )

        return matches

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity (simple word overlap)."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _calculate_metrics(
        self,
        fixture: PinnedFixture,
        actual_claims: list[Claim],
        actual_facts: list[dict[str, Any]],
        actual_recommendation: str | None,
        claim_matches: list[ClaimMatch],
    ) -> EvalMetrics:
        """Calculate evaluation metrics."""
        total_expected = len(fixture.expected_claims)
        total_actual = len(actual_claims)
        matched = sum(1 for m in claim_matches if m.actual_claim is not None)
        exact = sum(1 for m in claim_matches if m.is_exact)

        # Verification rate - based on claim confidence as proxy
        # Claims with confidence >= 0.7 are considered "verified"
        verified = sum(
            1
            for c in actual_claims
            if c.confidence >= 0.7
        )
        verification_rate = verified / total_actual if total_actual > 0 else 0.0

        # Fact coverage
        expected_fact_count = len(fixture.expected_facts)
        actual_fact_count = len(actual_facts)
        fact_coverage = (
            min(actual_fact_count / expected_fact_count, 1.0)
            if expected_fact_count > 0
            else 1.0
        )

        # Average confidence
        avg_confidence = (
            sum(c.confidence for c in actual_claims) / total_actual
            if total_actual > 0
            else 0.0
        )

        # Recommendation match
        rec_match = False
        if fixture.expected_recommendation and actual_recommendation:
            rec_match = (
                fixture.expected_recommendation.lower()
                == actual_recommendation.lower()
            )

        # Claim type accuracy
        type_matches = sum(1 for m in claim_matches if m.claim_type_match)
        type_accuracy = type_matches / len(claim_matches) if claim_matches else 0.0

        return EvalMetrics(
            total_expected_claims=total_expected,
            total_actual_claims=total_actual,
            matched_claims=matched,
            exact_matches=exact,
            missing_claims=total_expected - matched,
            extra_claims=max(0, total_actual - matched),
            claim_type_accuracy=type_accuracy,
            verified_claims=verified,
            verification_rate=verification_rate,
            fact_coverage=fact_coverage,
            section_coverage=1.0,  # Would need section data
            avg_confidence=avg_confidence,
            recommendation_match=rec_match,
        )

    def _determine_status(self, metrics: EvalMetrics) -> EvalStatus:
        """Determine pass/fail status from metrics."""
        if metrics.recall >= self.MIN_RECALL and metrics.precision >= self.MIN_PRECISION:
            if metrics.verification_rate >= self.MIN_VERIFICATION_RATE:
                return EvalStatus.PASSED
            return EvalStatus.PARTIAL
        return EvalStatus.FAILED

    async def evaluate_batch(
        self,
        fixture_ids: list[str],
        results_by_fixture: dict[str, dict[str, Any]],
    ) -> list[EvalResult]:
        """Evaluate multiple fixtures.

        Args:
            fixture_ids: List of fixture IDs to evaluate.
            results_by_fixture: Actual results keyed by fixture ID.

        Returns:
            List of EvalResults.
        """
        results = []
        for fixture_id in fixture_ids:
            actual = results_by_fixture.get(fixture_id, {})
            result = await self.evaluate(
                fixture_id=fixture_id,
                actual_claims=actual.get("claims", []),
                actual_facts=actual.get("facts", []),
                actual_recommendation=actual.get("recommendation"),
            )
            results.append(result)
        return results

    def save_result(self, result: EvalResult) -> Path:
        """Save evaluation result to disk.

        Args:
            result: Result to save.

        Returns:
            Path to saved file.
        """
        self.results_dir.mkdir(parents=True, exist_ok=True)

        timestamp = result.run_at.strftime("%Y%m%d_%H%M%S")
        filename = f"{result.fixture_id}_{timestamp}.json"
        result_path = self.results_dir / filename

        with open(result_path, "wb") as f:
            f.write(orjson.dumps(result.to_dict(), option=orjson.OPT_INDENT_2))

        return result_path

    def compare_results(
        self,
        baseline: EvalResult,
        current: EvalResult,
    ) -> dict[str, Any]:
        """Compare two eval results for regression detection.

        Args:
            baseline: Previous/baseline result.
            current: Current result to compare.

        Returns:
            Comparison dict with regressions.
        """
        regressions: list[str] = []
        improvements: list[str] = []

        # Compare key metrics
        if current.metrics.recall < baseline.metrics.recall - 0.05:
            regressions.append(
                f"Recall dropped: {baseline.metrics.recall:.2%} → {current.metrics.recall:.2%}"
            )
        elif current.metrics.recall > baseline.metrics.recall + 0.05:
            improvements.append(
                f"Recall improved: {baseline.metrics.recall:.2%} → {current.metrics.recall:.2%}"
            )

        if current.metrics.precision < baseline.metrics.precision - 0.05:
            regressions.append(
                f"Precision dropped: {baseline.metrics.precision:.2%} → {current.metrics.precision:.2%}"
            )
        elif current.metrics.precision > baseline.metrics.precision + 0.05:
            improvements.append(
                f"Precision improved: {baseline.metrics.precision:.2%} → {current.metrics.precision:.2%}"
            )

        if current.metrics.verification_rate < baseline.metrics.verification_rate - 0.05:
            regressions.append(
                f"Verification rate dropped: {baseline.metrics.verification_rate:.2%} → {current.metrics.verification_rate:.2%}"
            )

        return {
            "baseline_fixture": baseline.fixture_id,
            "current_fixture": current.fixture_id,
            "baseline_f1": baseline.metrics.f1_score,
            "current_f1": current.metrics.f1_score,
            "has_regressions": len(regressions) > 0,
            "regressions": regressions,
            "improvements": improvements,
        }
