"""
Search providers for web URL discovery.

Decouples URL discovery from reasoning - returns only URLs and snippets,
NOT full page content.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from er.llm.router import LLMRouter, AgentRole
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
    """Protocol for web search providers."""

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
    """Web search using OpenAI's web_search tool.

    Uses a cheap model with web_search tool to discover URLs.
    Returns only URLs and snippets - NOT full page content.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        model: str = "gpt-4o-mini",  # Cheap model for URL discovery
        max_tokens: int = 1200,
    ) -> None:
        """Initialize the search provider.

        Args:
            llm_router: LLM router for API calls.
            model: Model to use (should be cheap for URL discovery).
            max_tokens: Max tokens for response.
        """
        self.llm_router = llm_router
        self.model = model
        self.max_tokens = max_tokens

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
            List of SearchResult objects.
        """
        # Build the search prompt
        prompt_parts = [
            f"Search for: {query}",
            f"Return exactly {max_results} most relevant results.",
        ]

        if recency_days:
            prompt_parts.append(f"Only include results from the last {recency_days} days.")

        if domains:
            prompt_parts.append(f"Focus on these domains: {', '.join(domains)}")

        prompt_parts.append("""
Return results as a JSON object with this exact structure:
{
  "results": [
    {
      "title": "Article title",
      "url": "https://...",
      "snippet": "Brief description...",
      "source": "domain.com"
    }
  ]
}

IMPORTANT: Return ONLY the JSON, no other text.
""")

        prompt = "\n".join(prompt_parts)

        logger.debug("Running web search", query=query, max_results=max_results)

        try:
            # Call OpenAI with web_search tool
            response = await self.llm_router.openai_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                max_tokens=self.max_tokens,
                tools=[{"type": "web_search"}],
                response_format={"type": "json_object"},
            )

            # Parse the response
            content = response.get("content", "")
            if not content:
                logger.warning("Empty response from web search", query=query)
                return []

            # Parse JSON response
            try:
                data = json.loads(content)
                raw_results = data.get("results", [])
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse web search response", error=str(e), content=content[:500])
                return []

            # Convert to SearchResult objects
            results = []
            for item in raw_results[:max_results]:
                try:
                    result = SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("snippet", ""),
                        source=item.get("source", ""),
                    )
                    if result.url:  # Only include results with URLs
                        results.append(result)
                except Exception as e:
                    logger.warning("Failed to parse search result", error=str(e), item=item)

            logger.info(
                "Web search complete",
                query=query,
                results_found=len(results),
            )

            return results

        except Exception as e:
            logger.error("Web search failed", query=query, error=str(e))
            return []

    async def close(self) -> None:
        """Close the provider (no-op for this implementation)."""
        pass
