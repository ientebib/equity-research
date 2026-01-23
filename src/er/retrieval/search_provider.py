"""
Search providers for web URL discovery.

NOTE: This module is deprecated for Anthropic-only operation.
Use AnthropicResearcher from anthropic_research.py instead,
which uses Claude's native web_search tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from er.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result (URL + metadata, NOT full content)."""

    title: str
    url: str
    snippet: str
    source: str = ""  # Domain or source name
    published_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


class SearchProvider(Protocol):
    """Protocol for web search providers.

    NOTE: For Anthropic-only operation, use AnthropicResearcher instead.
    """

    async def search(
        self,
        query: str,
        max_results: int = 5,
        recency_days: int | None = None,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the web for relevant URLs.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            recency_days: Only return results from the last N days.
            domains: Restrict search to specific domains.

        Returns:
            List of SearchResult objects (URLs + snippets, NOT full content).
        """
        ...


class OpenAIWebSearchProvider:
    """DEPRECATED: Use AnthropicResearcher instead.

    This class is stubbed for backwards compatibility.
    OpenAI has been removed from this Anthropic-only codebase.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the search provider (stub)."""
        logger.warning(
            "OpenAIWebSearchProvider is deprecated. "
            "Use AnthropicResearcher from anthropic_research.py instead."
        )

    async def search(
        self,
        query: str,
        max_results: int = 5,
        recency_days: int | None = None,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the web (stub - always returns empty).

        Use AnthropicResearcher.research() instead.
        """
        raise NotImplementedError(
            "OpenAIWebSearchProvider is deprecated. "
            "Use AnthropicResearcher from anthropic_research.py instead."
        )

    async def close(self) -> None:
        """Close the provider (no-op)."""
        pass


class GeminiWebSearchProvider:
    """DEPRECATED: Use AnthropicResearcher instead.

    This class is stubbed for backwards compatibility.
    Gemini has been removed from this Anthropic-only codebase.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the search provider (stub)."""
        logger.warning(
            "GeminiWebSearchProvider is deprecated. "
            "Use AnthropicResearcher from anthropic_research.py instead."
        )

    async def search(
        self,
        query: str,
        max_results: int = 5,
        recency_days: int | None = None,
        domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the web (stub - always returns empty).

        Use AnthropicResearcher.research() instead.
        """
        raise NotImplementedError(
            "GeminiWebSearchProvider is deprecated. "
            "Use AnthropicResearcher from anthropic_research.py instead."
        )

    async def close(self) -> None:
        """Close the provider (no-op)."""
        pass
