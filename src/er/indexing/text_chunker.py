"""
Text Chunker for transcripts and filings.

Splits large text documents into overlapping chunks suitable for retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass
class TextChunk:
    """A chunk of text with offset information."""

    text: str
    start_offset: int
    end_offset: int
    chunk_index: int

    @property
    def length(self) -> int:
        """Length of the chunk in characters."""
        return len(self.text)


class TextChunker:
    """Chunks text documents into overlapping segments.

    Uses character-based chunking with configurable size and overlap.
    Attempts to split on sentence boundaries when possible.
    """

    # Default chunk sizes
    DEFAULT_CHUNK_SIZE = 1500  # characters
    DEFAULT_OVERLAP = 200  # characters

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ) -> None:
        """Initialize the chunker.

        Args:
            chunk_size: Target size of each chunk in characters.
            overlap: Overlap between consecutive chunks in characters.
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[TextChunk]:
        """Chunk text into overlapping segments.

        Args:
            text: Text to chunk.

        Returns:
            List of TextChunk objects.
        """
        if not text:
            return []

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(text):
            # Calculate end position
            end = min(start + self.chunk_size, len(text))

            # Try to break on sentence boundary
            if end < len(text):
                # Look for sentence-ending punctuation
                for boundary in [". ", ".\n", "? ", "?\n", "! ", "!\n"]:
                    # Search backwards from end for a sentence boundary
                    search_start = max(start + self.chunk_size // 2, start)
                    last_boundary = text.rfind(boundary, search_start, end)
                    if last_boundary > 0:
                        end = last_boundary + len(boundary)
                        break

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(TextChunk(
                    text=chunk_text,
                    start_offset=start,
                    end_offset=end,
                    chunk_index=chunk_index,
                ))
                chunk_index += 1

            # Move to next chunk with overlap
            start = end - self.overlap
            if start <= chunks[-1].start_offset if chunks else 0:
                # Prevent infinite loop
                start = end

        return chunks

    def chunk_iter(self, text: str) -> Iterator[TextChunk]:
        """Iterate over chunks (memory efficient for large texts).

        Args:
            text: Text to chunk.

        Yields:
            TextChunk objects.
        """
        for chunk in self.chunk(text):
            yield chunk


def chunk_text(
    text: str,
    target_chars: int = TextChunker.DEFAULT_CHUNK_SIZE,
    overlap: int = TextChunker.DEFAULT_OVERLAP,
) -> list[TextChunk]:
    """Convenience function to chunk text.

    Args:
        text: Text to chunk.
        target_chars: Target chunk size in characters.
        overlap: Overlap between chunks.

    Returns:
        List of TextChunk objects.
    """
    chunker = TextChunker(chunk_size=target_chars, overlap=overlap)
    return chunker.chunk(text)
