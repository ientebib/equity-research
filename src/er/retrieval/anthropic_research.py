"""
Anthropic Deep Research via Claude Web Search.

Uses Claude's native web search tool for research with automatic citations.
This is the SIMPLE, CORRECT approach - not multi-agent complexity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

from er.evidence.store import EvidenceStore
from er.logging import get_logger
from er.types import DiscoveredThread, SourceTier, ThreadBrief, ToSRisk

logger = get_logger(__name__)


@dataclass
class ResearchCitation:
    """A citation from web research."""
    url: str
    title: str
    cited_text: str
    evidence_id: str | None = None  # Assigned after storing in EvidenceStore


@dataclass
class ResearchFinding:
    """A finding from research with citations."""
    claim: str
    citations: list[ResearchCitation] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    """Complete research result."""
    query: str
    ticker: str
    content: str  # Full research text
    findings: list[ResearchFinding] = field(default_factory=list)
    citations: list[ResearchCitation] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    search_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    # Thread context (populated when research comes from Discovery threads)
    thread_id: str | None = None
    thread_name: str | None = None
    thread_priority: int | None = None
    thread_type: str | None = None  # "segment", "optionality", "cross_cutting"


class AnthropicResearcher:
    """Deep web research using Claude's native web search.

    This is the SIMPLE approach:
    1. Send query to Claude with web_search tool enabled
    2. Claude searches, synthesizes, and provides citations automatically
    3. We extract citations and store in EvidenceStore

    No need for multi-agent complexity - Claude handles it.
    """

    def __init__(
        self,
        evidence_store: EvidenceStore | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_searches: int = 10,
        api_key: str | None = None,
    ) -> None:
        """Initialize the researcher.

        Args:
            evidence_store: Store for persisting evidence. Optional.
            model: Claude model to use.
            max_searches: Max web searches per request.
            api_key: Anthropic API key. If None, reads from ANTHROPIC_API_KEY env var.
        """
        import os
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=key)
        self.evidence_store = evidence_store
        self.model = model
        self.max_searches = max_searches

    async def research(
        self,
        query: str,
        ticker: str,
        system_prompt: str | None = None,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> ResearchResult:
        """Execute deep research on a topic.

        Args:
            query: Research query/question.
            ticker: Company ticker for context.
            system_prompt: Optional system prompt override.
            allowed_domains: Only search these domains.
            blocked_domains: Never search these domains.

        Returns:
            ResearchResult with content, citations, and evidence IDs.
        """
        # Build web search tool config
        web_search_tool: dict[str, Any] = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": self.max_searches,
        }

        if allowed_domains:
            web_search_tool["allowed_domains"] = allowed_domains
        if blocked_domains:
            web_search_tool["blocked_domains"] = blocked_domains

        # Default system prompt for equity research
        default_system = f"""You are a senior equity research analyst conducting deep research on {ticker}.

Your research should be:
- Evidence-based with specific citations
- Focused on investment-relevant insights
- Balanced (cover both bull and bear cases)
- Recent and timely (prioritize recent sources)

For each major claim, cite your sources. Include:
- Growth drivers and risks
- Competitive positioning
- Recent developments (last 90 days)
- Management credibility
- Key metrics and KPIs"""

        messages = [{
            "role": "user",
            "content": f"Research query for {ticker}:\n\n{query}"
        }]

        logger.info(
            "Starting Anthropic web research",
            ticker=ticker,
            query=query[:100],
            max_searches=self.max_searches,
        )

        # Call Claude with web search
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system_prompt or default_system,
            tools=[web_search_tool],
            messages=messages,
        )

        # Extract content and citations
        content_parts: list[str] = []
        citations: list[ResearchCitation] = []
        search_count = 0

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)

                # Extract citations from text block
                if hasattr(block, "citations") and block.citations:
                    for cite in block.citations:
                        if cite.type == "web_search_result_location":
                            citations.append(ResearchCitation(
                                url=cite.url,
                                title=cite.title,
                                cited_text=getattr(cite, "cited_text", ""),
                            ))

            elif block.type == "web_search_tool_result":
                search_count += 1

        full_content = "\n".join(content_parts)

        # Store citations in EvidenceStore
        evidence_ids: list[str] = []
        if self.evidence_store:
            for citation in citations:
                try:
                    evidence = await self.evidence_store.store(
                        url=citation.url,
                        content=citation.cited_text.encode("utf-8"),
                        content_type="text/plain",
                        source_tier=SourceTier.NEWS,
                        tos_risk=ToSRisk.LOW,
                        title=citation.title,
                        snippet=citation.cited_text[:500],
                    )
                    citation.evidence_id = evidence.evidence_id
                    evidence_ids.append(evidence.evidence_id)
                except Exception as e:
                    logger.warning(
                        "Failed to store citation",
                        url=citation.url,
                        error=str(e),
                    )

        # Get token usage
        usage = response.usage
        server_tool_use = getattr(usage, "server_tool_use", None)
        # server_tool_use is an object with web_search_requests attribute, not a dict
        actual_search_count = search_count
        if server_tool_use is not None:
            actual_search_count = getattr(server_tool_use, "web_search_requests", search_count)

        result = ResearchResult(
            query=query,
            ticker=ticker,
            content=full_content,
            citations=citations,
            evidence_ids=evidence_ids,
            search_count=actual_search_count,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        logger.info(
            "Anthropic research complete",
            ticker=ticker,
            content_length=len(full_content),
            citation_count=len(citations),
            evidence_ids_count=len(evidence_ids),
            searches=result.search_count,
            tokens=usage.input_tokens + usage.output_tokens,
        )

        return result

    async def research_vertical(
        self,
        ticker: str,
        vertical: str,
        context: str = "",
        recency_days: int | None = None,
    ) -> ResearchResult:
        """Research a specific vertical/topic for a company.

        Args:
            ticker: Company ticker.
            vertical: Research vertical (e.g., "competitive landscape").
            context: Additional context about the company.
            recency_days: Focus on sources within N days (approximate).

        Returns:
            ResearchResult for this vertical.
        """
        # Build vertical-specific query
        query = f"""Deep dive on {vertical} for {ticker}.

