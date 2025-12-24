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

import os
from datetime import datetime, timezone
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

    async def get_stock_news(
        self,
        symbol: str,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get recent news for a stock.

        Args:
            symbol: Stock ticker symbol.
            limit: Maximum number of news items.

        Returns:
            Tuple of (news items, Evidence record).
        """
        data, evidence = await self._fetch(
            "news/stock",
            params={"symbols": symbol.upper(), "limit": limit},
            source_tier=SourceTier.NEWS,
        )
        return data if isinstance(data, list) else [], evidence

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
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], Evidence]:
        """Get analyst stock grades/ratings.

        Args:
            symbol: Stock ticker symbol.
            limit: Maximum number of grades.

        Returns:
            Tuple of (grades data, Evidence record).
        """
        data, evidence = await self._fetch(
            "grades",
            params={"symbol": symbol.upper(), "limit": limit},
            source_tier=SourceTier.INSTITUTIONAL,
        )
        return data if isinstance(data, list) else [], evidence

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
        include_transcripts: bool = True,
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

        # Fetch news
        try:
            news, ev = await self.get_stock_news(symbol, 30)
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

        context["evidence_ids"] = evidence_ids

        logger.info(
            "Fetched full company context",
            symbol=symbol,
            evidence_count=len(evidence_ids),
        )

        return context
