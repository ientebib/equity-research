"""
SEC EDGAR client for fetching SEC filings.

Implements proper identification and rate limiting per SEC requirements.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from er.config import get_settings
from er.evidence.store import EvidenceStore
from er.exceptions import DataFetchError
from er.logging import get_logger
from er.types import SourceTier, ToSRisk

logger = get_logger(__name__)

# SEC EDGAR API base URLs
SEC_DATA_BASE = "https://data.sec.gov"
SEC_EDGAR_BASE = "https://www.sec.gov"

# SEC requires max 10 requests per second
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_PERIOD = 1.0  # seconds


class RateLimiter:
    """Simple rate limiter for SEC API compliance."""

    def __init__(self, max_requests: int, period: float) -> None:
        self.max_requests = max_requests
        self.period = period
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until we can make a request within rate limits."""
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # Remove timestamps older than the period
            self._timestamps = [
                ts for ts in self._timestamps if now - ts < self.period
            ]

            if len(self._timestamps) >= self.max_requests:
                # Wait until oldest timestamp expires
                sleep_time = self.period - (now - self._timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    self._timestamps = self._timestamps[1:]

            self._timestamps.append(asyncio.get_event_loop().time())


class SECClient:
    """Client for fetching SEC EDGAR filings.

    Must send User-Agent header with SEC_USER_AGENT from config.
    Rate limited to 10 requests/second per SEC requirements.
    """

    def __init__(self, evidence_store: EvidenceStore) -> None:
        """Initialize SEC client.

        Args:
            evidence_store: Store for persisting fetched content.
        """
        self.evidence_store = evidence_store
        self.settings = get_settings()
        self._rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD)
        self._client: httpx.AsyncClient | None = None
        self._cik_cache: dict[str, str] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with proper headers."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.settings.SEC_USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _fetch(self, url: str, accept: str = "application/json") -> bytes:
        """Fetch URL with rate limiting and retries.

        Args:
            url: URL to fetch.
            accept: Accept header value.

        Returns:
            Response content as bytes.

        Raises:
            DataFetchError: If fetch fails after retries.
        """
        await self._rate_limiter.acquire()

        client = await self._get_client()

        try:
            response = await client.get(url, headers={"Accept": accept})
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limited by SEC, backing off", url=url)
                await asyncio.sleep(2.0)
            raise
        except Exception as e:
            raise DataFetchError(
                f"Failed to fetch {url}",
                context={"url": url, "error": str(e)},
            ) from e

    async def get_cik(self, ticker: str) -> str:
        """Look up CIK from ticker symbol.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            CIK number as string (zero-padded to 10 digits).

        Raises:
            DataFetchError: If ticker not found or maps to multiple CIKs.
        """
        ticker = ticker.upper()

        # Check cache
        if ticker in self._cik_cache:
            return self._cik_cache[ticker]

        # Fetch ticker mapping (from www.sec.gov, not data.sec.gov)
        url = f"{SEC_EDGAR_BASE}/files/company_tickers.json"
        content = await self._fetch(url)

        import orjson

        data = orjson.loads(content)

        # Find ticker in results
        matches = []
        for entry in data.values():
            if entry.get("ticker") == ticker:
                cik = str(entry["cik_str"]).zfill(10)
                matches.append(cik)

        if not matches:
            raise DataFetchError(
                f"Ticker {ticker} not found in SEC database",
                context={"ticker": ticker},
            )

        if len(matches) > 1:
            raise DataFetchError(
                f"Ticker {ticker} maps to multiple CIKs: {matches}",
                context={"ticker": ticker, "ciks": matches},
            )

        cik = matches[0]
        self._cik_cache[ticker] = cik
        logger.info("Resolved ticker to CIK", ticker=ticker, cik=cik)

        return cik

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        """Get XBRL company facts from SEC API.

        Args:
            cik: Company CIK (10-digit zero-padded).

        Returns:
            Dict with company facts including financial data.
        """
        url = f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json"

        content = await self._fetch(url)

        import orjson

        data = orjson.loads(content)

        # Store in evidence
        await self.evidence_store.store(
            url=url,
            content=content,
            content_type="application/json",
            snippet=f"XBRL company facts for CIK {cik}",
            title=f"SEC Company Facts - {data.get('entityName', cik)}",
            tos_risk=ToSRisk.NONE,
            source_tier=SourceTier.OFFICIAL,
        )

        return data

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        """Get company submissions (filing history) from SEC API.

        Args:
            cik: Company CIK (10-digit zero-padded).

        Returns:
            Dict with submission history including recent filings.
        """
        url = f"{SEC_DATA_BASE}/submissions/CIK{cik}.json"

        content = await self._fetch(url)

        import orjson

        data = orjson.loads(content)

        # Store in evidence
        await self.evidence_store.store(
            url=url,
            content=content,
            content_type="application/json",
            snippet=f"SEC submissions for CIK {cik}",
            title=f"SEC Submissions - {data.get('name', cik)}",
            tos_risk=ToSRisk.NONE,
            source_tier=SourceTier.OFFICIAL,
        )

        return data

    async def get_filing_text(self, accession_number: str, filename: str) -> str:
        """Get raw text of a specific filing document.

        Args:
            accession_number: SEC accession number (e.g., "0001193125-24-123456").
            filename: Name of the file within the filing.

        Returns:
            Raw text content of the filing.
        """
        # Format accession number for URL (remove dashes)
        accession_formatted = accession_number.replace("-", "")
        url = f"{SEC_EDGAR_BASE}/Archives/edgar/data/{accession_formatted[:10]}/{accession_formatted}/{filename}"

        content = await self._fetch(url, accept="text/html")
        text = content.decode("utf-8", errors="replace")

        # Store in evidence
        await self.evidence_store.store(
            url=url,
            content=content,
            content_type="text/html",
            snippet=text[:2000],
            title=f"SEC Filing {accession_number} - {filename}",
            tos_risk=ToSRisk.NONE,
            source_tier=SourceTier.OFFICIAL,
        )

        return text

    async def get_recent_10k(self, ticker: str) -> dict[str, Any]:
        """Get most recent 10-K filing with extracted sections.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with filing metadata and extracted sections.
        """
        cik = await self.get_cik(ticker)
        submissions = await self.get_submissions(cik)

        # Find most recent 10-K
        recent_filings = submissions.get("filings", {}).get("recent", {})
        forms = recent_filings.get("form", [])
        accessions = recent_filings.get("accessionNumber", [])
        filing_dates = recent_filings.get("filingDate", [])
        primary_docs = recent_filings.get("primaryDocument", [])

        filing_10k = None
        for i, form in enumerate(forms):
            if form in ("10-K", "10-K/A"):
                filing_10k = {
                    "form": form,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                }
                break

        if not filing_10k:
            raise DataFetchError(
                f"No 10-K found for {ticker}",
                context={"ticker": ticker, "cik": cik},
            )

        logger.info(
            "Found 10-K filing",
            ticker=ticker,
            accession=filing_10k["accession_number"],
            date=filing_10k["filing_date"],
        )

        # Fetch the filing text
        filing_text = await self.get_filing_text(
            filing_10k["accession_number"],
            filing_10k["primary_document"],
        )

        # Parse and extract sections
        sections = self._parse_10k_sections(filing_text)

        return {
            "ticker": ticker,
            "cik": cik,
            "form": filing_10k["form"],
            "accession_number": filing_10k["accession_number"],
            "filing_date": filing_10k["filing_date"],
            "sections": sections,
        }

    async def get_recent_10q(self, ticker: str) -> dict[str, Any]:
        """Get most recent 10-Q filing with extracted sections.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with filing metadata and extracted sections.
        """
        cik = await self.get_cik(ticker)
        submissions = await self.get_submissions(cik)

        # Find most recent 10-Q
        recent_filings = submissions.get("filings", {}).get("recent", {})
        forms = recent_filings.get("form", [])
        accessions = recent_filings.get("accessionNumber", [])
        filing_dates = recent_filings.get("filingDate", [])
        primary_docs = recent_filings.get("primaryDocument", [])

        filing_10q = None
        for i, form in enumerate(forms):
            if form in ("10-Q", "10-Q/A"):
                filing_10q = {
                    "form": form,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                }
                break

        if not filing_10q:
            raise DataFetchError(
                f"No 10-Q found for {ticker}",
                context={"ticker": ticker, "cik": cik},
            )

        logger.info(
            "Found 10-Q filing",
            ticker=ticker,
            accession=filing_10q["accession_number"],
            date=filing_10q["filing_date"],
        )

        # Fetch the filing text
        filing_text = await self.get_filing_text(
            filing_10q["accession_number"],
            filing_10q["primary_document"],
        )

        # Parse and extract sections
        sections = self._parse_10q_sections(filing_text)

        return {
            "ticker": ticker,
            "cik": cik,
            "form": filing_10q["form"],
            "accession_number": filing_10q["accession_number"],
            "filing_date": filing_10q["filing_date"],
            "sections": sections,
        }

    def _parse_10k_sections(self, html: str) -> dict[str, str]:
        """Parse 10-K HTML to extract key sections.

        Extracts:
        - Item 1: Business description
        - Item 1A: Risk factors
        - Item 7: MD&A
        - Segment information
        - Revenue breakdown

        Args:
            html: Raw HTML content of 10-K.

        Returns:
            Dict mapping section names to extracted text.
        """
        soup = BeautifulSoup(html, "lxml")

        # Get all text
        text = soup.get_text(separator="\n", strip=True)

        sections: dict[str, str] = {}

        # Define section patterns
        section_patterns = {
            "business": r"(?:ITEM\s*1[.\s]*(?:BUSINESS|Description of Business))(.+?)(?=ITEM\s*1A|ITEM\s*2)",
            "risk_factors": r"(?:ITEM\s*1A[.\s]*(?:RISK\s*FACTORS))(.+?)(?=ITEM\s*1B|ITEM\s*2)",
            "mda": r"(?:ITEM\s*7[.\s]*(?:MANAGEMENT.S\s*DISCUSSION|MD&A))(.+?)(?=ITEM\s*7A|ITEM\s*8)",
        }

        for section_name, pattern in section_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                section_text = match.group(1).strip()
                # Truncate very long sections
                if len(section_text) > 50000:
                    section_text = section_text[:50000] + "\n... [truncated]"
                sections[section_name] = section_text

        # Try to find segment information
        segment_patterns = [
            r"(?:Segment\s+Information|Operating\s+Segments|Reportable\s+Segments)(.+?)(?=\n\n\n|\Z)",
            r"(?:Note\s+\d+[.:]\s*Segment)(.+?)(?=Note\s+\d+|\Z)",
        ]

        for pattern in segment_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                sections["segments"] = match.group(1).strip()[:20000]
                break

        # Try to find revenue breakdown
        revenue_patterns = [
            r"(?:Revenue\s+(?:by|from)\s+(?:Geography|Region|Product|Segment))(.+?)(?=\n\n\n|\Z)",
            r"(?:Disaggregation\s+of\s+Revenue)(.+?)(?=\n\n\n|\Z)",
        ]

        for pattern in revenue_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                sections["revenue_breakdown"] = match.group(1).strip()[:20000]
                break

        logger.info(
            "Parsed 10-K sections",
            sections=list(sections.keys()),
            total_chars=sum(len(s) for s in sections.values()),
        )

        return sections

    def _parse_10q_sections(self, html: str) -> dict[str, str]:
        """Parse 10-Q HTML to extract key sections.

        Args:
            html: Raw HTML content of 10-Q.

        Returns:
            Dict mapping section names to extracted text.
        """
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator="\n", strip=True)

        sections: dict[str, str] = {}

        # 10-Q has different item numbering
        section_patterns = {
            "mda": r"(?:ITEM\s*2[.\s]*(?:MANAGEMENT.S\s*DISCUSSION|MD&A))(.+?)(?=ITEM\s*3|ITEM\s*4)",
            "risk_factors": r"(?:ITEM\s*1A[.\s]*(?:RISK\s*FACTORS))(.+?)(?=ITEM\s*2|PART\s*II)",
        }

        for section_name, pattern in section_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                section_text = match.group(1).strip()
                if len(section_text) > 30000:
                    section_text = section_text[:30000] + "\n... [truncated]"
                sections[section_name] = section_text

        logger.info(
            "Parsed 10-Q sections",
            sections=list(sections.keys()),
            total_chars=sum(len(s) for s in sections.values()),
        )

        return sections
