"""Tests for evaluation harness."""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from er.eval.harness import (
    EvalHarness,
    EvalResult,
    EvalMetrics,
    EvalStatus,
    ClaimMatch,
)
from er.eval.fixtures import (
    PinnedFixture,
    FixtureLoader,
)
from er.types import Claim, ClaimType


class TestPinnedFixture:
    """Tests for PinnedFixture."""

    def test_fixture_creation(self):
        """Test creating a fixture."""
        fixture = PinnedFixture(
            fixture_id="test_fixture",
            ticker="AAPL",
            company_name="Apple Inc.",
            created_at=datetime(2024, 1, 15),
            version="1.0",
            profile={"companyName": "Apple Inc."},
            financials={"revenue": 400e9},
        )

        assert fixture.fixture_id == "test_fixture"
        assert fixture.ticker == "AAPL"
        assert fixture.content_hash != ""

    def test_fixture_integrity(self):
        """Test fixture integrity verification."""
        fixture = PinnedFixture(
            fixture_id="test",
            ticker="AAPL",
            company_name="Apple",
            created_at=datetime(2024, 1, 1),
            version="1.0",
            profile={"test": "data"},
        )

        # Should pass initially
        assert fixture.verify_integrity() is True

        # Modify content
        fixture.profile["test"] = "modified"

        # Should fail now
        assert fixture.verify_integrity() is False

    def test_fixture_to_dict(self):
        """Test fixture serialization."""
        fixture = PinnedFixture(
            fixture_id="test",
            ticker="TEST",
            company_name="Test Corp",
            created_at=datetime(2024, 1, 1),
            version="1.0",
            expected_recommendation="BUY",
        )

        d = fixture.to_dict()

        assert d["fixture_id"] == "test"
        assert d["ticker"] == "TEST"
        assert d["expected_recommendation"] == "BUY"

    def test_fixture_from_dict(self):
        """Test fixture deserialization."""
        data = {
            "fixture_id": "test",
            "ticker": "MSFT",
            "company_name": "Microsoft",
            "created_at": "2024-01-15T00:00:00",
            "version": "1.0",
            "profile": {},
            "financials": {},
            "filings": [],
            "transcripts": [],
            "news": [],
            "expected_claims": [],
            "expected_facts": [],
            "expected_recommendation": "HOLD",
            "content_hash": "",
            "notes": "Test fixture",
        }

        fixture = PinnedFixture.from_dict(data)

        assert fixture.ticker == "MSFT"
        assert fixture.expected_recommendation == "HOLD"


class TestFixtureLoader:
    """Tests for FixtureLoader."""

    def test_create_fixture(self):
        """Test creating fixture via loader."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = FixtureLoader(Path(tmpdir))

            fixture = loader.create_fixture(
                fixture_id="new_test",
                ticker="NVDA",
                company_name="NVIDIA",
                profile={"sector": "Technology"},
                financials={"revenue": 60e9},
            )

            assert fixture.fixture_id == "new_test"
            assert fixture.ticker == "NVDA"

    def test_save_and_load(self):
        """Test saving and loading fixtures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = FixtureLoader(Path(tmpdir))

            # Create and save
            fixture = loader.create_fixture(
                fixture_id="test_save",
                ticker="GOOG",
                company_name="Alphabet",
                profile={"industry": "Internet"},
                financials={"revenue": 300e9},
            )
            loader.save(fixture)

            # Load
            loaded = loader.load("test_save")

            assert loaded is not None
            assert loaded.ticker == "GOOG"
            assert loaded.financials["revenue"] == 300e9

    def test_list_fixtures(self):
        """Test listing available fixtures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = FixtureLoader(Path(tmpdir))

            # Create multiple fixtures
            for i in range(3):
                fixture = loader.create_fixture(
                    fixture_id=f"fixture_{i}",
                    ticker=f"TEST{i}",
                    company_name=f"Test {i}",
                    profile={},
                    financials={},
                )
                loader.save(fixture)

            fixtures = loader.list_fixtures()

            assert len(fixtures) == 3
            assert "fixture_0" in fixtures

    def test_load_nonexistent(self):
        """Test loading nonexistent fixture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = FixtureLoader(Path(tmpdir))

            result = loader.load("does_not_exist")

            assert result is None


