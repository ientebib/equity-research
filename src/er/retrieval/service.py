"""
WebResearchService - DEPRECATED.

NOTE: This module is deprecated for Anthropic-only operation.
Use AnthropicResearcher from anthropic_research.py instead,
which uses Claude's native web_search tool.

The old workflow (search -> fetch -> summarize) is replaced by
Claude's integrated web search with automatic citations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from er.logging import get_logger
from er.retrieval.evidence_cards import EvidenceCard
from er.retrieval.fetch import FetchResult
from er.retrieval.search_provider import SearchResult

logger = get_logger(__name__)


@dataclass
class WebResearchResult:
    """Result from a web research query."""

    query: str
    search_results: list[SearchResult]
    fetch_results: list[FetchResult]
    evidence_cards: list[EvidenceCard]
    evidence_ids: list[str]  # All evidence IDs (raw + cards)

    def get_context_for_llm(self) -> str:
        """Get formatted context string for LLM consumption."""
        if not self.evidence_cards:
            return f"No relevant web results found for: {self.query}"

        parts = [f"Web Research Results for: {self.query}\n"]
        for card in self.evidence_cards:
            parts.append(card.to_context_string())
            parts.append("---")

        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "query": self.query,
            "search_results": [r.to_dict() for r in self.search_results],
            "evidence_cards": [c.to_dict() for c in self.evidence_cards],
            "evidence_ids": self.evidence_ids,
        }


class WebResearchService:
    """DEPRECATED: Use AnthropicResearcher instead.

    This class is stubbed for backwards compatibility.
    The OpenAI/Gemini search providers have been removed from this
    Anthropic-only codebase.

    Use AnthropicResearcher from anthropic_research.py instead,
    which provides Claude's native web search with automatic citations.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the service (stub).

        Raises NotImplementedError immediately since this service
        is no longer supported in Anthropic-only mode.
        """
        raise NotImplementedError(
            "WebResearchService is deprecated. "
            "Use AnthropicResearcher from anthropic_research.py instead. "
            "Example:\n"
            "  from er.retrieval.anthropic_research import AnthropicResearcher\n"
            "  researcher = AnthropicResearcher(evidence_store=evidence_store)\n"
            "  result = await researcher.research(query, ticker)"
        )

    async def close(self) -> None:
        """Close all components (no-op)."""
        pass

    async def research(
        self,
        query: str,
        max_results: int = 5,
        recency_days: int | None = None,
        domains: list[str] | None = None,
        skip_fetch: bool = False,
    ) -> WebResearchResult:
        """Execute a complete web research workflow (stub).

        Use AnthropicResearcher.research() instead.
        """
        raise NotImplementedError(
            "WebResearchService.research() is deprecated. "
            "Use AnthropicResearcher.research() instead."
        )

    async def research_batch(
        self,
        queries: list[str],
        max_results_per_query: int = 3,
        recency_days: int | None = None,
        max_total_queries: int = 25,
        max_concurrency: int = 3,
    ) -> list[WebResearchResult]:
        """Execute multiple research queries (stub).

        Use AnthropicResearcher.research_multi_vertical() instead.
        """
        raise NotImplementedError(
            "WebResearchService.research_batch() is deprecated. "
            "Use AnthropicResearcher.research_multi_vertical() instead."
        )

    def get_searches_performed(self) -> list[dict[str, Any]]:
        """Get list of all searches performed this session (stub)."""
        return []

    def get_all_evidence_cards(self) -> list[EvidenceCard]:
        """Get all evidence cards generated this session (stub)."""
        return []
