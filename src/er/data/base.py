"""
Base classes for data fetching.

This module will implement:
- DataFetcher: Abstract base class for data source fetchers
  - Async HTTP client with retry logic (tenacity)
  - Rate limiting per source
  - Caching integration
  - Error handling with structured exceptions

- FetchResult: Result of a fetch operation
  - raw_data, parsed_data, evidence_ids
  - fetch_time, cache_hit

- RateLimiter: Token bucket rate limiter
  - Per-source rate limits (SEC: 10 req/sec)
  - Async-aware

Concrete implementations in submodules:
- sec.py: SEC EDGAR fetcher (10-K, 10-Q, 8-K, DEF 14A)
- market.py: Market data fetcher (yfinance wrapper)
- transcripts.py: Earnings call transcript fetcher (FMP, Finnhub)
- news.py: News fetcher (with ToS-aware scraping)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataFetcher(ABC):
    """Abstract base class for data source fetchers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of this data source."""
        ...

    @abstractmethod
    async def fetch(self, identifier: str, **kwargs: Any) -> Any:
        """Fetch data for the given identifier."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections."""
        ...