class TestEvalMetrics:
    """Tests for EvalMetrics."""

    def test_precision_calculation(self):
        """Test precision calculation."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=8,
            matched_claims=6,
        )

        assert metrics.precision == 6 / 8

    def test_recall_calculation(self):
        """Test recall calculation."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=8,
            matched_claims=7,
        )

        assert metrics.recall == 7 / 10

    def test_f1_calculation(self):
        """Test F1 score calculation."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=10,
            matched_claims=8,
        )

        # precision = 8/10 = 0.8
        # recall = 8/10 = 0.8
        # f1 = 2 * 0.8 * 0.8 / (0.8 + 0.8) = 0.8
        assert abs(metrics.f1_score - 0.8) < 0.001

    def test_f1_with_zero_values(self):
        """Test F1 with zero values."""
        metrics = EvalMetrics(
            total_expected_claims=0,
            total_actual_claims=0,
            matched_claims=0,
        )

        assert metrics.f1_score == 0.0

    def test_metrics_to_dict(self):
        """Test metrics serialization."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=8,
            matched_claims=6,
            verification_rate=0.75,
        )

        d = metrics.to_dict()

        assert d["total_expected_claims"] == 10
        assert d["verification_rate"] == 0.75


class TestEvalResult:
    """Tests for EvalResult."""

    def test_result_to_dict(self):
        """Test result serialization."""
        result = EvalResult(
            fixture_id="test",
            ticker="AAPL",
            run_at=datetime(2024, 1, 15, 10, 0, 0),
            status=EvalStatus.PASSED,
            metrics=EvalMetrics(
                total_expected_claims=10,
                total_actual_claims=10,
                matched_claims=8,
            ),
            duration_seconds=5.5,
        )

        d = result.to_dict()

        assert d["fixture_id"] == "test"
        assert d["status"] == "passed"
        assert d["duration_seconds"] == 5.5
        assert "f1_score" in d


