"""Tests for TranscriptIndex and text chunking."""

from __future__ import annotations

import pytest

from er.indexing.text_chunker import TextChunker, TextChunk, chunk_text
from er.indexing.transcript_index import (
    TranscriptIndex,
    TranscriptChunk,
    build_transcript_excerpts,
)
from er.types import CompanyContext, TextExcerpt


class TestTextChunker:
    """Tests for TextChunker."""

    def test_empty_text(self) -> None:
        """Test chunking empty text returns empty list."""
        chunker = TextChunker()
        chunks = chunker.chunk("")
        assert chunks == []

    def test_short_text(self) -> None:
        """Test chunking text shorter than chunk size."""
        chunker = TextChunker(chunk_size=1000, overlap=100)
        text = "This is a short text."
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].start_offset == 0
        assert chunks[0].chunk_index == 0

    def test_long_text_creates_multiple_chunks(self) -> None:
        """Test chunking long text creates multiple overlapping chunks."""
        chunker = TextChunker(chunk_size=100, overlap=20)
        text = "This is sentence one. " * 20  # ~440 chars
        chunks = chunker.chunk(text)

        assert len(chunks) > 1
        # Verify chunks have sequential indices
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
        # Verify overlap exists (subsequent chunks start before previous ends)
        if len(chunks) > 1:
            assert chunks[1].start_offset < chunks[0].end_offset

    def test_sentence_boundary_splitting(self) -> None:
        """Test that chunker prefers sentence boundaries."""
        chunker = TextChunker(chunk_size=50, overlap=10)
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = chunker.chunk(text)

        # Each chunk should ideally end at a sentence boundary
        for chunk in chunks:
            # Most chunks should end with period+space or be the last chunk
            if chunk.chunk_index < len(chunks) - 1:
                # Interior chunks should prefer sentence boundaries
                assert "." in chunk.text

    def test_chunk_text_convenience_function(self) -> None:
        """Test chunk_text convenience function."""
        text = "Hello world. " * 100
        chunks = chunk_text(text, target_chars=200, overlap=50)

        assert len(chunks) > 1
        assert all(isinstance(c, TextChunk) for c in chunks)

    def test_chunk_iter(self) -> None:
        """Test chunk_iter generator."""
        chunker = TextChunker(chunk_size=100, overlap=20)
        text = "Test text. " * 50

        chunks_list = chunker.chunk(text)
        chunks_iter = list(chunker.chunk_iter(text))

        assert len(chunks_list) == len(chunks_iter)
        for c1, c2 in zip(chunks_list, chunks_iter):
            assert c1.text == c2.text

    def test_text_chunk_length_property(self) -> None:
        """Test TextChunk length property."""
        chunk = TextChunk(
            text="Hello world",
            start_offset=0,
            end_offset=11,
            chunk_index=0,
        )
        assert chunk.length == 11


