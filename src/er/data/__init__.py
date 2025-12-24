"""
Data fetching package.

This package handles fetching data from external sources:
- FMP (Financial Modeling Prep) - PRIMARY source
- SEC EDGAR filings (fallback)
- Market data (yfinance)
- Earnings call transcripts
- News and press releases
"""

from er.data.fmp_client import FMPClient
from er.data.news_client import NewsClient
from er.data.price_client import PriceClient
from er.data.sec_client import SECClient
from er.data.transcript_client import TranscriptClient

__all__ = [
    "FMPClient",
    "NewsClient",
    "PriceClient",
    "SECClient",
    "TranscriptClient",
]
