"""
WebResearchService - orchestrates web research workflow.

Combines:
- Search (URL discovery via OpenAI web_search)
- Fetch (HTTP fetch + text extraction)
- Summarize (EvidenceCard generation)

All with caching, deduplication, and evidence tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from er.evidence.store import EvidenceStore
from er.llm.router import LLMRouter
from er.logging import get_logger
from er.retrieval.evidence_cards import EvidenceCard, EvidenceCardGenerator
from er.retrieval.fetch import FetchResult, WebFetcher
from er.retrieval.search_provider import OpenAIWebSearchProvider, SearchResult
from er.workspace.store import WorkspaceStore

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
    """Orchestrates web research: search -> fetch -> summarize.

    Provides a unified interface for web research with:
    - Caching at URL level
    - Evidence tracking
    - Workspace artifact storage
    - Configurable quotas
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        evidence_store: EvidenceStore,
        workspace_store: WorkspaceStore | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            llm_router: LLM router for API calls.
            evidence_store: Store for raw evidence.
            workspace_store: Store for structured artifacts.
        """
        self.llm_router = llm_router
        self.evidence_store = evidence_store
        self.workspace_store = workspace_store

        # Initialize components
        self.search_provider = OpenAIWebSearchProvider(llm_router)
        self.fetcher = WebFetcher(evidence_store)
        self.card_generator = EvidenceCardGenerator(
            llm_router, evidence_store, workspace_store
        )

        # Track searches performed this session
        self._searches_performed: list[dict[str, Any]] = []

    async def close(self) -> None:
        """Close all components."""
        await self.search_provider.close()
        await self.fetcher.close()

    async def research(
        self,
        query: str,
        max_results: int = 5,
        recency_days: int | None = None,
        domains: list[str] | None = None,
        skip_fetch: bool = False,
    ) -> WebResearchResult:
        """Execute a complete web research workflow.

        Args:
            query: Search query.
            max_results: Max results to return.
            recency_days: Only results from last N days.
            domains: Restrict to specific domains.
            skip_fetch: If True, only search (don't fetch or summarize).

        Returns:
            WebResearchResult with all outputs.
        """
        logger.info(
            "Starting web research",
            query=query,
            max_results=max_results,
            recency_days=recency_days,
        )

        # Step 1: Search for URLs
        search_results = await self.search_provider.search(
            query=query,
            max_results=max_results,
            recency_days=recency_days,
            domains=domains,
        )

        # Log search
        search_log = {
            "query": query,
            "max_results": max_results,
            "recency_days": recency_days,
            "domains": domains,
            "results_count": len(search_results),
            "urls": [r.url for r in search_results],
        }
        self._searches_performed.append(search_log)

        if self.workspace_store:
            self.workspace_store.log_search(
                query=query,
                provider="openai_web_search",
                results=[r.to_dict() for r in search_results],
            )

        if skip_fetch or not search_results:
            return WebResearchResult(
                query=query,
                search_results=search_results,
                fetch_results=[],
                evidence_cards=[],
                evidence_ids=[],
            )

        # Step 2: Fetch URLs
        urls = [r.url for r in search_results]
        fetch_results = await self.fetcher.fetch_many(urls)

        # Step 3: Generate evidence cards
        evidence_cards = await self.card_generator.generate_cards(
            fetch_results,
            query_context=query,
        )

        # Collect all evidence IDs
        evidence_ids = []
        for fr in fetch_results:
            if fr.evidence_id:
                evidence_ids.append(fr.evidence_id)
        for card in evidence_cards:
            evidence_ids.append(card.raw_evidence_id)
            evidence_ids.append(card.summary_evidence_id)

        # Dedupe
        evidence_ids = list(set(evidence_ids))

        logger.info(
            "Web research complete",
            query=query,
            search_results=len(search_results),
            fetch_success=sum(1 for fr in fetch_results if fr.success),
            cards_generated=len(evidence_cards),
            evidence_ids=len(evidence_ids),
        )

        return WebResearchResult(
            query=query,
            search_results=search_results,
            fetch_results=fetch_results,
            evidence_cards=evidence_cards,
            evidence_ids=evidence_ids,
        )

    async def research_batch(
        self,
        queries: list[str],
        max_results_per_query: int = 3,
        recency_days: int | None = None,
        max_total_queries: int = 25,
        max_concurrency: int = 3,
    ) -> list[WebResearchResult]:
        """Execute multiple research queries with controlled concurrency.

        Args:
            queries: List of search queries.
            max_results_per_query: Max results per query.
            recency_days: Only results from last N days.
            max_total_queries: Maximum number of queries to execute.
            max_concurrency: Maximum concurrent queries (default 3).

        Returns:
            List of WebResearchResult objects.
        """
        import asyncio

        # Limit total queries to budget
        queries = queries[:max_total_queries]

        logger.info(
            "Starting batch web research",
            total_queries=len(queries),
            max_concurrency=max_concurrency,
            max_results_per_query=max_results_per_query,
        )

        # Use semaphore for rate limit control
        semaphore = asyncio.Semaphore(max_concurrency)

        async def research_with_semaphore(query: str) -> WebResearchResult:
            async with semaphore:
                return await self.research(
                    query=query,
                    max_results=max_results_per_query,
                    recency_days=recency_days,
                )

        # Execute all queries with controlled concurrency
        results = await asyncio.gather(
            *[research_with_semaphore(q) for q in queries],
            return_exceptions=True,
        )

        # Convert exceptions to empty results
        processed: list[WebResearchResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "Batch query failed",
                    query=queries[i],
                    error=str(result),
                )
                processed.append(WebResearchResult(
                    query=queries[i],
                    search_results=[],
                    fetch_results=[],
                    evidence_cards=[],
                    evidence_ids=[],
                ))
            else:
                processed.append(result)

        logger.info(
            "Batch web research complete",
            total_queries=len(queries),
            successful=sum(1 for r in processed if r.search_results),
        )

        return processed

    def get_searches_performed(self) -> list[dict[str, Any]]:
        """Get list of all searches performed this session."""
        return self._searches_performed.copy()

    def get_all_evidence_cards(self) -> list[EvidenceCard]:
        """Get all evidence cards generated this session.

        Note: Retrieves from workspace store if available.
        """
        if not self.workspace_store:
            return []

        artifacts = self.workspace_store.list_artifacts("evidence_card")
        cards = []
        for artifact in artifacts:
            try:
                content = artifact.get("content", {})
                cards.append(EvidenceCard(**content))
            except Exception as e:
                logger.warning("Failed to load evidence card", error=str(e))

        return cards
