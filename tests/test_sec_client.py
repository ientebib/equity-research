"""
Tests for the SEC EDGAR client.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from er.data.sec_client import SECClient, RateLimiter
from er.evidence.store import EvidenceStore
from er.exceptions import DataFetchError


@pytest.fixture
async def evidence_store(temp_dir: Path) -> EvidenceStore:
    """Create an initialized evidence store for testing."""
    store = EvidenceStore(temp_dir / "cache")
    await store.init()
    yield store
    await store.close()


@pytest.fixture
def sec_client(evidence_store: EvidenceStore, mock_settings: None) -> SECClient:
    """Create SEC client with mocked settings."""
    return SECClient(evidence_store)


class TestRateLimiter:
    """Test rate limiter functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_requests_within_limit(self) -> None:
        """Test that requests within limit proceed immediately."""
        limiter = RateLimiter(max_requests=5, period=1.0)

        # Should be able to make 5 requests immediately
        for _ in range(5):
            await limiter.acquire()

    @pytest.mark.asyncio
    async def test_rate_limiter_delays_when_exceeded(self) -> None:
        """Test that rate limiter delays when limit exceeded."""
        import asyncio

        limiter = RateLimiter(max_requests=2, period=0.1)

        # First two should be immediate
        await limiter.acquire()
        await limiter.acquire()

        # Third should be delayed
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start

        # Should have waited ~0.1 seconds
        assert elapsed >= 0.05  # Some tolerance


class TestSECClientCIKLookup:
    """Test CIK lookup functionality."""

    @pytest.mark.asyncio
    async def test_get_cik_success(
        self, sec_client: SECClient, evidence_store: EvidenceStore
    ) -> None:
        """Test successful CIK lookup."""
        mock_response = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        }

        with patch.object(
            sec_client, "_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = json.dumps(mock_response).encode()

            cik = await sec_client.get_cik("AAPL")

            assert cik == "0000320193"  # Zero-padded to 10 digits
            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cik_caches_result(
        self, sec_client: SECClient
    ) -> None:
        """Test that CIK lookup is cached."""
        mock_response = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }

        with patch.object(
            sec_client, "_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = json.dumps(mock_response).encode()

            # First call
            cik1 = await sec_client.get_cik("AAPL")
            # Second call - should use cache
            cik2 = await sec_client.get_cik("AAPL")

            assert cik1 == cik2
            # Should only fetch once
            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cik_not_found(self, sec_client: SECClient) -> None:
        """Test CIK lookup for unknown ticker."""
        mock_response = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }

        with patch.object(
            sec_client, "_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = json.dumps(mock_response).encode()

            with pytest.raises(DataFetchError) as exc_info:
                await sec_client.get_cik("INVALID")

            assert "not found" in str(exc_info.value).lower()


class TestSECClientCompanyFacts:
    """Test company facts retrieval."""

    @pytest.mark.asyncio
    async def test_get_company_facts(
        self, sec_client: SECClient
    ) -> None:
        """Test fetching company facts."""
        mock_response = {
            "cik": 320193,
            "entityName": "Apple Inc.",
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [{"val": 352583000000}]
                        }
                    }
                }
            }
        }

        with patch.object(
            sec_client, "_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = json.dumps(mock_response).encode()

            facts = await sec_client.get_company_facts("0000320193")

            assert facts["entityName"] == "Apple Inc."
            assert "facts" in facts


class TestSECClientSubmissions:
    """Test submissions retrieval."""

    @pytest.mark.asyncio
    async def test_get_submissions(
        self, sec_client: SECClient
    ) -> None:
        """Test fetching company submissions."""
        mock_response = {
            "cik": "320193",
            "name": "Apple Inc.",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K"],
                    "accessionNumber": ["0001-24-001", "0001-24-002", "0001-24-003"],
                    "filingDate": ["2024-01-01", "2024-02-01", "2024-03-01"],
                    "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm"],
                }
            }
        }

        with patch.object(
            sec_client, "_fetch", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = json.dumps(mock_response).encode()

            submissions = await sec_client.get_submissions("0000320193")

            assert submissions["name"] == "Apple Inc."
            assert "filings" in submissions


class TestSECClientFilingParsing:
    """Test 10-K/10-Q parsing."""

    def test_parse_10k_sections_extracts_business(
        self, sec_client: SECClient
    ) -> None:
        """Test that 10-K parsing extracts business section."""
        html = """
        <html>
        <body>
        ITEM 1. BUSINESS

        Apple Inc. designs, manufactures and markets smartphones,
        personal computers, tablets, wearables and accessories worldwide.

        ITEM 1A. RISK FACTORS

        The Company's business is subject to various risks.

        ITEM 2. PROPERTIES
        </body>
        </html>
        """

        sections = sec_client._parse_10k_sections(html)

        assert "business" in sections
        assert "Apple Inc" in sections["business"] or "smartphones" in sections["business"]

    def test_parse_10k_sections_extracts_risk_factors(
        self, sec_client: SECClient
    ) -> None:
        """Test that 10-K parsing extracts risk factors."""
        html = """
        <html>
        <body>
        ITEM 1A. RISK FACTORS

        Competition in the technology industry is intense.
        Economic conditions may affect consumer spending.

        ITEM 1B. UNRESOLVED STAFF COMMENTS
        </body>
        </html>
        """

        sections = sec_client._parse_10k_sections(html)

        assert "risk_factors" in sections

    def test_parse_10k_sections_extracts_mda(
        self, sec_client: SECClient
    ) -> None:
        """Test that 10-K parsing extracts MD&A."""
        html = """
        <html>
        <body>
        ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS

        Revenue increased 10% year over year.
        Operating margins improved significantly.

        ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES
        </body>
        </html>
        """

        sections = sec_client._parse_10k_sections(html)

        assert "mda" in sections


class TestSECClientIntegration:
    """Integration tests that require mocking full flows."""

    @pytest.mark.asyncio
    async def test_get_recent_10k_full_flow(
        self, sec_client: SECClient
    ) -> None:
        """Test full flow of fetching recent 10-K."""
        # Mock CIK lookup
        cik_response = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }

        # Mock submissions
        submissions_response = {
            "cik": "320193",
            "name": "Apple Inc.",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q"],
                    "accessionNumber": ["0001193125-24-000001", "0001193125-24-000002"],
                    "filingDate": ["2024-01-15", "2024-04-15"],
                    "primaryDocument": ["aapl-10k.htm", "aapl-10q.htm"],
                }
            }
        }

        # Mock filing content
        filing_html = """
        <html>
        <body>
        ITEM 1. BUSINESS
        Apple Inc. designs consumer electronics.
        ITEM 1A. RISK FACTORS
        Various risks exist.
        ITEM 2. PROPERTIES
        </body>
        </html>
        """

        call_count = 0

        async def mock_fetch(url: str, accept: str = "application/json") -> bytes:
            nonlocal call_count
            call_count += 1

            if "company_tickers" in url:
                return json.dumps(cik_response).encode()
            elif "submissions" in url:
                return json.dumps(submissions_response).encode()
            else:
                return filing_html.encode()

        with patch.object(sec_client, "_fetch", side_effect=mock_fetch):
            result = await sec_client.get_recent_10k("AAPL")

            assert result["ticker"] == "AAPL"
            assert result["form"] == "10-K"
            assert "sections" in result
            assert "business" in result["sections"]
