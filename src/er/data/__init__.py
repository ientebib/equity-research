"""
Data fetching package.

This package handles fetching data from external sources:
- FMP (Financial Modeling Prep) - PRIMARY source for all financial data
- Price client (yfinance) - Real-time market data
"""

from er.data.fmp_client import FMPClient
from er.data.price_client import PriceClient

__all__ = [
    "FMPClient",
    "PriceClient",
]
