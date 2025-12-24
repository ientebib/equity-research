"""
Price client for fetching market data.

Uses yfinance as primary provider with support for fallback providers.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import pandas as pd
import yfinance as yf

from er.evidence.store import EvidenceStore
from er.exceptions import DataFetchError
from er.logging import get_logger
from er.types import SourceTier, ToSRisk

logger = get_logger(__name__)

# Thread pool for yfinance (it's not async-native)
_executor = ThreadPoolExecutor(max_workers=4)


class PriceClient:
    """Client for fetching market data.

    Primary provider: yfinance
    Fallback: stub for future providers
    """

    def __init__(self, evidence_store: EvidenceStore) -> None:
        """Initialize price client.

        Args:
            evidence_store: Store for persisting fetched data.
        """
        self.evidence_store = evidence_store

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        """Get current quote data for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with: price, market_cap, shares_outstanding, volume,
                       beta, 52w_high, 52w_low, pe_ratio, dividend_yield

        Raises:
            DataFetchError: If quote data is invalid or unavailable.
        """
        ticker = ticker.upper()
        logger.info("Fetching quote", ticker=ticker)

        # Try primary provider (yfinance)
        try:
            quote = await self._get_yfinance_quote(ticker)
            await self._validate_quote(quote, ticker)
            await self._store_quote_evidence(ticker, quote)
            return quote
        except DataFetchError:
            raise
        except Exception as e:
            logger.warning("yfinance quote failed", ticker=ticker, error=str(e))
            raise DataFetchError(
                f"Failed to get quote for {ticker}",
                context={"ticker": ticker, "error": str(e)},
            ) from e

    async def _get_yfinance_quote(self, ticker: str) -> dict[str, Any]:
        """Get quote from yfinance."""
        loop = asyncio.get_event_loop()

        def _fetch() -> dict[str, Any]:
            stock = yf.Ticker(ticker)
            info = stock.info

            return {
                "ticker": ticker,
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "dividend_yield": info.get("dividendYield"),
                "eps": info.get("trailingEps"),
                "book_value": info.get("bookValue"),
                "price_to_book": info.get("priceToBook"),
                "enterprise_value": info.get("enterpriseValue"),
                "revenue": info.get("totalRevenue"),
                "ebitda": info.get("ebitda"),
                "free_cash_flow": info.get("freeCashflow"),
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange"),
                "name": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }

        return await loop.run_in_executor(_executor, _fetch)

    async def _validate_quote(self, quote: dict[str, Any], ticker: str) -> None:
        """Validate quote data.

        Raises:
            DataFetchError: If required fields are missing or invalid.
        """
        errors = []

        if not quote.get("price") or quote["price"] <= 0:
            errors.append("Price must be > 0")

        if not quote.get("market_cap") or quote["market_cap"] <= 0:
            errors.append("Market cap must be > 0")

        if not quote.get("shares_outstanding") or quote["shares_outstanding"] <= 0:
            errors.append("Shares outstanding must be > 0")

        if errors:
            raise DataFetchError(
                f"Invalid quote data for {ticker}: {', '.join(errors)}",
                context={"ticker": ticker, "quote": quote, "errors": errors},
            )

    async def _store_quote_evidence(self, ticker: str, quote: dict[str, Any]) -> None:
        """Store quote as evidence."""
        import orjson

        content = orjson.dumps(quote)
        snippet = (
            f"{quote.get('name', ticker)}: ${quote['price']:.2f}, "
            f"Market Cap: ${quote['market_cap']:,.0f}, "
            f"P/E: {quote.get('pe_ratio', 'N/A')}"
        )

        await self.evidence_store.store(
            url=f"yfinance://{ticker}/quote",
            content=content,
            content_type="application/json",
            snippet=snippet,
            title=f"Market Data - {quote.get('name', ticker)}",
            tos_risk=ToSRisk.NONE,
            source_tier=SourceTier.INSTITUTIONAL,
        )

    async def get_historical(
        self,
        ticker: str,
        period: str = "1y",
    ) -> pd.DataFrame:
        """Get historical price data.

        Args:
            ticker: Stock ticker symbol.
            period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max).

        Returns:
            DataFrame with OHLCV data.
        """
        ticker = ticker.upper()
        logger.info("Fetching historical data", ticker=ticker, period=period)

        loop = asyncio.get_event_loop()

        def _fetch() -> pd.DataFrame:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period)
            return df

        df = await loop.run_in_executor(_executor, _fetch)

        if df.empty:
            raise DataFetchError(
                f"No historical data for {ticker}",
                context={"ticker": ticker, "period": period},
            )

        # Store summary as evidence
        import orjson

        summary = {
            "ticker": ticker,
            "period": period,
            "start_date": df.index[0].isoformat() if len(df) > 0 else None,
            "end_date": df.index[-1].isoformat() if len(df) > 0 else None,
            "data_points": len(df),
            "high": float(df["High"].max()) if "High" in df.columns else None,
            "low": float(df["Low"].min()) if "Low" in df.columns else None,
            "avg_volume": float(df["Volume"].mean()) if "Volume" in df.columns else None,
        }

        await self.evidence_store.store(
            url=f"yfinance://{ticker}/history/{period}",
            content=orjson.dumps(summary),
            content_type="application/json",
            snippet=f"Historical data for {ticker}: {len(df)} data points from {summary['start_date']} to {summary['end_date']}",
            title=f"Historical Prices - {ticker} ({period})",
            tos_risk=ToSRisk.NONE,
            source_tier=SourceTier.INSTITUTIONAL,
        )

        logger.info(
            "Fetched historical data",
            ticker=ticker,
            period=period,
            rows=len(df),
        )

        return df

    async def get_financials(self, ticker: str) -> dict[str, pd.DataFrame]:
        """Get financial statements from yfinance.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with income_statement, balance_sheet, cash_flow DataFrames.
        """
        ticker = ticker.upper()
        logger.info("Fetching financials", ticker=ticker)

        loop = asyncio.get_event_loop()

        def _fetch() -> dict[str, pd.DataFrame]:
            stock = yf.Ticker(ticker)
            return {
                "income_statement": stock.financials,
                "balance_sheet": stock.balance_sheet,
                "cash_flow": stock.cashflow,
                "quarterly_income": stock.quarterly_financials,
                "quarterly_balance": stock.quarterly_balance_sheet,
                "quarterly_cash_flow": stock.quarterly_cashflow,
            }

        financials = await loop.run_in_executor(_executor, _fetch)

        logger.info(
            "Fetched financials",
            ticker=ticker,
            has_income=not financials["income_statement"].empty,
            has_balance=not financials["balance_sheet"].empty,
            has_cashflow=not financials["cash_flow"].empty,
        )

        return financials
