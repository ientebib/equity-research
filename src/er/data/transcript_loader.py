"""
Local transcript loader for earnings call transcripts.

Loads transcript files from the local filesystem and converts them to the
format expected by CompanyContext.transcripts.

Transcript files are expected in: transcripts/{TICKER}/*.txt
Filename format: q{quarter}_{year}.txt (e.g., q3_2025.txt)
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from er.logging import get_logger

logger = get_logger(__name__)

# Default transcript directory (relative to project root)
DEFAULT_TRANSCRIPT_DIR = Path(__file__).parent.parent.parent.parent / "transcripts"


def parse_transcript_filename(filename: str) -> tuple[int, int] | None:
    """Parse quarter and year from transcript filename.

    Args:
        filename: Filename like "q3_2025.txt" or "Q1_2024.txt"

    Returns:
        Tuple of (quarter, year) or None if parsing fails.
    """
    match = re.match(r"[qQ](\d)_(\d{4})\.txt$", filename)
    if match:
        quarter = int(match.group(1))
        year = int(match.group(2))
        if 1 <= quarter <= 4:
            return quarter, year
    return None


def quarter_to_date(quarter: int, year: int) -> str:
    """Convert quarter and year to approximate earnings date.

    Earnings calls typically happen ~1 month after quarter end:
    - Q1 (Jan-Mar) -> April earnings
    - Q2 (Apr-Jun) -> July earnings
    - Q3 (Jul-Sep) -> October earnings
    - Q4 (Oct-Dec) -> January (next year) earnings

    Returns:
        Date string in YYYY-MM-DD format.
    """
    month_map = {
        1: (year, 4, 25),    # Q1 -> late April
        2: (year, 7, 25),    # Q2 -> late July
        3: (year, 10, 25),   # Q3 -> late October
        4: (year + 1, 1, 25), # Q4 -> late January next year
    }
    y, m, d = month_map[quarter]
    return f"{y:04d}-{m:02d}-{d:02d}"


def load_transcripts(
    ticker: str,
    transcript_dir: Path | str | None = None,
    max_transcripts: int = 4,
) -> list[dict[str, Any]]:
    """Load earnings transcripts for a ticker from local files.

    Args:
        ticker: Stock ticker (e.g., "GOOGL")
        transcript_dir: Base directory containing ticker subfolders.
                       Defaults to project's transcripts/ directory.
        max_transcripts: Maximum number of transcripts to load (most recent first).

    Returns:
        List of transcript dicts in CompanyContext.transcripts format:
        [
            {
                "quarter": 3,
                "year": 2025,
                "date": "2025-10-25",
                "text": "Full transcript text...",
                "source": "local_file",
                "filename": "q3_2025.txt"
            },
            ...
        ]
    """
    if transcript_dir is None:
        transcript_dir = DEFAULT_TRANSCRIPT_DIR
    else:
        transcript_dir = Path(transcript_dir)

    ticker_dir = transcript_dir / ticker.upper()

    if not ticker_dir.exists():
        logger.info("No transcript directory found", ticker=ticker, path=str(ticker_dir))
        return []

    # Find all transcript files
    transcript_files = []
    for file_path in ticker_dir.glob("*.txt"):
        parsed = parse_transcript_filename(file_path.name)
        if parsed:
            quarter, year = parsed
            transcript_files.append((file_path, quarter, year))

    if not transcript_files:
        logger.info("No transcript files found", ticker=ticker, path=str(ticker_dir))
        return []

    # Sort by date (most recent first): year desc, quarter desc
    transcript_files.sort(key=lambda x: (x[2], x[1]), reverse=True)

    # Load transcripts
    transcripts = []
    for file_path, quarter, year in transcript_files[:max_transcripts]:
        try:
            content = file_path.read_text(encoding="utf-8")
            transcript = {
                "quarter": quarter,
                "year": year,
                "date": quarter_to_date(quarter, year),
                "text": content,
                "source": "local_file",
                "filename": file_path.name,
            }
            transcripts.append(transcript)
            logger.info(
                "Loaded transcript",
                ticker=ticker,
                quarter=f"Q{quarter}",
                year=year,
                chars=len(content),
            )
        except Exception as e:
            logger.warning(
                "Failed to load transcript",
                ticker=ticker,
                file=str(file_path),
                error=str(e),
            )

    return transcripts


def get_latest_transcript(
    ticker: str,
    transcript_dir: Path | str | None = None,
) -> dict[str, Any] | None:
    """Get the most recent transcript for a ticker.

    Args:
        ticker: Stock ticker (e.g., "GOOGL")
        transcript_dir: Base directory containing ticker subfolders.

    Returns:
        Single transcript dict or None if not found.
    """
    transcripts = load_transcripts(ticker, transcript_dir, max_transcripts=1)
    return transcripts[0] if transcripts else None


def list_available_transcripts(
    ticker: str,
    transcript_dir: Path | str | None = None,
) -> list[tuple[int, int, str]]:
    """List available transcript quarters for a ticker without loading content.

    Args:
        ticker: Stock ticker
        transcript_dir: Base directory

    Returns:
        List of (quarter, year, filename) tuples, sorted most recent first.
    """
    if transcript_dir is None:
        transcript_dir = DEFAULT_TRANSCRIPT_DIR
    else:
        transcript_dir = Path(transcript_dir)

    ticker_dir = transcript_dir / ticker.upper()

    if not ticker_dir.exists():
        return []

    results = []
    for file_path in ticker_dir.glob("*.txt"):
        parsed = parse_transcript_filename(file_path.name)
        if parsed:
            quarter, year = parsed
            results.append((quarter, year, file_path.name))

    results.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return results
