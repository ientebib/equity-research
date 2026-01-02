"""
FMP (Financial Modeling Prep) client for fetching financial data.

This is the PRIMARY data source for the equity research system.
Provides access to:
- Financial statements (income, balance sheet, cash flow)
- Revenue segmentation (product and geographic)
- Earnings call transcripts
- Stock news
- Analyst estimates and price targets
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import orjson

from er.evidence.store import EvidenceStore
from er.exceptions import DataFetchError
from er.logging import get_logger
from er.types import Evidence, SourceTier, ToSRisk

logger = get_logger(__name__)

# Base URL for FMP API
FMP_BASE_URL = "https://financialmodelingprep.com/stable"

# Cache settings
FMP_CACHE_DIR = Path.home() / ".cache" / "equity-research" / "fmp"
FMP_CACHE_TTL_HOURS = 24  # Cache TTL in hours

# News filtering - low-value sources to exclude (opinion/clickbait)
LOW_VALUE_NEWS_SOURCES = {
    "defenseworld.net",  # Politician stock trades - noise
    "stockmarket.com",   # Generic aggregator
    "fool.com",          # "Best stocks to buy" clickbait listicles
    "zacks.com",         # Generic stock analysis, not news
    "247wallst.com",     # Market commentary, not news
    "investopedia.com",  # Educational, not news
    "marketbeat.com",    # "Is this the dip to buy?" opinions
    "youtube.com",       # Video links, not useful as text
    "feeds.benzinga.com",  # Benzinga RSS feed is mostly opinions
    "seekingalpha.com",  # Opinion/analysis, not news
    "benzinga.com",      # "Expert picks" opinion pieces
    "invezz.com",        # "Is it a buy signal" opinions
}

# High-value news sources - actual journalism, not opinion
HIGH_VALUE_NEWS_SOURCES = {
    "cnbc.com",
    "nytimes.com",
    "wsj.com",
    "bloomberg.com",
    "reuters.com",
    "ft.com",
    "geekwire.com",
    "techcrunch.com",
    "businessinsider.com",
    "theverge.com",
    "arstechnica.com",
}


class FMPClient:
    """Client for Financial Modeling Prep API.

    Primary data source for financial data. All fetched data is stored
    in EvidenceStore for citation tracking.
    """

    def __init__(
        self,
        evidence_store: EvidenceStore,
        api_key: str | None = None,
    ) -> None:
        """Initialize FMP client.

        Args:
            evidence_store: Store for persisting fetched data.
            api_key: FMP API key. If None, reads from FMP_API_KEY env var.
        """
        self.evidence_store = evidence_store
        self.api_key = api_key or os.environ.get("FMP_API_KEY")

        if not self.api_key:
            logger.warning("FMP_API_KEY not set - FMP client will fail on API calls")

        self._client: httpx.AsyncClient | None = None

        # Ensure cache directory exists
        FMP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, endpoint: str, params: dict[str, Any] | None) -> str:
        """Generate cache key from endpoint and params."""
        # Exclude apikey from cache key
        cache_params = {k: v for k, v in (params or {}).items() if k != "apikey"}
        key_str = f"{endpoint}:{orjson.dumps(cache_params, option=orjson.OPT_SORT_KEYS).decode()}"
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _cache_path(self, cache_key: str) -> Path:
        """Get cache file path for a key."""
        return FMP_CACHE_DIR / f"{cache_key}.json"

    def _read_cache(self, endpoint: str, params: dict[str, Any] | None) -> dict[str, Any] | list[Any] | None:
        """Read from cache if valid."""
        cache_key = self._cache_key(endpoint, params)
        cache_file = self._cache_path(cache_key)

        if not cache_file.exists():
            return None

        # Check TTL
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600

        if age_hours > FMP_CACHE_TTL_HOURS:
            logger.debug("Cache expired", endpoint=endpoint, age_hours=age_hours)
            return None

        try:
            data = orjson.loads(cache_file.read_bytes())
            logger.info("Cache hit", endpoint=endpoint, cache_key=cache_key, age_hours=round(age_hours, 1))
            return data
        except Exception as e:
            logger.warning("Cache read failed", endpoint=endpoint, error=str(e))
            return None

    def _write_cache(self, endpoint: str, params: dict[str, Any] | None, data: dict[str, Any] | list[Any]) -> None:
        """Write data to cache."""
        cache_key = self._cache_key(endpoint, params)
        cache_file = self._cache_path(cache_key)

        try:
            cache_file.write_bytes(orjson.dumps(data))
            logger.debug("Cache written", endpoint=endpoint, cache_key=cache_key)
        except Exception as e:
            logger.warning("Cache write failed", endpoint=endpoint, error=str(e))

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _fetch(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        source_tier: SourceTier = SourceTier.OFFICIAL,
    ) -> tuple[dict[str, Any] | list[Any], Evidence]:
        """Fetch data from FMP API.

        Args:
            endpoint: API endpoint path (e.g., "income-statement").
            params: Query parameters (symbol will be added automatically).
            source_tier: Source tier for evidence classification.

        Returns:
            Tuple of (parsed JSON data, Evidence record).

        Raises:
            DataFetchError: If the API call fails.
        """
        # Check cache first
        cached_data = self._read_cache(endpoint, params)
        if cached_data is not None:
            # Still store as evidence even from cache
            content = orjson.dumps(cached_data)
            snippet = self._make_snippet(endpoint, params, cached_data)
            evidence = await self.evidence_store.store(
                url=f"fmp://{endpoint}?{self._params_to_string(params)}",
                content=content,
                content_type="application/json",
                source_tier=source_tier,
                tos_risk=ToSRisk.LOW,
                snippet=snippet,
            )
            return cached_data, evidence

        if not self.api_key:
            raise DataFetchError(
                "FMP_API_KEY not configured",
                context={"endpoint": endpoint},
            )

        client = await self._get_client()
        url = f"{FMP_BASE_URL}/{endpoint}"

        # Add API key to params
        request_params = params or {}
        request_params["apikey"] = self.api_key

        logger.info("Fetching from FMP", endpoint=endpoint, params={k: v for k, v in request_params.items() if k != "apikey"})

        try:
            response = await client.get(url, params=request_params)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise DataFetchError(
                f"FMP API error: {e.response.status_code}",
                context={
                    "endpoint": endpoint,
                    "status_code": e.response.status_code,
                    "response": e.response.text[:500] if e.response.text else None,
                },
            ) from e
        except httpx.RequestError as e:
            raise DataFetchError(
                f"FMP request failed: {e}",
                context={"endpoint": endpoint, "error": str(e)},
            ) from e

        # Parse response
        try:
            data = response.json()
        except Exception as e:
            raise DataFetchError(
                "Failed to parse FMP response",
                context={"endpoint": endpoint, "error": str(e)},
            ) from e

        # Check for API errors in response
        if isinstance(data, dict) and "Error Message" in data:
            raise DataFetchError(
                f"FMP API error: {data['Error Message']}",
                context={"endpoint": endpoint, "error": data},
            )

        # Write to cache on successful fetch
        self._write_cache(endpoint, params, data)

        # Store as evidence
        content = orjson.dumps(data)
        snippet = self._make_snippet(endpoint, params, data)

        evidence = await self.evidence_store.store(
            url=f"fmp://{endpoint}?{self._params_to_string(params)}",
            content=content,
            content_type="application/json",
            snippet=snippet,
            title=f"FMP: {endpoint}",
            tos_risk=ToSRisk.NONE,
            source_tier=source_tier,
        )

        logger.info(
            "Fetched from FMP",
            endpoint=endpoint,
            evidence_id=evidence.evidence_id,
            data_size=len(content),
        )

        return data, evidence

    def _params_to_string(self, params: dict[str, Any] | None) -> str:
        """Convert params to query string (excluding apikey)."""
        if not params:
            return ""
        return "&".join(f"{k}={v}" for k, v in params.items() if k != "apikey")

    def _make_snippet(
        self,
        endpoint: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | list[Any],
    ) -> str:
        """Create a human-readable snippet from the data."""
        symbol = params.get("symbol", "N/A") if params else "N/A"

        if isinstance(data, list):
            count = len(data)
            return f"FMP {endpoint} for {symbol}: {count} records"
        elif isinstance(data, dict):
            keys = list(data.keys())[:5]
            return f"FMP {endpoint} for {symbol}: {', '.join(keys)}"
        else:
            return f"FMP {endpoint} for {symbol}"

    # ==================== Financial Statements ====================

    async def get_income_statement(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get income statements.

        Args:
            symbol: Stock ticker symbol.
            period: "annual" or "quarterly".
            limit: Number of periods to fetch.

        Returns:
            Tuple of (list of income statements, Evidence record).
        """
        data, evidence = await self._fetch(
            "income-statement",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_balance_sheet(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get balance sheets.

        Args:
            symbol: Stock ticker symbol.
            period: "annual" or "quarterly".
            limit: Number of periods to fetch.

        Returns:
            Tuple of (list of balance sheets, Evidence record).
        """
        data, evidence = await self._fetch(
            "balance-sheet-statement",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_cash_flow(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get cash flow statements.

        Args:
            symbol: Stock ticker symbol.
            period: "annual" or "quarterly".
            limit: Number of periods to fetch.

        Returns:
            Tuple of (list of cash flow statements, Evidence record).
        """
        data, evidence = await self._fetch(
            "cash-flow-statement",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else [], evidence

    # ==================== Revenue Segmentation ====================

    async def get_revenue_product_segmentation(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get revenue breakdown by product/service.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (revenue segmentation data, Evidence record).
        """
        data, evidence = await self._fetch(
            "revenue-product-segmentation",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_revenue_geographic_segmentation(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get revenue breakdown by geography.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (geographic segmentation data, Evidence record).
        """
        data, evidence = await self._fetch(
            "revenue-geographic-segmentation",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    # ==================== Earnings & Transcripts ====================

    async def get_earnings(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get earnings data.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (earnings data, Evidence record).
        """
        data, evidence = await self._fetch(
            "earnings",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_earnings_transcript(
        self,
        symbol: str,
        year: int,
        quarter: int,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get earnings call transcript.

        Args:
            symbol: Stock ticker symbol.
            year: Calendar year.
            quarter: Quarter (1-4).

        Returns:
            Tuple of (transcript data, Evidence record).
        """
        data, evidence = await self._fetch(
            "earning-call-transcript",
            params={
                "symbol": symbol.upper(),
                "year": year,
                "quarter": quarter,
            },
        )
        return data if isinstance(data, list) else [], evidence

    async def get_recent_transcripts(
        self,
        symbol: str,
        num_quarters: int = 4,
    ) -> list[tuple[dict[str, Any], Evidence]]:
        """Get recent earnings call transcripts.

        Args:
            symbol: Stock ticker symbol.
            num_quarters: Number of recent quarters to fetch.

        Returns:
            List of (transcript data, Evidence record) tuples.
        """
        # Calculate recent quarters
        now = datetime.now(timezone.utc)
        current_year = now.year
        current_quarter = (now.month - 1) // 3 + 1

        results = []
        year, quarter = current_year, current_quarter

        for _ in range(num_quarters):
            # Go back one quarter
            quarter -= 1
            if quarter == 0:
                quarter = 4
                year -= 1

            try:
                transcripts, evidence = await self.get_earnings_transcript(
                    symbol, year, quarter
                )
                if transcripts:
                    results.append((transcripts[0], evidence))
            except DataFetchError as e:
                logger.warning(
                    "Failed to fetch transcript",
                    symbol=symbol,
                    year=year,
                    quarter=quarter,
                    error=str(e),
                )

        return results

    # ==================== News ====================

    def _filter_news(
        self,
        news_items: list[dict[str, Any]],
        max_items: int = 15,
    ) -> list[dict[str, Any]]:
        """Filter news items and strip to essential fields only.

        Removes low-value sources, prioritizes high-value ones, and strips
        useless fields (image URLs, etc.) to minimize context bloat.

        The news serves as "signals" for Discovery - headlines and summaries
        to indicate recent events. Deep Research will do its own web search
        for full details.

        Args:
            news_items: Raw news items from API.
            max_items: Maximum number of filtered items to return.

        Returns:
            Filtered and cleaned news items with only essential fields.
        """
        # Filter out low-value sources
        filtered = [
            item for item in news_items
            if item.get("site", "").lower() not in LOW_VALUE_NEWS_SOURCES
        ]

        # Sort: high-value sources first, then by date
        def sort_key(item: dict[str, Any]) -> tuple[int, str]:
            site = item.get("site", "").lower()
            is_high_value = 0 if site in HIGH_VALUE_NEWS_SOURCES else 1
            date = item.get("publishedDate", "")
            return (is_high_value, date)

        filtered.sort(key=sort_key, reverse=True)

        # Take top N items and strip to essential fields only
        # No image URLs, no full URLs (LLM would try to fetch them)
        result = []
        for item in filtered[:max_items]:
            result.append({
                "date": item.get("publishedDate", "")[:10],  # Just date, not time
                "source": item.get("site", ""),
                "title": item.get("title", ""),
                "summary": item.get("text", ""),  # Just the snippet
            })

        logger.debug(
            "Filtered news",
            original_count=len(news_items),
            filtered_count=len(result),
            removed=len(news_items) - len(filtered),
        )

        return result

    async def get_stock_news(
        self,
        symbol: str,
        limit: int = 50,
        filter_news: bool = True,
        max_filtered: int = 20,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get recent news for a stock.

        Args:
            symbol: Stock ticker symbol.
            limit: Maximum number of news items to fetch from API.
            filter_news: Whether to filter out low-value sources.
            max_filtered: Maximum items to return after filtering.

        Returns:
            Tuple of (news items, Evidence record).
        """
        data, evidence = await self._fetch(
            "news/stock",
            params={"symbols": symbol.upper(), "limit": limit},
            source_tier=SourceTier.NEWS,
        )
        news_items = data if isinstance(data, list) else []

        if filter_news and news_items:
            news_items = self._filter_news(news_items, max_items=max_filtered)

        return news_items, evidence

    # ==================== Analyst Data ====================

    async def get_analyst_estimates(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get analyst estimates.

        Args:
            symbol: Stock ticker symbol.
            period: "annual" or "quarterly".
            limit: Number of periods.

        Returns:
            Tuple of (estimates data, Evidence record).
        """
        data, evidence = await self._fetch(
            "analyst-estimates",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
            source_tier=SourceTier.INSTITUTIONAL,
        )
        return data if isinstance(data, list) else [], evidence

    async def get_price_target_summary(
        self,
        symbol: str,
    ) -> tuple[dict[str, Any], Evidence]:
        """Get price target summary.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (price target summary, Evidence record).
        """
        data, evidence = await self._fetch(
            "price-target-summary",
            params={"symbol": symbol.upper()},
            source_tier=SourceTier.INSTITUTIONAL,
        )
        return data if isinstance(data, dict) else {}, evidence

    async def get_price_target_consensus(
        self,
        symbol: str,
    ) -> tuple[dict[str, Any], Evidence]:
        """Get price target consensus.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (consensus data, Evidence record).
        """
        data, evidence = await self._fetch(
            "price-target-consensus",
            params={"symbol": symbol.upper()},
            source_tier=SourceTier.INSTITUTIONAL,
        )
        return data if isinstance(data, dict) else {}, evidence

    async def get_stock_grades(
        self,
        symbol: str,
        limit: int = 30,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get analyst stock grades/ratings.

        Note: FMP API ignores limit param for grades - returns all historical.
        We truncate client-side to keep context size reasonable.

        Args:
            symbol: Stock ticker symbol.
            limit: Maximum number of grades to return (truncated client-side).

        Returns:
            Tuple of (grades data, Evidence record).
        """
        data, evidence = await self._fetch(
            "grades",
            params={"symbol": symbol.upper()},  # limit ignored by API
            source_tier=SourceTier.INSTITUTIONAL,
        )
        grades = data if isinstance(data, list) else []
        # API returns all historical grades - truncate to recent ones
        return grades[:limit], evidence

    # ==================== Financial Ratios & Metrics ====================

    # The 20 curated ratios for equity research
    CURATED_RATIO_FIELDS = {
        # Expectations / What's Priced In (4)
        "priceToEarningsRatio",
        "priceToEarningsGrowthRatio",
        # evToEBITDA comes from key-metrics
        "freeCashFlowYield",
        # Quality of Earnings (5)
        "incomeQuality",
        "daysOfSalesOutstanding",
        "daysOfInventoryOutstanding",
        "cashConversionCycle",
        "stockBasedCompensationToRevenue",
        # ROIC / Capital Allocation (4)
        "returnOnInvestedCapital",
        "capexToRevenue",
        "capexToDepreciation",
        "researchAndDevelopementToRevenue",
        # Profitability (3)
        "grossProfitMargin",
        "operatingProfitMargin",
        "netProfitMargin",
        # Financial Health (4)
        "debtToEquityRatio",
        "interestCoverageRatio",
        "netDebtToEBITDA",
        "currentRatio",
        # From key-metrics
        "evToEBITDA",
    }

    async def get_financial_ratios(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 3,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get financial ratios.

        Args:
            symbol: Stock ticker symbol.
            period: "annual" or "quarterly".
            limit: Number of periods.

        Returns:
            Tuple of (ratios data, Evidence record).
        """
        data, evidence = await self._fetch(
            "ratios",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_financial_ratios_ttm(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get trailing twelve months financial ratios.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (ratios TTM data, Evidence record).
        """
        data, evidence = await self._fetch(
            "ratios-ttm",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_key_metrics(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 3,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get key metrics.

        Args:
            symbol: Stock ticker symbol.
            period: "annual" or "quarterly".
            limit: Number of periods.

        Returns:
            Tuple of (key metrics data, Evidence record).
        """
        data, evidence = await self._fetch(
            "key-metrics",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_key_metrics_ttm(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get trailing twelve months key metrics.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (key metrics TTM data, Evidence record).
        """
        data, evidence = await self._fetch(
            "key-metrics-ttm",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    async def get_financial_scores(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get financial scores (Altman Z-Score, Piotroski Score).

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (financial scores data, Evidence record).
        """
        data, evidence = await self._fetch(
            "financial-scores",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    def _compute_red_flags(self, ratios: dict[str, Any], scores: dict[str, Any]) -> list[str]:
        """Compute red flags from ratios and scores.

        Args:
            ratios: Combined ratios dict.
            scores: Financial scores dict.

        Returns:
            List of red flag warnings.
        """
        flags = []

        # Quality of Earnings
        income_quality = ratios.get("incomeQuality")
        if income_quality is not None:
            if income_quality < 0.8:
                flags.append("CRITICAL: Income quality below 0.8 — earnings may not be real cash")
            elif income_quality < 0.9:
                flags.append("WARNING: Income quality below 0.9 — investigate accruals")

        # Receivables
        dso = ratios.get("daysOfSalesOutstanding")
        if dso is not None and dso > 60:
            flags.append("WARNING: DSO above 60 days — slow collections or revenue recognition issues")

        # SBC
        sbc_to_rev = ratios.get("stockBasedCompensationToRevenue")
        if sbc_to_rev is not None and sbc_to_rev > 0.15:
            flags.append("WARNING: SBC above 15% of revenue — significant earnings dilution")

        # Leverage
        net_debt_ebitda = ratios.get("netDebtToEBITDA")
        if net_debt_ebitda is not None and net_debt_ebitda > 4:
            flags.append("WARNING: Net debt > 4x EBITDA — high leverage")

        # Bankruptcy risk (Altman Z)
        altman_z = scores.get("altmanZScore")
        if altman_z is not None:
            if altman_z < 1.8:
                flags.append("CRITICAL: Altman Z below 1.8 — distress zone")
            elif altman_z < 2.99:
                flags.append("WARNING: Altman Z in grey zone (1.8-2.99)")

        # Piotroski
        piotroski = scores.get("piotroskiScore")
        if piotroski is not None and piotroski < 3:
            flags.append("CRITICAL: Piotroski score below 3 — weak financial health")

        # ROIC
        roic = ratios.get("returnOnInvestedCapital")
        if roic is not None and roic < 0.08:
            flags.append("WARNING: ROIC below 8% — may be destroying value")

        return flags

    def _interpret_peg(self, peg: float | None) -> str:
        """Generate narrative for PEG ratio."""
        if peg is None:
            return "PEG not available"
        if peg < 0:
            return "Negative PEG — company has negative earnings or growth"
        if peg < 1:
            return f"PEG of {peg:.2f} suggests stock may be undervalued relative to growth"
        if peg < 1.5:
            return f"PEG of {peg:.2f} suggests fair valuation for growth"
        if peg < 2:
            return f"PEG of {peg:.2f} — market expects strong growth to justify premium"
        return f"PEG of {peg:.2f} — high premium, market expects exceptional growth"

    def _interpret_roic(self, roic: float | None) -> str:
        """Generate narrative for ROIC."""
        if roic is None:
            return "ROIC not available"
        if roic < 0:
            return "Negative ROIC — company destroying capital"
        if roic < 0.08:
            return f"ROIC of {roic:.1%} — likely below cost of capital, destroying value"
        if roic < 0.12:
            return f"ROIC of {roic:.1%} — adequate, roughly covering cost of capital"
        if roic < 0.20:
            return f"ROIC of {roic:.1%} — good returns, creating shareholder value"
        return f"ROIC of {roic:.1%} — excellent returns, strong competitive advantage"

    def _interpret_altman(self, z: float | None) -> str:
        """Interpret Altman Z-Score."""
        if z is None:
            return "Not available"
        if z < 1.8:
            return f"Distress zone ({z:.2f}) — elevated bankruptcy risk"
        if z < 2.99:
            return f"Grey zone ({z:.2f}) — some financial stress"
        return f"Safe zone ({z:.2f}) — low bankruptcy risk"

    def _interpret_piotroski(self, score: int | None) -> str:
        """Interpret Piotroski Score."""
        if score is None:
            return "Not available"
        if score <= 2:
            return f"Weak ({score}/9) — poor financial health"
        if score <= 4:
            return f"Below average ({score}/9)"
        if score <= 6:
            return f"Average ({score}/9)"
        if score <= 8:
            return f"Strong ({score}/9) — good financial health"
        return f"Excellent ({score}/9) — very strong financial health"

    def _compute_buyback_check(
        self,
        income_statements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute buyback distortion check from income statements.

        Args:
            income_statements: List of annual income statements (most recent first).

        Returns:
            Buyback check dict with share count change and EPS decomposition.
        """
        if len(income_statements) < 2:
            return {
                "share_count_change_yoy": None,
                "interpretation": "Insufficient data for YoY comparison",
                "eps_growth_decomposition": None,
                "flag": None,
            }

        current = income_statements[0]
        prior = income_statements[1]

        # Get share counts (diluted preferred for accuracy)
        current_shares = current.get("weightedAverageShsOutDil") or current.get("weightedAverageShsOut")
        prior_shares = prior.get("weightedAverageShsOutDil") or prior.get("weightedAverageShsOut")

        if not current_shares or not prior_shares:
            return {
                "share_count_change_yoy": None,
                "interpretation": "Share count data not available",
                "eps_growth_decomposition": None,
                "flag": None,
            }

        # Calculate share count change
        share_change = (current_shares - prior_shares) / prior_shares

        # Get EPS for decomposition
        current_eps = current.get("epsDiluted") or current.get("eps")
        prior_eps = prior.get("epsDiluted") or prior.get("eps")

        # Get revenue for operational growth proxy
        current_revenue = current.get("revenue")
        prior_revenue = prior.get("revenue")

        # Build interpretation
        if share_change < -0.02:  # More than 2% reduction
            interpretation = f"Shares down {abs(share_change):.1%} YoY — active buybacks"
        elif share_change > 0.02:
            interpretation = f"Shares up {share_change:.1%} YoY — dilution from issuance"
        else:
            interpretation = f"Shares roughly flat ({share_change:+.1%} YoY)"

        # EPS decomposition
        eps_decomposition = None
        flag = None

        if current_eps and prior_eps and prior_eps > 0 and current_revenue and prior_revenue:
            eps_growth = (current_eps - prior_eps) / prior_eps
            revenue_growth = (current_revenue - prior_revenue) / prior_revenue

            # Buyback contribution = -share_change (fewer shares = higher EPS)
            buyback_contribution = -share_change if share_change < 0 else 0

            # Operational contribution = total EPS growth - buyback boost
            # This is simplified; true decomposition would need margin analysis
            operational_contribution = eps_growth - buyback_contribution

            eps_decomposition = {
                "total_eps_growth": round(eps_growth, 3),
                "revenue_growth": round(revenue_growth, 3),
                "buyback_contribution": round(buyback_contribution, 3),
                "operational_contribution": round(operational_contribution, 3),
            }

            # Flag if buybacks are driving significant portion of EPS growth
            if eps_growth > 0.05 and buyback_contribution > 0:  # EPS grew >5%
                buyback_pct = buyback_contribution / eps_growth if eps_growth > 0 else 0
                if buyback_pct > 0.3:  # Buybacks drove >30% of EPS growth
                    flag = f"WARNING: ~{buyback_pct:.0%} of EPS growth is buyback-driven, not operational"

        return {
            "share_count_change_yoy": round(share_change, 4),
            "current_shares_diluted": current_shares,
            "prior_shares_diluted": prior_shares,
            "interpretation": interpretation,
            "eps_growth_decomposition": eps_decomposition,
            "flag": flag,
        }

    async def get_quant_metrics(
        self,
        symbol: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """Get curated quant metrics for equity research.

        Fetches ratios, key metrics, scores, and income statements,
        then structures them into the analytical framework with computed red flags.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (structured quant metrics dict, list of evidence IDs).
        """
        symbol = symbol.upper()
        evidence_ids: list[str] = []

        # Fetch all data sources
        ratios_ttm = {}
        key_metrics_ttm = {}
        scores = {}
        income_statements = []

        try:
            data, ev = await self.get_financial_ratios_ttm(symbol)
            if data:
                ratios_ttm = data[0]
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch ratios TTM", symbol=symbol, error=str(e))

        try:
            data, ev = await self.get_key_metrics_ttm(symbol)
            if data:
                key_metrics_ttm = data[0]
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch key metrics TTM", symbol=symbol, error=str(e))

        try:
            data, ev = await self.get_financial_scores(symbol)
            if data:
                scores = data[0]
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch financial scores", symbol=symbol, error=str(e))

        # Fetch income statements for buyback check (need 2 years)
        try:
            data, ev = await self.get_income_statement(symbol, period="annual", limit=2)
            income_statements = data
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch income statements for buyback check", symbol=symbol, error=str(e))

        # Helper to get value (TTM fields have TTM suffix)
        def get_ratio(field: str) -> Any:
            # Try TTM version first
            ttm_field = field + "TTM" if not field.endswith("TTM") else field
            if ttm_field in ratios_ttm:
                return ratios_ttm[ttm_field]
            if ttm_field in key_metrics_ttm:
                return key_metrics_ttm[ttm_field]
            # Try non-TTM
            if field in ratios_ttm:
                return ratios_ttm[field]
            if field in key_metrics_ttm:
                return key_metrics_ttm[field]
            return None

        # Build structured output
        quant_metrics = {
            "expectations": {
                "pe_ratio": get_ratio("priceToEarningsRatio"),
                "peg_ratio": get_ratio("priceToEarningsGrowthRatio"),
                "ev_to_ebitda": get_ratio("evToEBITDA"),
                "fcf_yield": get_ratio("freeCashFlowYield"),
                "implied_growth_narrative": self._interpret_peg(get_ratio("priceToEarningsGrowthRatio")),
            },
            "earnings_quality": {
                "income_quality": get_ratio("incomeQuality"),
                "dso": get_ratio("daysOfSalesOutstanding"),
                "dio": get_ratio("daysOfInventoryOutstanding"),
                "cash_conversion_cycle": get_ratio("cashConversionCycle"),
                "sbc_to_revenue": get_ratio("stockBasedCompensationToRevenue"),
            },
            "capital_allocation": {
                "roic": get_ratio("returnOnInvestedCapital"),
                "capex_to_revenue": get_ratio("capexToRevenue"),
                "capex_to_depreciation": get_ratio("capexToDepreciation"),
                "rd_to_revenue": get_ratio("researchAndDevelopementToRevenue"),
                "roic_assessment": self._interpret_roic(get_ratio("returnOnInvestedCapital")),
            },
            "profitability": {
                "gross_margin": get_ratio("grossProfitMargin"),
                "operating_margin": get_ratio("operatingProfitMargin"),
                "net_margin": get_ratio("netProfitMargin"),
            },
            "financial_health": {
                "debt_to_equity": get_ratio("debtToEquityRatio"),
                "interest_coverage": get_ratio("interestCoverageRatio"),
                "net_debt_to_ebitda": get_ratio("netDebtToEBITDA"),
                "current_ratio": get_ratio("currentRatio"),
            },
            "scores": {
                "altman_z": scores.get("altmanZScore"),
                "piotroski": scores.get("piotroskiScore"),
                "altman_interpretation": self._interpret_altman(scores.get("altmanZScore")),
                "piotroski_interpretation": self._interpret_piotroski(scores.get("piotroskiScore")),
            },
        }

        # Compute buyback distortion check
        buyback_check = self._compute_buyback_check(income_statements)
        quant_metrics["buyback_check"] = buyback_check

        # Compute red flags
        combined_ratios = {**ratios_ttm, **key_metrics_ttm}
        red_flags = self._compute_red_flags(combined_ratios, scores)

        # Add buyback flag if present
        if buyback_check.get("flag"):
            red_flags.append(buyback_check["flag"])

        quant_metrics["red_flags"] = red_flags

        return quant_metrics, evidence_ids

    # ==================== Company Profile ====================

    async def get_company_profile(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get company profile.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Tuple of (profile data, Evidence record).
        """
        data, evidence = await self._fetch(
            "profile",
            params={"symbol": symbol.upper()},
        )
        return data if isinstance(data, list) else [], evidence

    # ==================== Full Company Context ====================

    async def get_full_context(
        self,
        symbol: str,
        include_transcripts: bool = False,  # Requires higher FMP tier - default off
        num_transcript_quarters: int = 4,
    ) -> dict[str, Any]:
        """Fetch all relevant data to build CompanyContext.

        This is the main method used by the Data Orchestrator to gather
        all financial data for a company in one call.

        Args:
            symbol: Stock ticker symbol.
            include_transcripts: Whether to fetch earnings transcripts.
            num_transcript_quarters: Number of transcript quarters to fetch.

        Returns:
            Dict with all fetched data and evidence_ids.
        """
        symbol = symbol.upper()
        logger.info("Fetching full company context", symbol=symbol)

        evidence_ids: list[str] = []
        context: dict[str, Any] = {
            "symbol": symbol,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Fetch profile
        try:
            profiles, ev = await self.get_company_profile(symbol)
            context["profile"] = profiles[0] if profiles else {}
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch profile", symbol=symbol, error=str(e))
            context["profile"] = {}

        # Fetch financial statements (annual)
        try:
            income, ev = await self.get_income_statement(symbol, "annual", 3)
            context["income_statement_annual"] = income
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch income statement", symbol=symbol, error=str(e))
            context["income_statement_annual"] = []

        try:
            balance, ev = await self.get_balance_sheet(symbol, "annual", 3)
            context["balance_sheet_annual"] = balance
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch balance sheet", symbol=symbol, error=str(e))
            context["balance_sheet_annual"] = []

        try:
            cashflow, ev = await self.get_cash_flow(symbol, "annual", 3)
            context["cash_flow_annual"] = cashflow
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch cash flow", symbol=symbol, error=str(e))
            context["cash_flow_annual"] = []

        # Fetch financial statements (quarterly - last 4)
        try:
            income_q, ev = await self.get_income_statement(symbol, "quarterly", 4)
            context["income_statement_quarterly"] = income_q
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch quarterly income", symbol=symbol, error=str(e))
            context["income_statement_quarterly"] = []

        # Fetch segmentation
        try:
            prod_seg, ev = await self.get_revenue_product_segmentation(symbol)
            context["revenue_product_segmentation"] = prod_seg
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch product segmentation", symbol=symbol, error=str(e))
            context["revenue_product_segmentation"] = []

        try:
            geo_seg, ev = await self.get_revenue_geographic_segmentation(symbol)
            context["revenue_geographic_segmentation"] = geo_seg
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch geo segmentation", symbol=symbol, error=str(e))
            context["revenue_geographic_segmentation"] = []

        # Fetch transcripts
        if include_transcripts:
            try:
                transcripts = await self.get_recent_transcripts(symbol, num_transcript_quarters)
                context["transcripts"] = [t[0] for t in transcripts]
                for _, ev in transcripts:
                    evidence_ids.append(ev.evidence_id)
            except DataFetchError as e:
                logger.warning("Failed to fetch transcripts", symbol=symbol, error=str(e))
                context["transcripts"] = []

        # Fetch news (fetch 50, filter to 15 high-quality signals)
        # News serves as signals for Discovery - headlines only, no URLs
        try:
            news, ev = await self.get_stock_news(
                symbol, limit=50, filter_news=True, max_filtered=15
            )
            context["news"] = news
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch news", symbol=symbol, error=str(e))
            context["news"] = []

        # Fetch analyst data
        try:
            estimates, ev = await self.get_analyst_estimates(symbol)
            context["analyst_estimates"] = estimates
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch analyst estimates", symbol=symbol, error=str(e))
            context["analyst_estimates"] = []

        try:
            pt_summary, ev = await self.get_price_target_summary(symbol)
            context["price_target_summary"] = pt_summary
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch price target summary", symbol=symbol, error=str(e))
            context["price_target_summary"] = {}

        try:
            pt_consensus, ev = await self.get_price_target_consensus(symbol)
            context["price_target_consensus"] = pt_consensus
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch price target consensus", symbol=symbol, error=str(e))
            context["price_target_consensus"] = {}

        try:
            grades, ev = await self.get_stock_grades(symbol)
            context["analyst_grades"] = grades
            evidence_ids.append(ev.evidence_id)
        except DataFetchError as e:
            logger.warning("Failed to fetch analyst grades", symbol=symbol, error=str(e))
            context["analyst_grades"] = []

        # Fetch quant metrics (ratios, key metrics, scores with red flags)
        try:
            quant_metrics, quant_evidence_ids = await self.get_quant_metrics(symbol)
            context["quant_metrics"] = quant_metrics
            evidence_ids.extend(quant_evidence_ids)
        except DataFetchError as e:
            logger.warning("Failed to fetch quant metrics", symbol=symbol, error=str(e))
            context["quant_metrics"] = {}

        context["evidence_ids"] = evidence_ids

        logger.info(
            "Fetched full company context",
            symbol=symbol,
            evidence_count=len(evidence_ids),
        )

        return context