class TestEvalHarness:
    """Tests for EvalHarness."""

    @pytest.fixture
    def harness(self):
        """Create harness with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield EvalHarness(
                fixtures_dir=Path(tmpdir) / "fixtures",
                results_dir=Path(tmpdir) / "results",
            )

    @pytest.mark.asyncio
    async def test_evaluate_missing_fixture(self, harness):
        """Test evaluation with missing fixture."""
        result = await harness.evaluate("nonexistent")

        assert result.status == EvalStatus.ERROR
        assert "not found" in result.errors[0]

    @pytest.mark.asyncio
    async def test_evaluate_with_fixture(self):
        """Test evaluation with actual fixture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixtures_dir = Path(tmpdir) / "fixtures"
            results_dir = Path(tmpdir) / "results"

            harness = EvalHarness(fixtures_dir, results_dir)

            # Create fixture
            fixture = harness.fixture_loader.create_fixture(
                fixture_id="test_eval",
                ticker="TEST",
                company_name="Test Corp",
                profile={},
                financials={},
            )
            fixture.expected_claims = [
                {"text": "Revenue grew 10%"},
                {"text": "Margins improved"},
            ]
            fixture.expected_recommendation = "BUY"
            harness.fixture_loader.save(fixture)

            # Evaluate with matching claims
            actual_claims = [
                Claim(
                    claim_id="c1",
                    text="Revenue grew 10%",
                    claim_type=ClaimType.FACT,
                    section="financials",
                    confidence=0.9,
                ),
                Claim(
                    claim_id="c2",
                    text="Margins improved significantly",
                    claim_type=ClaimType.FACT,
                    section="financials",
                    confidence=0.85,
                ),
            ]

            result = await harness.evaluate(
                fixture_id="test_eval",
                actual_claims=actual_claims,
                actual_recommendation="BUY",
            )

            assert result.fixture_id == "test_eval"
            assert result.metrics.matched_claims >= 1

    def test_match_claims_exact(self, harness):
        """Test exact claim matching."""
        expected = ["Revenue grew 10%", "Margins improved"]
        actual = ["Revenue grew 10%", "Cost savings achieved"]

        matches = harness._match_claims(expected, actual)

        assert len(matches) == 2
        assert matches[0].is_exact is True  # Exact match
        assert matches[1].actual_claim is None  # No match

    def test_match_claims_similar(self, harness):
        """Test similar claim matching."""
        expected = ["Revenue increased by approximately 10 percent"]
        actual = ["Revenue increased approximately 10 percent year over year"]

        matches = harness._match_claims(expected, actual)

        # Should find partial match
        assert matches[0].match_score > 0.5

    def test_calculate_similarity(self, harness):
        """Test text similarity calculation."""
        text1 = "Revenue grew 10% year over year"
        text2 = "Revenue grew 10% YoY"

        similarity = harness._calculate_similarity(text1, text2)

        assert similarity > 0.4  # Some overlap

    def test_calculate_similarity_identical(self, harness):
        """Test similarity of identical texts."""
        text = "Exact same text"

        similarity = harness._calculate_similarity(text, text)

        assert similarity == 1.0

    def test_calculate_similarity_no_overlap(self, harness):
        """Test similarity with no overlap."""
        text1 = "apple orange banana"
        text2 = "car house tree"

        similarity = harness._calculate_similarity(text1, text2)

        assert similarity == 0.0

    def test_determine_status_passed(self, harness):
        """Test status determination - passed."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=10,
            matched_claims=8,  # 80% recall/precision
            verification_rate=0.7,
        )

        status = harness._determine_status(metrics)

        assert status == EvalStatus.PASSED

    def test_determine_status_failed(self, harness):
        """Test status determination - failed."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=10,
            matched_claims=3,  # 30% recall/precision
            verification_rate=0.2,
        )

        status = harness._determine_status(metrics)

        assert status == EvalStatus.FAILED

    def test_determine_status_partial(self, harness):
        """Test status determination - partial."""
        metrics = EvalMetrics(
            total_expected_claims=10,
            total_actual_claims=10,
            matched_claims=8,  # Good recall/precision
            verification_rate=0.4,  # But low verification
        )

        status = harness._determine_status(metrics)

        assert status == EvalStatus.PARTIAL

    def test_compare_results(self, harness):
        """Test result comparison for regression detection."""
        baseline = EvalResult(
            fixture_id="test",
            ticker="TEST",
            run_at=datetime(2024, 1, 1),
            status=EvalStatus.PASSED,
            metrics=EvalMetrics(
                total_expected_claims=10,
                total_actual_claims=10,
                matched_claims=8,
                verification_rate=0.8,
            ),
        )

        current = EvalResult(
            fixture_id="test",
            ticker="TEST",
            run_at=datetime(2024, 1, 2),
            status=EvalStatus.PASSED,
            metrics=EvalMetrics(
                total_expected_claims=10,
                total_actual_claims=10,
                matched_claims=6,  # Worse
                verification_rate=0.7,
            ),
        )

        comparison = harness.compare_results(baseline, current)

        assert comparison["has_regressions"] is True
        assert len(comparison["regressions"]) > 0

    def test_compare_results_improvements(self, harness):
        """Test detecting improvements."""
        baseline = EvalResult(
            fixture_id="test",
            ticker="TEST",
            run_at=datetime(2024, 1, 1),
            status=EvalStatus.PARTIAL,
            metrics=EvalMetrics(
                total_expected_claims=10,
                total_actual_claims=10,
                matched_claims=6,
            ),
        )

        current = EvalResult(
            fixture_id="test",
            ticker="TEST",
            run_at=datetime(2024, 1, 2),
            status=EvalStatus.PASSED,
            metrics=EvalMetrics(
                total_expected_claims=10,
                total_actual_claims=10,
                matched_claims=9,  # Better
            ),
        )

        comparison = harness.compare_results(baseline, current)

        assert len(comparison["improvements"]) > 0

    def test_save_result(self):
        """Test saving evaluation result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = EvalHarness(results_dir=Path(tmpdir) / "results")

            result = EvalResult(
                fixture_id="save_test",
                ticker="SAVE",
                run_at=datetime(2024, 1, 15, 12, 0, 0),
                status=EvalStatus.PASSED,
                metrics=EvalMetrics(),
            )

            path = harness.save_result(result)

            assert path.exists()
            assert "save_test" in path.name
