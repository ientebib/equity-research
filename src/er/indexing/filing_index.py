"""
Filing Index for SEC filing retrieval.

Indexes 10-K, 10-Q, and 8-K filings for excerpt retrieval.
Provides BM25-like retrieval similar to TranscriptIndex.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import math

from er.indexing.text_chunker import TextChunker
from er.types import TextExcerpt, generate_id


class FilingType(Enum):
    """Types of SEC filings."""

    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"
    FORM_DEF14A = "DEF14A"
    UNKNOWN = "unknown"


@dataclass
class FilingChunk:
    """A chunk from an SEC filing with metadata."""

    excerpt_id: str
    source_evidence_id: str
    text: str
    start_offset: int
    end_offset: int
    filing_type: FilingType
    filing_date: str
    fiscal_period: str  # e.g., "FY2024", "Q3 2024"
    section: str | None = None  # e.g., "Item 1A Risk Factors"

    # For BM25 scoring
    term_frequencies: dict[str, int] = field(default_factory=dict)
    doc_length: int = 0


# Common SEC filing sections
SECTION_PATTERNS = {
    "item_1": r"(?i)item\s*1[.\s]+business",
    "item_1a": r"(?i)item\s*1a[.\s]+risk\s*factors",
    "item_1b": r"(?i)item\s*1b[.\s]+unresolved\s*staff\s*comments",
    "item_2": r"(?i)item\s*2[.\s]+properties",
    "item_3": r"(?i)item\s*3[.\s]+legal\s*proceedings",
    "item_4": r"(?i)item\s*4[.\s]+mine\s*safety",
    "item_5": r"(?i)item\s*5[.\s]+market\s*for",
    "item_6": r"(?i)item\s*6[.\s]+selected\s*financial",
    "item_7": r"(?i)item\s*7[.\s]+management.*discussion",
    "item_7a": r"(?i)item\s*7a[.\s]+quantitative.*risk",
    "item_8": r"(?i)item\s*8[.\s]+financial\s*statements",
    "item_9": r"(?i)item\s*9[.\s]+changes.*disagreements",
    "item_9a": r"(?i)item\s*9a[.\s]+controls.*procedures",
}


class FilingIndex:
    """Index for SEC filing excerpts with retrieval.

    Provides:
    1. Chunking of filings into excerpt evidence
    2. BM25-like retrieval for relevant excerpts
    3. Section detection for 10-K/10-Q items
    """

    # BM25 parameters (same as TranscriptIndex)
    K1 = 1.5
    B = 0.75

    def __init__(
        self,
        chunk_size: int = 2000,
        chunk_overlap: int = 300,
    ) -> None:
        """Initialize the filing index.

        Args:
            chunk_size: Target chunk size in characters.
            chunk_overlap: Overlap between chunks.
        """
        self.chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap)

        # In-memory index
        self.chunks: list[FilingChunk] = []
        self.idf: dict[str, float] = {}
        self.avg_doc_length: float = 0.0

    def add_filing(
        self,
        content: str,
        filing_type: FilingType | str,
        filing_date: str,
        fiscal_period: str,
        evidence_id: str | None = None,
    ) -> list[FilingChunk]:
        """Add a filing to the index.

        Args:
            content: Filing text content.
            filing_type: Type of filing (10-K, 10-Q, 8-K).
            filing_date: Date of filing.
            fiscal_period: Fiscal period covered (e.g., "FY2024").
            evidence_id: Optional evidence ID for source tracking.

        Returns:
            List of indexed chunks.
        """
        if isinstance(filing_type, str):
            filing_type = self._parse_filing_type(filing_type)

        if not evidence_id:
            evidence_id = generate_id("ev")

        # Chunk the filing
        text_chunks = self.chunker.chunk(content)
        new_chunks: list[FilingChunk] = []

        for chunk in text_chunks:
            # Detect section from chunk text
            section = self._detect_section(chunk.text)

            indexed_chunk = FilingChunk(
                excerpt_id=generate_id("exc"),
                source_evidence_id=evidence_id,
                text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                filing_type=filing_type,
                filing_date=filing_date,
                fiscal_period=fiscal_period,
                section=section,
            )

            # Build term frequencies for BM25
            indexed_chunk.term_frequencies = self._tokenize_and_count(chunk.text)
            indexed_chunk.doc_length = len(chunk.text.split())

            new_chunks.append(indexed_chunk)
            self.chunks.append(indexed_chunk)

        # Rebuild IDF with new documents
        self._build_idf()

        return new_chunks

    def retrieve_excerpts(
        self,
        query: str,
        top_k: int = 5,
        filing_type: FilingType | None = None,
        section: str | None = None,
    ) -> list[TextExcerpt]:
        """Retrieve top-k relevant excerpts for a query.

        Args:
            query: Search query.
            top_k: Number of excerpts to return.
            filing_type: Optional filter by filing type.
            section: Optional filter by section.

        Returns:
            List of TextExcerpt objects sorted by relevance.
        """
        if not self.chunks:
            return []

        # Filter chunks if requested
        candidate_chunks = self.chunks
        if filing_type:
            candidate_chunks = [c for c in candidate_chunks if c.filing_type == filing_type]
        if section:
            section_lower = section.lower()
            candidate_chunks = [
                c for c in candidate_chunks
                if c.section and section_lower in c.section.lower()
            ]

        # Tokenize query
        query_terms = self._tokenize(query)

        # Score each chunk
        scored_chunks: list[tuple[float, FilingChunk]] = []

        for chunk in candidate_chunks:
            score = self._bm25_score(query_terms, chunk)
            if score > 0:
                scored_chunks.append((score, chunk))

        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # Convert to TextExcerpt
        excerpts = []
        for score, chunk in scored_chunks[:top_k]:
            excerpt = TextExcerpt(
                excerpt_id=chunk.excerpt_id,
                source_evidence_id=chunk.source_evidence_id,
                source_type="filing",
                text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                metadata={
                    "filing_type": chunk.filing_type.value,
                    "filing_date": chunk.filing_date,
                    "fiscal_period": chunk.fiscal_period,
                    "section": chunk.section,
                },
                relevance_score=score,
            )
            excerpts.append(excerpt)

        return excerpts

    def get_risk_factors(self, top_k: int = 10) -> list[TextExcerpt]:
        """Retrieve risk factor excerpts from Item 1A.

        Args:
            top_k: Maximum number of excerpts.

        Returns:
            List of TextExcerpt objects from risk factors section.
        """
        # Filter to Item 1A Risk Factors section
        risk_chunks = [
            c for c in self.chunks
            if c.section and "risk" in c.section.lower()
        ]

        # Convert to excerpts (no query scoring, just return all)
        excerpts = []
        for chunk in risk_chunks[:top_k]:
            excerpt = TextExcerpt(
                excerpt_id=chunk.excerpt_id,
                source_evidence_id=chunk.source_evidence_id,
                source_type="filing",
                text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                metadata={
                    "filing_type": chunk.filing_type.value,
                    "section": chunk.section,
                },
                relevance_score=1.0,
            )
            excerpts.append(excerpt)

        return excerpts

    def get_mda_excerpts(self, query: str | None = None, top_k: int = 5) -> list[TextExcerpt]:
        """Retrieve MD&A (Management Discussion & Analysis) excerpts.

        Args:
            query: Optional query to rank excerpts.
            top_k: Maximum number of excerpts.

        Returns:
            List of TextExcerpt objects from MD&A section.
        """
        # Filter to Item 7 MD&A section
        mda_chunks = [
            c for c in self.chunks
            if c.section and ("management" in c.section.lower() or "item 7" in c.section.lower())
        ]

        if query:
            # Score and rank by query
            query_terms = self._tokenize(query)
            scored = []
            for chunk in mda_chunks:
                score = self._bm25_score(query_terms, chunk)
                scored.append((score, chunk))
            scored.sort(key=lambda x: x[0], reverse=True)
            mda_chunks = [c for _, c in scored[:top_k]]
        else:
            mda_chunks = mda_chunks[:top_k]

        excerpts = []
        for chunk in mda_chunks:
            excerpt = TextExcerpt(
                excerpt_id=chunk.excerpt_id,
                source_evidence_id=chunk.source_evidence_id,
                source_type="filing",
                text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                metadata={
                    "filing_type": chunk.filing_type.value,
                    "section": chunk.section,
                },
                relevance_score=1.0,
            )
            excerpts.append(excerpt)

        return excerpts

    def _parse_filing_type(self, filing_type: str) -> FilingType:
        """Parse filing type string to enum."""
        filing_type_upper = filing_type.upper().replace("-", "").replace(" ", "")
        mapping = {
            "10K": FilingType.FORM_10K,
            "10Q": FilingType.FORM_10Q,
            "8K": FilingType.FORM_8K,
            "DEF14A": FilingType.FORM_DEF14A,
        }
        return mapping.get(filing_type_upper, FilingType.UNKNOWN)

    def _detect_section(self, text: str) -> str | None:
        """Detect SEC filing section from text content."""
        for section_name, pattern in SECTION_PATTERNS.items():
            if re.search(pattern, text[:500]):  # Check first 500 chars
                # Return human-readable section name
                section_map = {
                    "item_1": "Item 1 - Business",
                    "item_1a": "Item 1A - Risk Factors",
                    "item_1b": "Item 1B - Unresolved Staff Comments",
                    "item_2": "Item 2 - Properties",
                    "item_3": "Item 3 - Legal Proceedings",
                    "item_4": "Item 4 - Mine Safety",
                    "item_5": "Item 5 - Market Information",
                    "item_6": "Item 6 - Selected Financial Data",
                    "item_7": "Item 7 - MD&A",
                    "item_7a": "Item 7A - Quantitative Risk Disclosures",
                    "item_8": "Item 8 - Financial Statements",
                    "item_9": "Item 9 - Changes and Disagreements",
                    "item_9a": "Item 9A - Controls and Procedures",
                }
                return section_map.get(section_name, section_name)

        return None

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase terms."""
        text = text.lower()
        tokens = re.findall(r'\b[a-z0-9]+\b', text)
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'this',
            'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'our', 'their', 'its', 'such', 'any', 'each', 'other', 'which',
        }
        return [t for t in tokens if t not in stopwords and len(t) > 1]

    def _tokenize_and_count(self, text: str) -> dict[str, int]:
        """Tokenize text and count term frequencies."""
        tokens = self._tokenize(text)
        return dict(Counter(tokens))

    def _build_idf(self) -> None:
        """Build IDF scores for all terms in the index."""
        if not self.chunks:
            return

        doc_freq: dict[str, int] = Counter()
        total_length = 0

        for chunk in self.chunks:
            total_length += chunk.doc_length
            for term in chunk.term_frequencies.keys():
                doc_freq[term] += 1

        n = len(self.chunks)
        self.idf = {
            term: math.log((n - df + 0.5) / (df + 0.5) + 1)
            for term, df in doc_freq.items()
        }
        self.avg_doc_length = total_length / n if n > 0 else 0

    def _bm25_score(
        self,
        query_terms: list[str],
        chunk: FilingChunk,
    ) -> float:
        """Compute BM25 score for a chunk given query terms."""
        score = 0.0

        for term in query_terms:
            if term not in self.idf:
                continue

            tf = chunk.term_frequencies.get(term, 0)
            if tf == 0:
                continue

            idf = self.idf[term]
            numerator = tf * (self.K1 + 1)
            denominator = tf + self.K1 * (
                1 - self.B + self.B * chunk.doc_length / self.avg_doc_length
            )
            score += idf * numerator / denominator

        return score


def build_filing_excerpts(
    filings: list[dict[str, Any]],
) -> list[TextExcerpt]:
    """Build filing excerpts from a list of filings.

    Convenience function to build excerpts without managing index.

    Args:
        filings: List of filing dicts with 'content', 'type', 'date', 'period'.

    Returns:
        List of all excerpts (unranked).
    """
    index = FilingIndex()

    for filing in filings:
        content = filing.get("content", "")
        if not content:
            continue

        index.add_filing(
            content=content,
            filing_type=filing.get("type", "unknown"),
            filing_date=filing.get("date", ""),
            fiscal_period=filing.get("period", ""),
            evidence_id=filing.get("evidence_id"),
        )

    # Return all chunks as excerpts
    return [
        TextExcerpt(
            excerpt_id=chunk.excerpt_id,
            source_evidence_id=chunk.source_evidence_id,
            source_type="filing",
            text=chunk.text,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            metadata={
                "filing_type": chunk.filing_type.value,
                "filing_date": chunk.filing_date,
                "section": chunk.section,
            },
            relevance_score=0.0,
        )
        for chunk in index.chunks
    ]
