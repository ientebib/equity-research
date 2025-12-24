"""
Tests for the evidence store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from er.evidence.store import EvidenceStore
from er.types import SourceTier, ToSRisk


@pytest.fixture
async def evidence_store(temp_dir: Path) -> EvidenceStore:
    """Create an initialized evidence store for testing."""
    store = EvidenceStore(temp_dir / "cache")
    await store.init()
    yield store
    await store.close()


class TestEvidenceStoreBasics:
    """Test basic evidence store operations."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, evidence_store: EvidenceStore) -> None:
        """Test storing and retrieving evidence."""
        content = b"Test content for evidence"
        evidence = await evidence_store.store(
            url="https://example.com/test",
            content=content,
            content_type="text/plain",
            snippet="Test content for evidence",
            title="Test Evidence",
            tos_risk=ToSRisk.LOW,
            source_tier=SourceTier.NEWS,
        )

        assert evidence.evidence_id.startswith("ev_")
        assert evidence.source_url == "https://example.com/test"
        assert evidence.content_type == "text/plain"
        assert evidence.snippet == "Test content for evidence"
        assert evidence.title == "Test Evidence"
        assert evidence.tos_risk == ToSRisk.LOW
        assert evidence.source_tier == SourceTier.NEWS
        assert evidence.blob_path is not None

        # Retrieve by ID
        retrieved = await evidence_store.get(evidence.evidence_id)
        assert retrieved is not None
        assert retrieved.evidence_id == evidence.evidence_id
        assert retrieved.source_url == evidence.source_url
        assert retrieved.content_hash == evidence.content_hash

    @pytest.mark.asyncio
    async def test_get_blob(self, evidence_store: EvidenceStore) -> None:
        """Test retrieving blob content."""
        content = b"Binary content here"
        evidence = await evidence_store.store(
            url="https://example.com/binary",
            content=content,
            content_type="application/octet-stream",
            snippet="Binary content",
        )

        blob = await evidence_store.get_blob(evidence.evidence_id)
        assert blob == content

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that getting nonexistent evidence returns None."""
        result = await evidence_store.get("ev_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_blob_nonexistent_returns_none(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that getting nonexistent blob returns None."""
        result = await evidence_store.get_blob("ev_nonexistent")
        assert result is None


class TestEvidenceStoreDuplication:
    """Test duplicate content handling."""

    @pytest.mark.asyncio
    async def test_duplicate_content_reuses_blob(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that duplicate content reuses the same blob file."""
        content = b"Same content"

        # Store same content twice
        ev1 = await evidence_store.store(
            url="https://example.com/first",
            content=content,
            content_type="text/plain",
            snippet="Same content",
        )

        ev2 = await evidence_store.store(
            url="https://example.com/second",
            content=content,
            content_type="text/plain",
            snippet="Same content again",
        )

        # Should have same hash and blob path
        assert ev1.content_hash == ev2.content_hash
        assert ev1.blob_path == ev2.blob_path

        # But different evidence IDs
        assert ev1.evidence_id != ev2.evidence_id

        # Both should be retrievable
        retrieved1 = await evidence_store.get(ev1.evidence_id)
        retrieved2 = await evidence_store.get(ev2.evidence_id)
        assert retrieved1 is not None
        assert retrieved2 is not None

    @pytest.mark.asyncio
    async def test_different_content_different_blobs(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that different content creates different blobs."""
        ev1 = await evidence_store.store(
            url="https://example.com/a",
            content=b"Content A",
            content_type="text/plain",
            snippet="A",
        )

        ev2 = await evidence_store.store(
            url="https://example.com/b",
            content=b"Content B",
            content_type="text/plain",
            snippet="B",
        )

        assert ev1.content_hash != ev2.content_hash
        assert ev1.blob_path != ev2.blob_path


class TestEvidenceStoreSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_finds_matching_snippets(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that search finds evidence by snippet content."""
        await evidence_store.store(
            url="https://example.com/apple",
            content=b"Apple content",
            content_type="text/plain",
            snippet="Apple Inc is a technology company",
        )

        await evidence_store.store(
            url="https://example.com/google",
            content=b"Google content",
            content_type="text/plain",
            snippet="Google LLC is a search company",
        )

        results = await evidence_store.search("Apple")
        assert len(results) == 1
        assert "Apple" in results[0].snippet

        results = await evidence_store.search("company")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_respects_limit(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that search respects limit parameter."""
        # Store multiple items
        for i in range(10):
            await evidence_store.store(
                url=f"https://example.com/{i}",
                content=f"Content {i}".encode(),
                content_type="text/plain",
                snippet=f"Test item {i}",
            )

        results = await evidence_store.search("item", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_no_results(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test that search returns empty list for no matches."""
        await evidence_store.store(
            url="https://example.com/test",
            content=b"Test",
            content_type="text/plain",
            snippet="Test content",
        )

        results = await evidence_store.search("nonexistent")
        assert results == []


class TestEvidenceStoreListBySource:
    """Test listing by source pattern."""

    @pytest.mark.asyncio
    async def test_list_by_source_pattern(
        self, evidence_store: EvidenceStore
    ) -> None:
        """Test listing evidence by source URL pattern."""
        await evidence_store.store(
            url="https://sec.gov/filing/123",
            content=b"SEC filing",
            content_type="text/html",
            snippet="SEC filing content",
            source_tier=SourceTier.OFFICIAL,
        )

        await evidence_store.store(
            url="https://sec.gov/filing/456",
            content=b"Another SEC filing",
            content_type="text/html",
            snippet="Another SEC filing",
            source_tier=SourceTier.OFFICIAL,
        )

        await evidence_store.store(
            url="https://news.com/article",
            content=b"News",
            content_type="text/html",
            snippet="News article",
            source_tier=SourceTier.NEWS,
        )

        # List SEC filings
        results = await evidence_store.list_by_source("%sec.gov%")
        assert len(results) == 2

        # List news
        results = await evidence_store.list_by_source("%news.com%")
        assert len(results) == 1


class TestEvidenceStoreStats:
    """Test statistics functionality."""

    @pytest.mark.asyncio
    async def test_count(self, evidence_store: EvidenceStore) -> None:
        """Test counting evidence records."""
        assert await evidence_store.count() == 0

        await evidence_store.store(
            url="https://example.com/1",
            content=b"1",
            content_type="text/plain",
            snippet="1",
        )
        assert await evidence_store.count() == 1

        await evidence_store.store(
            url="https://example.com/2",
            content=b"2",
            content_type="text/plain",
            snippet="2",
        )
        assert await evidence_store.count() == 2

    @pytest.mark.asyncio
    async def test_stats(self, evidence_store: EvidenceStore) -> None:
        """Test statistics gathering."""
        await evidence_store.store(
            url="https://sec.gov/filing",
            content=b"SEC",
            content_type="text/html",
            snippet="SEC",
            source_tier=SourceTier.OFFICIAL,
            tos_risk=ToSRisk.NONE,
        )

        await evidence_store.store(
            url="https://news.com/article",
            content=b"News",
            content_type="text/html",
            snippet="News",
            source_tier=SourceTier.NEWS,
            tos_risk=ToSRisk.LOW,
        )

        stats = await evidence_store.stats()

        assert stats["total"] == 2
        assert stats["by_tier"]["official"] == 1
        assert stats["by_tier"]["news"] == 1
        assert stats["by_tos_risk"]["none"] == 1
        assert stats["by_tos_risk"]["low"] == 1
