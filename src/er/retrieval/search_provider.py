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
from urllib.parse import parse_qs, urlparse

from er.llm.base import LLMRequest
from er.llm.openai_client import OpenAIClient
from er.llm.gemini_client import GeminiClient
from er.llm.router import LLMRouter, AgentRole
from er.logging import get_logger

logger = get_logger(__name__)


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None


def _normalize_grounding_url(url: str) -> str:
    if "grounding-api-redirect" not in url:
        return url
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        redirected = params.get("url", [])
        if redirected:
            return redirected[0]
    except Exception:
        return url
    return url


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
        model: str = "gpt-4o-mini",  # Cheap model with web_search support
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
            if hasattr(self.llm_router, "_has_provider_key") and not self.llm_router._has_provider_key("openai"):
                logger.error("OpenAI API key missing; web search unavailable", query=query)
                return []

            try:
                client = self.llm_router._get_client("openai")
            except Exception as e:
                logger.error("Failed to initialize OpenAI client for web search", error=str(e), query=query)
                return []

            if not isinstance(client, OpenAIClient):
                logger.error("Web search requires OpenAI client", query=query)
                return []

            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                max_tokens=self.max_tokens,
            )
            response = await client.complete_with_web_search(
                request,
                reasoning_effort="low",
            )

            # Parse the response
            content = response.content
            if not content:
                logger.warning("Empty response from web search", query=query)
                return []

            # Parse JSON response
            data = _extract_json(content)
            if not data:
                logger.warning("Failed to parse web search response", content=content[:500])
                return []
            raw_results = data.get("results", [])

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


class GeminiWebSearchProvider:
    """Web search using Gemini grounding (Google Search)."""

    def __init__(
        self,
        llm_router: LLMRouter,
        model: str = "gemini-2.5-flash",
        max_tokens: int = 1200,
    ) -> None:
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

        try:
            client, model = self.llm_router.get_client_and_model(AgentRole.WORKHORSE)
            if not isinstance(client, GeminiClient):
                logger.error("Gemini client not available for Google search", query=query)
                return []

            request = LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                model=model if model.startswith("gemini-") else self.model,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            response = await client.complete_with_grounding(
                request,
                enable_google_search=True,
            )
            raw_results = []
            metadata = response.metadata or {}
            grounding_chunks = metadata.get("grounding_chunks") or []
            if grounding_chunks:
                raw_results = []
                for chunk in grounding_chunks:
                    url = _normalize_grounding_url(str(chunk.get("url", "")))
                    raw_results.append({
                        "title": chunk.get("title", ""),
                        "url": url,
                        "snippet": chunk.get("snippet", ""),
                        "source": chunk.get("source", ""),
                    })
            else:
                content = response.content
                data = _extract_json(content)
                if not data:
                    logger.warning("Failed to parse Gemini web search response", content=content[:500])
                    return []
                raw_results = data.get("results", [])
            results = []
            for item in raw_results[:max_results]:
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    source=item.get("source", ""),
                )
                if result.url:
                    results.append(result)

            logger.info(
                "Gemini web search complete",
                query=query,
                results_found=len(results),
            )
            return results
        except Exception as e:
            logger.error("Gemini web search failed", query=query, error=str(e))
            return []

    async def close(self) -> None:
        """Close the provider (no-op for this implementation)."""
        pass
