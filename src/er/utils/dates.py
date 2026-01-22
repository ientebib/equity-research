"""Date and quarter utilities for the equity research system.

Provides dynamic quarter computation instead of hardcoded values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from er.types import CompanyContext


def get_quarter_from_date(date: datetime) -> tuple[int, int]:
    """Get year and quarter from a datetime.

    Args:
        date: The datetime to extract quarter from.

    Returns:
        Tuple of (year, quarter) where quarter is 1-4.
    """
    quarter = (date.month - 1) // 3 + 1
    return (date.year, quarter)


def get_latest_quarter() -> tuple[int, int]:
    """Get the latest completed quarter based on current date.

    Financial data typically has a 1-quarter lag, so we return
    the previous quarter.

    Returns:
        Tuple of (year, quarter) for the most recent completed quarter.
    """
    now = datetime.now(timezone.utc)
    year, current_quarter = get_quarter_from_date(now)

    # Go back one quarter for data lag
    if current_quarter == 1:
        return (year - 1, 4)
    else:
        return (year, current_quarter - 1)


def get_latest_quarter_from_data(context: "CompanyContext") -> tuple[int, int]:
    """Infer the latest quarter from FMP financial data.

    This is more accurate than using current date because it reflects
    what data is actually available.

    Args:
        context: CompanyContext with financial statements.

    Returns:
        Tuple of (year, quarter) for the most recent quarter in the data.
    """
    # Try to get from quarterly income statements
    if context.income_statement_quarterly:
        latest = context.income_statement_quarterly[0]
        date_str = latest.get("date", "")
        if date_str:
            try:
                # FMP dates are typically YYYY-MM-DD
                dt = datetime.fromisoformat(date_str)
                return get_quarter_from_date(dt)
            except (ValueError, TypeError):
                pass

    # Try to get from transcripts
    if context.transcripts:
        latest = context.transcripts[0]
        year = latest.get("year")
        quarter = latest.get("quarter")
        if year and quarter:
            try:
                return (int(year), int(quarter))
            except (ValueError, TypeError):
                pass

    # Fallback to computed value
    return get_latest_quarter()


def format_quarter(year: int, quarter: int) -> str:
    """Format year and quarter as 'Q3 2025' style string.

    Args:
        year: The year.
        quarter: The quarter (1-4).

    Returns:
        Formatted string like 'Q3 2025'.
    """
    return f"Q{quarter} {year}"


def get_quarter_range(year: int, quarter: int, lookback: int = 4) -> list[tuple[int, int]]:
    """Get a range of quarters going back from a starting point.

    Args:
        year: Starting year.
        quarter: Starting quarter.
        lookback: Number of quarters to include (including start).

    Returns:
        List of (year, quarter) tuples from most recent to oldest.
    """
    quarters = []
    current_year, current_quarter = year, quarter

    for _ in range(lookback):
        quarters.append((current_year, current_quarter))
        if current_quarter == 1:
            current_year -= 1
            current_quarter = 4
        else:
            current_quarter -= 1

    return quarters


def format_quarters_for_prompt(year: int, quarter: int) -> str:
    """Generate quarter reference text for prompts.

    Args:
        year: Latest year.
        quarter: Latest quarter.

    Returns:
        Text describing the quarter context for LLM prompts.
    """
    latest = format_quarter(year, quarter)
    quarters = get_quarter_range(year, quarter, 4)

    quarter_list = ", ".join(format_quarter(y, q) for y, q in quarters)

    return f"""{latest} is the MOST RECENT quarter with ACTUAL REPORTED earnings (not estimates).
All financial data for {latest} and earlier quarters represents ACTUAL FILED results from SEC filings.
The last 4 quarters with reported actuals: {quarter_list}.
Use {latest} as your baseline. This is real data, not analyst estimates."""
