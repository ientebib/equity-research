"""
Transcript Index for excerpt retrieval.

Chunks transcripts and provides BM25-like retrieval for relevant excerpts.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from er.evidence.store import EvidenceStore
from er.indexing.text_chunker import TextChunker, TextChunk
from er.types import CompanyContext, TextExcerpt, generate_id


@dataclass
class TranscriptChunk:
    """A chunk from a transcript with metadata."""

    excerpt_id: str
    source_evidence_id: str
    text: str
    start_offset: int
    end_offset: int
    quarter: str  # e.g., "Q3 2024"
    speaker: str | None = None
    section: str | None = None  # "prepared_remarks" or "qa"

    # For BM25 scoring
    term_frequencies: dict[str, int] = field(default_factory=dict)
    doc_length: int = 0


class TranscriptIndex:
    """Index for transcript excerpts with retrieval.

    Provides:
    1. Chunking of transcripts into excerpt evidence
    2. BM25-like retrieval for relevant excerpts
    3. Integration with EvidenceStore
    """

    # BM25 parameters
    K1 = 1.5
    B = 0.75

    def __init__(
        self,
        evidence_store: EvidenceStore | None = None,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
    ) -> None:
        """Initialize the transcript index.

        Args:
            evidence_store: Optional EvidenceStore for persistence.
            chunk_size: Target chunk size in characters.
            chunk_overlap: Overlap between chunks.
        """
        self.evidence_store = evidence_store
        self.chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap)

        # In-memory index
        self.chunks: list[TranscriptChunk] = []
        self.idf: dict[str, float] = {}
        self.avg_doc_length: float = 0.0

    def build_from_company_context(
        self,
        company_context: CompanyContext,
    ) -> list[TranscriptChunk]:
        """Build index from company context transcripts.

        Args:
            company_context: CompanyContext with transcripts.

        Returns:
            List of indexed chunks.
        """
        self.chunks = []

        transcripts = company_context.transcripts or []

        for transcript in transcripts:
            # Get transcript text
            content = transcript.get("content", "")
            if not content:
                continue

            quarter = transcript.get("quarter", "")
            year = transcript.get("year", "")
            quarter_str = f"Q{quarter} {year}" if quarter and year else "Unknown"

            # Get or create evidence ID
            evidence_id = transcript.get("evidence_id", generate_id("ev"))

            # Chunk the transcript
            text_chunks = self.chunker.chunk(content)

            for chunk in text_chunks:
                # Detect speaker if possible
                speaker = self._detect_speaker(chunk.text)

                # Detect section
                section = self._detect_section(chunk.text)

                # Create indexed chunk
                indexed_chunk = TranscriptChunk(
                    excerpt_id=generate_id("exc"),
                    source_evidence_id=evidence_id,
                    text=chunk.text,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    quarter=quarter_str,
                    speaker=speaker,
                    section=section,
                )

                # Build term frequencies for BM25
                indexed_chunk.term_frequencies = self._tokenize_and_count(chunk.text)
                indexed_chunk.doc_length = len(chunk.text.split())

                self.chunks.append(indexed_chunk)

        # Build IDF scores
        self._build_idf()

        return self.chunks

    def retrieve_excerpts(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[TextExcerpt]:
        """Retrieve top-k relevant excerpts for a query.

        Args:
            query: Search query.
            top_k: Number of excerpts to return.

        Returns:
            List of TextExcerpt objects sorted by relevance.
        """
        if not self.chunks:
            return []

        # Tokenize query
        query_terms = self._tokenize(query)

        # Score each chunk
        scored_chunks: list[tuple[float, TranscriptChunk]] = []

        for chunk in self.chunks:
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
                source_type="transcript",
                text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                metadata={
                    "quarter": chunk.quarter,
                    "speaker": chunk.speaker,
                    "section": chunk.section,
                },
                relevance_score=score,
            )
            excerpts.append(excerpt)

        return excerpts

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase terms."""
        # Simple tokenization - lowercase, split on non-alphanumeric
        text = text.lower()
        tokens = re.findall(r'\b[a-z0-9]+\b', text)
        # Remove stopwords
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                     'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'this',
                     'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they'}
        return [t for t in tokens if t not in stopwords and len(t) > 1]

    def _tokenize_and_count(self, text: str) -> dict[str, int]:
        """Tokenize text and count term frequencies."""
        tokens = self._tokenize(text)
        return dict(Counter(tokens))

    def _build_idf(self) -> None:
        """Build IDF scores for all terms in the index."""
        if not self.chunks:
            return

        # Count document frequency for each term
        doc_freq: dict[str, int] = Counter()
        total_length = 0

        for chunk in self.chunks:
            total_length += chunk.doc_length
            for term in chunk.term_frequencies.keys():
                doc_freq[term] += 1

        # Compute IDF
        n = len(self.chunks)
        self.idf = {
            term: math.log((n - df + 0.5) / (df + 0.5) + 1)
            for term, df in doc_freq.items()
        }

        # Average document length
        self.avg_doc_length = total_length / n if n > 0 else 0

    def _bm25_score(
        self,
        query_terms: list[str],
        chunk: TranscriptChunk,
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

            # BM25 formula
            numerator = tf * (self.K1 + 1)
            denominator = tf + self.K1 * (
                1 - self.B + self.B * chunk.doc_length / self.avg_doc_length
            )

            score += idf * numerator / denominator

        return score

    def _detect_speaker(self, text: str) -> str | None:
        """Detect speaker from transcript text."""
        # Look for common speaker patterns
        patterns = [
            r'^([A-Z][a-z]+ [A-Z][a-z]+)[:\-]',  # "Tim Cook:"
            r'^([A-Z][A-Z\s]+)[:\-]',  # "CEO:"
            r'\[([A-Z][a-z]+ [A-Z][a-z]+)\]',  # "[Tim Cook]"
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:200])
            if match:
                return match.group(1).strip()

        return None

    def _detect_section(self, text: str) -> str | None:
        """Detect section (prepared remarks vs Q&A) from text."""
        text_lower = text.lower()

        # Q&A indicators
        qa_indicators = [
            "question", "analyst", "your question",
            "thank you for your question", "let me address",
        ]

        for indicator in qa_indicators:
            if indicator in text_lower:
                return "qa"

        return "prepared_remarks"


def build_transcript_excerpts(
    company_context: CompanyContext,
    evidence_store: EvidenceStore | None = None,
) -> list[TextExcerpt]:
    """Build transcript excerpts from company context.

    Convenience function to build excerpts without managing index.

    Args:
        company_context: CompanyContext with transcripts.
        evidence_store: Optional EvidenceStore.

    Returns:
        List of all excerpts (unranked).
    """
    index = TranscriptIndex(evidence_store=evidence_store)
    chunks = index.build_from_company_context(company_context)

    return [
        TextExcerpt(
            excerpt_id=chunk.excerpt_id,
            source_evidence_id=chunk.source_evidence_id,
            source_type="transcript",
            text=chunk.text,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            metadata={
                "quarter": chunk.quarter,
                "speaker": chunk.speaker,
                "section": chunk.section,
            },
            relevance_score=0.0,
        )
        for chunk in chunks
    ]