{f"Context: {context}" if context else ""}

Focus areas:
- Current state and recent changes
- Key drivers and trends
- Risks and opportunities
- Quantitative data where available
{f"- Prioritize sources from the last {recency_days} days" if recency_days else ""}

Provide specific evidence for all claims."""

        # Block known problematic domains for financial research
        blocked = [
            "reddit.com",
            "twitter.com",
            "facebook.com",
        ]

        return await self.research(
            query=query,
            ticker=ticker,
            blocked_domains=blocked,
        )

    async def research_thread(
        self,
        ticker: str,
        thread: DiscoveredThread,
        brief: ThreadBrief | None = None,
        context: str = "",
    ) -> ResearchResult:
        """Research a Discovery-generated thread with full context.

        Uses thread metadata to build richer research queries:
        - thread.value_driver_hypothesis as the core question
        - thread.research_questions as specific investigation points
        - brief.rationale for why this matters
        - brief.hypotheses to test

        Args:
            ticker: Company ticker.
            thread: DiscoveredThread from Discovery Agent.
            brief: Optional ThreadBrief with rationale and hypotheses.
            context: Additional company context.

        Returns:
            ResearchResult with thread metadata attached.
        """
        # Build enhanced query from Discovery context
        research_questions_str = "\n".join(f"- {q}" for q in thread.research_questions)

        query_parts = [
            f"Deep research on {thread.name} for {ticker}.",
            "",
            f"Core Question: {thread.value_driver_hypothesis}" if thread.value_driver_hypothesis else "",
            "",
            "Specific Research Questions:" if thread.research_questions else "",
            research_questions_str,
        ]

        if brief:
            if brief.rationale:
                query_parts.append("")
                query_parts.append(f"Why This Matters: {brief.rationale}")
            if brief.hypotheses:
                query_parts.append("")
                query_parts.append("Hypotheses to Test:")
                query_parts.append("\n".join(f"- {h}" for h in brief.hypotheses))

        if context:
            query_parts.append("")
            query_parts.append(f"Context: {context}")

        query_parts.append("")
        query_parts.append("Provide specific evidence for all claims. Focus on recent data (last 90 days for developments, full history for fundamentals).")

        query = "\n".join(query_parts)

        # Use appropriate recency based on thread lens
        recency_hint = ""
        if thread.discovery_lens == "recent_developments":
            recency_hint = "Prioritize sources from the last 90 days."

        if recency_hint:
            query += f"\n\n{recency_hint}"

        # Block problematic domains
        blocked = ["reddit.com", "twitter.com", "facebook.com"]

        result = await self.research(
            query=query,
            ticker=ticker,
            blocked_domains=blocked,
        )

        # Attach thread metadata to result
        result.thread_id = thread.thread_id
        result.thread_name = thread.name
        result.thread_priority = thread.priority
        result.thread_type = thread.thread_type.value if hasattr(thread.thread_type, "value") else str(thread.thread_type)

        return result

    async def research_multi_vertical(
        self,
        ticker: str,
        verticals: list[str],
        context: str = "",
    ) -> list[ResearchResult]:
        """Research multiple verticals for a company.

        Args:
            ticker: Company ticker.
            verticals: List of verticals to research.
            context: Company context.

        Returns:
            List of ResearchResult, one per vertical.
        """
        import asyncio

        tasks = [
            self.research_vertical(ticker, vertical, context)
            for vertical in verticals
        ]

        return await asyncio.gather(*tasks)
