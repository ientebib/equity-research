"""
EvidenceCard generator - summarize web pages into bounded cards.

EvidenceCards are bounded summaries (300-500 tokens) of web pages,
stored in both EvidenceStore and WorkspaceStore for tracking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any

from er.evidence.store import EvidenceStore
from er.llm.router import LLMRouter, AgentRole
from er.logging import get_logger
from er.retrieval.fetch import FetchResult
from er.security.sanitizer import InputSanitizer, ThreatLevel
from er.types import SourceTier, ToSRisk
from er.workspace.store import WorkspaceStore

logger = get_logger(__name__)


@dataclass
class EvidenceCard:
    """A bounded summary of a web page.

    Contains:
    - Structured summary (300-500 tokens)
    - Key facts extracted
    - Source metadata
    - Evidence IDs linking to raw content
    """

    card_id: str
    url: str
    title: str
    source: str
    summary: str  # 300-500 token summary
    key_facts: list[str]  # Bullet point facts
    relevance_score: float  # 0.0-1.0
    raw_evidence_id: str  # Evidence ID of raw HTML
    summary_evidence_id: str  # Evidence ID of this card
    published_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return asdict(self)

    def to_context_string(self) -> str:
        """Convert to a string suitable for LLM context."""
        facts_str = "\n".join(f"  - {f}" for f in self.key_facts) if self.key_facts else "  (none)"
        return f"""[{self.source}] {self.title}
URL: {self.url}
Summary: {self.summary}
Key Facts:
{facts_str}
Relevance: {self.relevance_score:.0%}
Evidence ID: {self.raw_evidence_id}
"""


class EvidenceCardGenerator:
    """Generates bounded EvidenceCards from web pages.

    Uses a cheap model to summarize page content into structured cards.
    """

    # Prompt for summarization
    SUMMARIZE_PROMPT = """Summarize this web page content for equity research.

URL: {url}
Title: {title}
Content:
{content}

---

Generate a JSON response with:
{{
  "summary": "300-500 word summary focusing on investment-relevant information",
  "key_facts": ["fact 1", "fact 2", ...],
  "relevance_score": 0.0 to 1.0 (how relevant to equity research),
  "published_date": "YYYY-MM-DD if found, null otherwise"
}}

Focus on:
- Financial metrics and performance
- Strategic developments
- Competitive dynamics
- Risk factors
- Management statements

