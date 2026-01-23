"""
Web retrieval module for evidence-first research.

Primary Interface (Anthropic-only):
- AnthropicResearcher: Deep research using Claude's native web search
- ResearchResult: Results from AnthropicResearcher

Legacy (Deprecated):
- WebResearchService: DEPRECATED - use AnthropicResearcher instead
- OpenAIWebSearchProvider: DEPRECATED - stubbed for backwards compatibility
- GeminiWebSearchProvider: DEPRECATED - stubbed for backwards compatibility

Utilities (still active):
- WebFetcher: Fetch and extract text from URLs
- EvidenceCardGenerator: Summarize web pages into bounded EvidenceCards
- SearchResult: Data class for search results
"""

from er.retrieval.anthropic_research import AnthropicResearcher, ResearchResult
from er.retrieval.evidence_cards import EvidenceCard, EvidenceCardGenerator
from er.retrieval.fetch import FetchResult, WebFetcher
from er.retrieval.search_provider import (
    SearchResult,
    SearchProvider,
    OpenAIWebSearchProvider,  # Deprecated stub
    GeminiWebSearchProvider,  # Deprecated stub
)
from er.retrieval.service import WebResearchResult, WebResearchService  # Deprecated

__all__ = [
    # Primary interface (Anthropic-only)
    "AnthropicResearcher",
    "ResearchResult",
    # Utilities
    "EvidenceCard",
    "EvidenceCardGenerator",
    "FetchResult",
    "WebFetcher",
    "SearchResult",
    "SearchProvider",
    # Deprecated (stubbed for backwards compatibility)
    "OpenAIWebSearchProvider",
    "GeminiWebSearchProvider",
    "WebResearchResult",
    "WebResearchService",
]
