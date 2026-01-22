"""
Web page fetcher with text extraction.

Fetches URLs via HTTP, extracts readable text, and stores in EvidenceStore.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from er.evidence.store import EvidenceStore
from er.logging import get_logger
from er.security.sanitizer import InputSanitizer, ThreatLevel
from er.types import Evidence, SourceTier, ToSRisk

logger = get_logger(__name__)

# User agent for web requests
USER_AGENT = "EquityResearchBot/1.0 (+https://github.com/equity-research)"

# Request timeout
REQUEST_TIMEOUT = 30.0

# Max content size to fetch (10MB)
MAX_CONTENT_SIZE = 10 * 1024 * 1024


@dataclass
class FetchResult:
    """Result of fetching a URL."""

    url: str
    evidence_id: str
    title: str
    text: str  # Extracted text content
    content_hash: str
    success: bool
    error: str | None = None


class WebFetcher:
    """Fetches web pages and stores them as evidence.

    Features:
    - HTTP fetching with timeouts and retries
    - Text extraction using BeautifulSoup
    - Caching/deduplication via EvidenceStore
    - Source tier and ToS risk classification
    """

    # Domain classifications for source tier
    HIGH_QUALITY_DOMAINS = {
        "sec.gov", "investor.com", "reuters.com", "bloomberg.com",
        "wsj.com", "ft.com", "nytimes.com", "cnbc.com",
    }

    INSTITUTIONAL_DOMAINS = {
        "morningstar.com", "seekingalpha.com", "fool.com",
        "zacks.com", "benzinga.com",
    }

    # Domains with high ToS risk (may not allow scraping)
    HIGH_TOS_RISK_DOMAINS = {
        "reuters.com", "bloomberg.com", "wsj.com", "ft.com",
    }

    def __init__(
        self,
        evidence_store: EvidenceStore,
        timeout: float = REQUEST_TIMEOUT,
        max_retries: int = 2,
    ) -> None:
        """Initialize the fetcher.

        Args:
            evidence_store: Store for persisting fetched content.
            timeout: Request timeout in seconds.
            max_retries: Number of retry attempts on failure.
        """
        self.evidence_store = evidence_store
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None
        self._sanitizer = InputSanitizer(max_length=100000)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _classify_source_tier(self, url: str) -> SourceTier:
        """Classify the source tier based on domain."""
        domain = urlparse(url).netloc.lower()
        # Remove www prefix
        if domain.startswith("www."):
            domain = domain[4:]

        if domain in self.HIGH_QUALITY_DOMAINS or domain == "sec.gov":
            return SourceTier.OFFICIAL
        elif domain in self.INSTITUTIONAL_DOMAINS:
            return SourceTier.INSTITUTIONAL
        else:
            return SourceTier.NEWS

    def _classify_tos_risk(self, url: str) -> ToSRisk:
        """Classify ToS risk based on domain."""
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        if domain in self.HIGH_TOS_RISK_DOMAINS:
            return ToSRisk.HIGH
        elif domain in self.INSTITUTIONAL_DOMAINS:
            return ToSRisk.MEDIUM
        else:
            return ToSRisk.LOW

    def _extract_text(self, html: str, url: str = "") -> tuple[str, str]:
        """Extract readable text from HTML and sanitize for prompt injection.

        Args:
            html: Raw HTML content.
            url: Source URL for logging.

        Returns:
            Tuple of (title, sanitized_extracted_text).
        """
        soup = BeautifulSoup(html, "html.parser")

        # Get title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Remove script and style elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
            element.decompose()

        # Try to find main content area
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            main = soup

        # Get text
        text = main.get_text(separator="\n", strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)

        # Truncate if too long (keep first 50k chars)
        if len(text) > 50000:
            text = text[:50000] + "\n...[truncated]"

        # Sanitize extracted text to prevent prompt injection
        sanitization_result = self._sanitizer.sanitize(text, source=url or "web_fetch")

        if sanitization_result.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL):
            logger.warning(
                "High threat content detected in web fetch",
                url=url,
                threat_level=sanitization_result.threat_level.value,
                threats=sanitization_result.threats_detected,
            )

        # Sanitize title too
        title_sanitized = self._sanitizer.sanitize(title, source=f"{url}_title")

        return title_sanitized.sanitized_text, sanitization_result.sanitized_text

    async def fetch(
        self,
        url: str,
        skip_if_cached: bool = True,
    ) -> FetchResult:
        """Fetch a URL and store as evidence.

        Args:
            url: URL to fetch.
            skip_if_cached: If True, return cached evidence if exists.

        Returns:
            FetchResult with evidence_id and extracted text.
        """
        # Check cache first
        if skip_if_cached:
            existing = await self.evidence_store.find_by_url(url)
            if existing:
                logger.debug("Using cached evidence", url=url, evidence_id=existing.evidence_id)
                # Retrieve the full content and re-extract text
                cached_content = await self.evidence_store.get_blob(existing.evidence_id)
                if cached_content and existing.content_type == "text/html":
                    # Re-extract full text from cached HTML (with sanitization)
                    html = cached_content.decode("utf-8", errors="replace")
                    title, text = self._extract_text(html, url=url)
                else:
                    # Fallback to snippet if content not available
                    title = existing.title or ""
                    text = existing.snippet or ""
                return FetchResult(
                    url=url,
                    evidence_id=existing.evidence_id,
                    title=title,
                    text=text,
                    content_hash=existing.content_hash,
                    success=True,
                )

        # Fetch the URL
        client = await self._get_client()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()

                # Check content size
                content_length = int(response.headers.get("content-length", 0))
                if content_length > MAX_CONTENT_SIZE:
                    return FetchResult(
                        url=url,
                        evidence_id="",
                        title="",
                        text="",
                        content_hash="",
                        success=False,
                        error=f"Content too large: {content_length} bytes",
                    )

                html = response.text
                break

            except httpx.HTTPError as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    logger.warning(
                        "Fetch attempt failed, retrying",
                        url=url,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                continue

        else:
            logger.error("All fetch attempts failed", url=url, error=last_error)
            return FetchResult(
                url=url,
                evidence_id="",
                title="",
                text="",
                content_hash="",
                success=False,
                error=last_error,
            )

        # Extract text (with sanitization)
        title, text = self._extract_text(html, url=url)

        # Compute content hash
        content_hash = hashlib.sha256(html.encode()).hexdigest()

        # Classify source
        source_tier = self._classify_source_tier(url)
        tos_risk = self._classify_tos_risk(url)

        # Store raw HTML as evidence
        evidence = await self.evidence_store.store(
            url=url,
            content=html.encode(),
            content_type="text/html",
            source_tier=source_tier,
            tos_risk=tos_risk,
            title=title,
            snippet=text[:500] if text else "",
        )

        logger.info(
            "Fetched and stored URL",
            url=url,
            evidence_id=evidence.evidence_id,
            title=title[:100] if title else "",
            text_length=len(text),
        )

        return FetchResult(
            url=url,
            evidence_id=evidence.evidence_id,
            title=title,
            text=text,
            content_hash=content_hash,
            success=True,
        )

    async def fetch_many(
        self,
        urls: list[str],
        skip_if_cached: bool = True,
    ) -> list[FetchResult]:
        """Fetch multiple URLs concurrently.

        Args:
            urls: List of URLs to fetch.
            skip_if_cached: If True, skip URLs already in cache.

        Returns:
            List of FetchResult objects.
        """
        import asyncio

        # Limit concurrency
        semaphore = asyncio.Semaphore(5)

        async def fetch_with_semaphore(url: str) -> FetchResult:
            async with semaphore:
                return await self.fetch(url, skip_if_cached=skip_if_cached)

        results = await asyncio.gather(
            *[fetch_with_semaphore(url) for url in urls],
            return_exceptions=True,
        )

        # Convert exceptions to failed results
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(FetchResult(
                    url=urls[i],
                    evidence_id="",
                    title="",
                    text="",
                    content_hash="",
                    success=False,
                    error=str(result),
                ))
            else:
                processed.append(result)

        return processed