Return ONLY valid JSON."""

    def __init__(
        self,
        llm_router: LLMRouter,
        evidence_store: EvidenceStore,
        workspace_store: WorkspaceStore | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize the generator.

        Args:
            llm_router: LLM router for API calls.
            evidence_store: Store for raw evidence.
            workspace_store: Store for structured artifacts.
            model: Model to use (defaults to cheap workhorse model).
        """
        self.llm_router = llm_router
        self.evidence_store = evidence_store
        self.workspace_store = workspace_store
        self.model = model  # Will use default if None

    async def generate_card(
        self,
        fetch_result: FetchResult,
        query_context: str = "",
    ) -> EvidenceCard | None:
        """Generate an EvidenceCard from a fetched page.

        Args:
            fetch_result: Result from WebFetcher.
            query_context: Optional context about why this page was fetched.

        Returns:
            EvidenceCard, or None if generation failed.
        """
        if not fetch_result.success:
            logger.warning(
                "Cannot generate card from failed fetch",
                url=fetch_result.url,
                error=fetch_result.error,
            )
            return None

        # Sanitize evidence text before it enters any LLM prompt
        sanitizer = InputSanitizer()
        sanitization = sanitizer.sanitize(fetch_result.text, source=fetch_result.url)
        if sanitization.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL):
            sanitized_text = "[Content blocked due to security concerns]"
        else:
            sanitized_text = sanitization.sanitized_text

        # Truncate content if too long (keep first 8000 chars for summarization)
        content = sanitized_text[:8000]

        # Store sanitization metadata when changes or threats detected
        if self.workspace_store and (
            sanitization.modifications_made or sanitization.threat_level != ThreatLevel.NONE
        ):
            self.workspace_store.put_artifact(
                artifact_type="sanitized_evidence",
                producer="evidence_card_generator",
                json_obj={
                    "url": fetch_result.url,
                    "threat_level": sanitization.threat_level.value,
                    "threats_detected": sanitization.threats_detected,
                    "modifications_made": sanitization.modifications_made,
                    "original_length": sanitization.original_length,
                    "sanitized_length": sanitization.sanitized_length,
                },
                summary=f"Sanitized evidence ({sanitization.threat_level.value}) for {fetch_result.url}",
                evidence_ids=[fetch_result.evidence_id] if fetch_result.evidence_id else [],
            )

        # Build prompt
        prompt = self.SUMMARIZE_PROMPT.format(
            url=fetch_result.url,
            title=fetch_result.title,
            content=content,
        )

        if query_context:
            prompt = f"Context: {query_context}\n\n{prompt}"

        try:
            # Call LLM for summarization
            response = await self.llm_router.call(
                role=AgentRole.OUTPUT,  # Cheap model
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                response_format={"type": "json_object"},
            )

            # Parse response
            content_str = response.get("content", "")
            if not content_str:
                logger.warning("Empty response from summarization", url=fetch_result.url)
                return None

            data = json.loads(content_str)

            # Extract fields
            summary = data.get("summary", "")
            key_facts = data.get("key_facts", [])
            relevance_score = float(data.get("relevance_score", 0.5))
            published_date = data.get("published_date")

            # Store the card summary as evidence too
            card_content = json.dumps({
                "url": fetch_result.url,
                "title": fetch_result.title,
                "summary": summary,
                "key_facts": key_facts,
                "relevance_score": relevance_score,
            })

            summary_evidence = await self.evidence_store.store(
                url=f"evidence_card:{fetch_result.url}",
                content=card_content.encode(),
                content_type="application/json",
                source_tier=SourceTier.DERIVED,
                tos_risk=ToSRisk.NONE,
                title=f"EvidenceCard: {fetch_result.title}",
                snippet=summary[:200],
            )

            # Create card
            card = EvidenceCard(
                card_id=summary_evidence.evidence_id,
                url=fetch_result.url,
                title=fetch_result.title,
                source=self._extract_domain(fetch_result.url),
                summary=summary,
                key_facts=key_facts if isinstance(key_facts, list) else [],
                relevance_score=relevance_score,
                raw_evidence_id=fetch_result.evidence_id,
                summary_evidence_id=summary_evidence.evidence_id,
                published_date=published_date,
            )

            # Store in workspace if available
            if self.workspace_store:
                self.workspace_store.put_artifact(
                    artifact_type="evidence_card",
                    producer="evidence_card_generator",
                    json_obj=card.to_dict(),
                    summary=summary[:200],
                    evidence_ids=[fetch_result.evidence_id, summary_evidence.evidence_id],
                )

            logger.info(
                "Generated evidence card",
                url=fetch_result.url,
                card_id=card.card_id,
                relevance=relevance_score,
                facts_count=len(key_facts),
            )

            return card

        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse summarization response",
                url=fetch_result.url,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to generate evidence card",
                url=fetch_result.url,
                error=str(e),
            )
            return None

    async def generate_cards(
        self,
        fetch_results: list[FetchResult],
        query_context: str = "",
    ) -> list[EvidenceCard]:
        """Generate EvidenceCards from multiple fetched pages.

        Args:
            fetch_results: Results from WebFetcher.
            query_context: Optional context about the search.

        Returns:
            List of successfully generated EvidenceCards.
        """
        import asyncio

        # Process concurrently with limited parallelism
        semaphore = asyncio.Semaphore(3)

        async def generate_with_semaphore(result: FetchResult) -> EvidenceCard | None:
            async with semaphore:
                return await self.generate_card(result, query_context)

        cards = await asyncio.gather(
            *[generate_with_semaphore(r) for r in fetch_results],
            return_exceptions=True,
        )

        # Filter out None and exceptions
        valid_cards = []
        for card in cards:
            if isinstance(card, EvidenceCard):
                valid_cards.append(card)
            elif isinstance(card, Exception):
                logger.warning("Card generation raised exception", error=str(card))

        return valid_cards

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
