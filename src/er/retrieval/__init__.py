"""
Web retrieval module for evidence-first research.

Provides:
- SearchProvider: Protocol for web search providers
- OpenAIWebSearchProvider: Web search using OpenAI's web_search tool
- WebFetcher: Fetch and extract text from URLs
- EvidenceCardGenerator: Summarize web pages into bounded EvidenceCards
- WebResearchService: Orchestrates search, fetch, and summarization
- AnthropicResearcher: Deep research using Claude's native web search
"""

from er.retrieval.search_provider import (
    SearchResult,
    SearchProvider,
    OpenAIWebSearchProvider,
)
from er.retrieval.fetch import WebFetcher
from er.retrieval.evidence_cards import EvidenceCardGenerator
from er.retrieval.service import WebResearchService
from er.retrieval.anthropic_research import AnthropicResearcher, ResearchResult

__all__ = [
    "SearchResult",
    "SearchProvider",
    "OpenAIWebSearchProvider",
    "WebFetcher",
    "EvidenceCardGenerator",
    "WebResearchService",
    "AnthropicResearcher",
    "ResearchResult",
]
