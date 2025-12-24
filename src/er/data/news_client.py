"""
News and web search client.

Abstraction for web search. Currently implemented as stubs that return
empty results. The actual implementation will use LLM web search tools.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from er.evidence.store import EvidenceStore
from er.logging import get_logger
from er.types import SourceTier, ToSRisk

logger = get_logger(__name__)

# Major news sites with low ToS risk
LOW_RISK_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "marketwatch.com",
    "finance.yahoo.com",
    "seekingalpha.com",
    "fool.com",
    "investopedia.com",
    "barrons.com",
    "businessinsider.com",
}


class NewsClient:
    """Client for news and web search.

    Currently a stub implementation. Actual web search will be
    implemented using LLM web search tools in later phases.
    """

    def __init__(self, evidence_store: EvidenceStore) -> None:
        """Initialize news client.

        Args:
            evidence_store: Store for persisting fetched content.
        """
        self.evidence_store = evidence_store

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for news articles.

        Currently a stub that returns empty results.
        Will be implemented with LLM web search tools.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of search results with: url, title, snippet, published_at
        """
        logger.info(
            "News search (stub)",
            query=query,
            max_results=max_results,
        )

        # Stub: Return empty results
        # In future phases, this will call LLM web search tools
        return []

    async def fetch_url(self, url: str) -> str | None:
        """Fetch full content from a URL.

        Currently a stub that returns None.
        Will be implemented with proper web fetching.

        Args:
            url: URL to fetch.

        Returns:
            Page content as text, or None if unavailable.
        """
        logger.info("URL fetch (stub)", url=url)

        # Stub: Return None
        # In future phases, this will fetch and parse web pages
        return None

    def get_tos_risk(self, url: str) -> ToSRisk:
        """Determine Terms of Service risk level for a URL.

        Args:
            url: URL to check.

        Returns:
            ToSRisk level based on domain.
        """
        from urllib.parse import urlparse

        try:
            domain = urlparse(url).netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]

            # Check against known low-risk domains
            if domain in LOW_RISK_DOMAINS:
                return ToSRisk.LOW

            # SEC and government sites are no risk
            if domain.endswith(".gov") or domain.endswith(".sec.gov"):
                return ToSRisk.NONE

            # Company IR sites are low risk
            if "investor" in domain or "ir." in domain:
                return ToSRisk.LOW

            # Default to medium for unknown sites
            return ToSRisk.MEDIUM

        except Exception:
            return ToSRisk.MEDIUM

    def get_source_tier(self, url: str) -> SourceTier:
        """Determine source tier for a URL.

        Args:
            url: URL to classify.

        Returns:
            SourceTier based on domain type.
        """
        from urllib.parse import urlparse

        try:
            domain = urlparse(url).netloc.lower()

            # Official sources
            if domain.endswith(".gov"):
                return SourceTier.OFFICIAL

            # Company IR sites
            if "investor" in domain or "ir." in domain:
                return SourceTier.OFFICIAL

            # Major financial news
            if domain.replace("www.", "") in LOW_RISK_DOMAINS:
                return SourceTier.NEWS

            # Default to other
            return SourceTier.OTHER

        except Exception:
            return SourceTier.OTHER

    async def search_company_news(
        self,
        ticker: str,
        company_name: str | None = None,
        days: int = 30,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for recent news about a company.

        Convenience method that constructs appropriate search queries.

        Args:
            ticker: Stock ticker symbol.
            company_name: Company name (optional, improves results).
            days: Number of days to look back.
            max_results: Maximum results to return.

        Returns:
            List of news results.
        """
        # Build search query
        query_parts = [ticker]
        if company_name:
            query_parts.append(company_name)
        query_parts.append("stock news")

        query = " ".join(query_parts)

        return await self.search(query, max_results)

    async def search_earnings_news(
        self,
        ticker: str,
        quarter: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search for earnings-related news.

        Args:
            ticker: Stock ticker symbol.
            quarter: Quarter (Q1, Q2, Q3, Q4).
            year: Fiscal year.

        Returns:
            List of earnings news results.
        """
        query_parts = [ticker, "earnings"]
        if quarter and year:
            query_parts.append(f"{quarter} {year}")

        query = " ".join(query_parts)

        return await self.search(query, max_results=10)
