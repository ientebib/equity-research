"""
Pinned Fixtures for Deterministic Evaluation.

Provides frozen test data for reproducible pipeline evaluation
without external API calls.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson


@dataclass
class PinnedFixture:
    """A pinned fixture for deterministic testing.

    Contains all data needed to run pipeline without external calls:
    - Company profile and financials
    - SEC filings (10-K, 10-Q excerpts)
    - Earnings call transcripts
    - News articles
    - Expected outputs for validation
    """

    fixture_id: str
    ticker: str
    company_name: str
    created_at: datetime
    version: str  # Fixture schema version

    # Frozen input data
    profile: dict[str, Any] = field(default_factory=dict)
    financials: dict[str, Any] = field(default_factory=dict)
    filings: list[dict[str, Any]] = field(default_factory=list)
    transcripts: list[dict[str, Any]] = field(default_factory=list)
    news: list[dict[str, Any]] = field(default_factory=list)

    # Expected outputs for validation
    expected_claims: list[dict[str, Any]] = field(default_factory=list)
    expected_facts: list[dict[str, Any]] = field(default_factory=list)
    expected_recommendation: str | None = None

    # Metadata
    content_hash: str = ""  # SHA256 of frozen content
    notes: str = ""

    def __post_init__(self) -> None:
        """Calculate content hash if not set."""
        if not self.content_hash:
            self.content_hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """Calculate SHA256 hash of fixture content."""
        content = orjson.dumps(
            {
                "profile": self.profile,
                "financials": self.financials,
                "filings": self.filings,
                "transcripts": self.transcripts,
                "news": self.news,
            },
            option=orjson.OPT_SORT_KEYS,
        )
        return hashlib.sha256(content).hexdigest()[:16]

    def verify_integrity(self) -> bool:
        """Verify fixture content hasn't changed."""
        return self._calculate_hash() == self.content_hash

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "fixture_id": self.fixture_id,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
            "profile": self.profile,
            "financials": self.financials,
            "filings": self.filings,
            "transcripts": self.transcripts,
            "news": self.news,
            "expected_claims": self.expected_claims,
            "expected_facts": self.expected_facts,
            "expected_recommendation": self.expected_recommendation,
            "content_hash": self.content_hash,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PinnedFixture:
        """Create from dict."""
        return cls(
            fixture_id=data["fixture_id"],
            ticker=data["ticker"],
            company_name=data["company_name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            version=data["version"],
            profile=data.get("profile", {}),
            financials=data.get("financials", {}),
            filings=data.get("filings", []),
            transcripts=data.get("transcripts", []),
            news=data.get("news", []),
            expected_claims=data.get("expected_claims", []),
            expected_facts=data.get("expected_facts", []),
            expected_recommendation=data.get("expected_recommendation"),
            content_hash=data.get("content_hash", ""),
            notes=data.get("notes", ""),
        )


class FixtureLoader:
    """Loads and manages pinned fixtures."""

    FIXTURE_VERSION = "1.0"

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        """Initialize loader.

        Args:
            fixtures_dir: Directory containing fixture files.
        """
        self.fixtures_dir = fixtures_dir or Path("tests/fixtures")
        self._cache: dict[str, PinnedFixture] = {}

    def load(self, fixture_id: str) -> PinnedFixture | None:
        """Load a fixture by ID.

        Args:
            fixture_id: Fixture identifier.

        Returns:
            PinnedFixture or None if not found.
        """
        if fixture_id in self._cache:
            return self._cache[fixture_id]

        fixture_path = self.fixtures_dir / f"{fixture_id}.json"
        if not fixture_path.exists():
            return None

        try:
            with open(fixture_path, "rb") as f:
                data = orjson.loads(f.read())
            fixture = PinnedFixture.from_dict(data)
            self._cache[fixture_id] = fixture
            return fixture
        except Exception:
            return None

    def save(self, fixture: PinnedFixture) -> Path:
        """Save a fixture to disk.

        Args:
            fixture: Fixture to save.

        Returns:
            Path to saved file.
        """
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)
        fixture_path = self.fixtures_dir / f"{fixture.fixture_id}.json"

        with open(fixture_path, "wb") as f:
            f.write(orjson.dumps(fixture.to_dict(), option=orjson.OPT_INDENT_2))

        self._cache[fixture.fixture_id] = fixture
        return fixture_path

    def list_fixtures(self) -> list[str]:
        """List available fixture IDs."""
        if not self.fixtures_dir.exists():
            return []

        return [
            p.stem
            for p in self.fixtures_dir.glob("*.json")
            if p.is_file()
        ]

    def create_fixture(
        self,
        fixture_id: str,
        ticker: str,
        company_name: str,
        profile: dict[str, Any],
        financials: dict[str, Any],
        filings: list[dict[str, Any]] | None = None,
        transcripts: list[dict[str, Any]] | None = None,
        news: list[dict[str, Any]] | None = None,
        notes: str = "",
    ) -> PinnedFixture:
        """Create a new fixture.

        Args:
            fixture_id: Unique fixture identifier.
            ticker: Stock ticker.
            company_name: Company name.
            profile: Company profile data.
            financials: Financial data.
            filings: Optional SEC filings.
            transcripts: Optional earnings transcripts.
            news: Optional news articles.
            notes: Optional notes about the fixture.

        Returns:
            Created PinnedFixture.
        """
        from er.types import utc_now

        fixture = PinnedFixture(
            fixture_id=fixture_id,
            ticker=ticker,
            company_name=company_name,
            created_at=utc_now(),
            version=self.FIXTURE_VERSION,
            profile=profile,
            financials=financials,
            filings=filings or [],
            transcripts=transcripts or [],
            news=news or [],
            notes=notes,
        )

        return fixture