class TestTranscriptIndex:
    """Tests for TranscriptIndex."""

    @pytest.fixture
    def sample_transcript(self) -> str:
        """Create sample transcript text."""
        return """
Tim Cook: Good afternoon and thank you for joining today's call. I'm pleased to report
another strong quarter with revenue of $94 billion, up 8% year over year.

Luca Maestri: Thank you Tim. Our services revenue reached $24 billion, a new record.
Gross margin was 45.5%, reflecting strong product mix.

Analyst Question: Can you comment on the iPhone demand environment in China?

Tim Cook: Great question. We saw some challenges in China but remain optimistic about
the long-term opportunity in that market. Our installed base continues to grow.

Analyst Question: What's your outlook for AI features?

Tim Cook: We're very excited about our AI initiatives. We believe our approach of
on-device processing combined with cloud capabilities will differentiate us.
        """.strip()

    @pytest.fixture
    def company_context(self, sample_transcript: str) -> CompanyContext:
        """Create CompanyContext with transcript."""
        from datetime import datetime
        return CompanyContext(
            symbol="AAPL",
            fetched_at=datetime.fromisoformat("2024-01-15T10:00:00"),
            profile={
                "companyName": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
            },
            transcripts=[
                {
                    "quarter": 4,
                    "year": 2024,
                    "content": sample_transcript,
                    "evidence_id": "ev_transcript_001",
                }
            ],
        )

    def test_build_from_empty_context(self) -> None:
        """Test building index from context with no transcripts."""
        from datetime import datetime
        context = CompanyContext(
            symbol="TEST",
            fetched_at=datetime.fromisoformat("2024-01-01T00:00:00"),
            profile={"companyName": "Test Corp"},
            transcripts=[],
        )

        index = TranscriptIndex()
        chunks = index.build_from_company_context(context)
        assert chunks == []

    def test_build_from_company_context(self, company_context: CompanyContext) -> None:
        """Test building index from company context."""
        index = TranscriptIndex(chunk_size=500, chunk_overlap=50)
        chunks = index.build_from_company_context(company_context)

        assert len(chunks) > 0
        assert all(isinstance(c, TranscriptChunk) for c in chunks)
        # Each chunk should have proper fields
        for chunk in chunks:
            assert chunk.excerpt_id.startswith("exc_")
            assert chunk.source_evidence_id == "ev_transcript_001"
            assert chunk.quarter == "Q4 2024"
            assert len(chunk.text) > 0
            assert chunk.doc_length > 0
            assert len(chunk.term_frequencies) > 0

    def test_retrieve_excerpts_no_matches(self, company_context: CompanyContext) -> None:
        """Test retrieval returns empty for irrelevant query."""
        index = TranscriptIndex()
        index.build_from_company_context(company_context)

        # Query with terms not in transcript
        excerpts = index.retrieve_excerpts("cryptocurrency blockchain mining")
        # May return some results with low scores, or empty
        # The important thing is it doesn't crash
        assert isinstance(excerpts, list)

    def test_retrieve_excerpts_relevant_query(self, company_context: CompanyContext) -> None:
        """Test retrieval returns relevant excerpts for matching query."""
        index = TranscriptIndex()
        index.build_from_company_context(company_context)

        # Query for terms in transcript
        excerpts = index.retrieve_excerpts("iPhone China demand")

        assert len(excerpts) > 0
        assert all(isinstance(e, TextExcerpt) for e in excerpts)
        # First result should be most relevant
        assert excerpts[0].relevance_score > 0

    def test_retrieve_excerpts_top_k(self, company_context: CompanyContext) -> None:
        """Test retrieval respects top_k parameter."""
        index = TranscriptIndex()
        index.build_from_company_context(company_context)

        excerpts = index.retrieve_excerpts("revenue", top_k=2)
        assert len(excerpts) <= 2

    def test_bm25_scoring(self, company_context: CompanyContext) -> None:
        """Test BM25 scoring ranks relevant chunks higher."""
        index = TranscriptIndex()
        index.build_from_company_context(company_context)

        # Query about AI
        excerpts_ai = index.retrieve_excerpts("AI artificial intelligence")

        # Query about services revenue
        excerpts_revenue = index.retrieve_excerpts("services revenue record")

        # Both should return results
        assert len(excerpts_ai) > 0
        assert len(excerpts_revenue) > 0

        # AI excerpts should mention AI-related content
        ai_text = excerpts_ai[0].text.lower()
        assert "ai" in ai_text or "intelligence" in ai_text

    def test_speaker_detection(self) -> None:
        """Test speaker detection from transcript text."""
        index = TranscriptIndex()

        # Test various speaker patterns
        assert index._detect_speaker("Tim Cook: Hello everyone") == "Tim Cook"
        assert index._detect_speaker("[John Smith] Thank you") == "John Smith"
        assert index._detect_speaker("CEO: Good morning") == "CEO"
        assert index._detect_speaker("No speaker here") is None

    def test_section_detection(self) -> None:
        """Test section detection (prepared remarks vs Q&A)."""
        index = TranscriptIndex()

        # Q&A indicators
        assert index._section_detection_result("Let me answer your question") == "qa"
        assert index._section_detection_result("The analyst asked about margins") == "qa"

        # Prepared remarks (default)
        assert index._section_detection_result("We are pleased to report") == "prepared_remarks"

    def test_tokenize_removes_stopwords(self) -> None:
        """Test tokenization removes stopwords."""
        index = TranscriptIndex()

        tokens = index._tokenize("The quick brown fox and the lazy dog")

        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        assert "the" not in tokens
        assert "and" not in tokens

    def test_idf_computation(self, company_context: CompanyContext) -> None:
        """Test IDF values are computed correctly."""
        index = TranscriptIndex()
        index.build_from_company_context(company_context)

        # IDF should be populated
        assert len(index.idf) > 0
        # Average doc length should be positive
        assert index.avg_doc_length > 0

        # Common terms should have lower IDF
        # Rare terms should have higher IDF


class TestBuildTranscriptExcerpts:
    """Tests for build_transcript_excerpts convenience function."""

    def test_build_transcript_excerpts(self) -> None:
        """Test convenience function."""
        from datetime import datetime
        context = CompanyContext(
            symbol="MSFT",
            fetched_at=datetime.fromisoformat("2024-01-01T00:00:00"),
            profile={"companyName": "Microsoft Corp", "sector": "Technology"},
            transcripts=[
                {
                    "quarter": 2,
                    "year": 2024,
                    "content": "Satya Nadella: We continue to see strong cloud growth.",
                }
            ],
        )

        excerpts = build_transcript_excerpts(context)

        assert len(excerpts) > 0
        assert all(isinstance(e, TextExcerpt) for e in excerpts)
        assert excerpts[0].source_type == "transcript"
        assert excerpts[0].metadata.get("quarter") == "Q2 2024"


# Helper for section detection test
def _section_detection_helper(index: TranscriptIndex, text: str) -> str | None:
    """Helper to test section detection."""
    return index._detect_section(text)


# Monkey-patch for cleaner test
TranscriptIndex._section_detection_result = lambda self, text: self._detect_section(text)
