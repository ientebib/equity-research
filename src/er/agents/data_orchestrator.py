"""
Data Orchestrator Agent (Stage 1).

Fetches all relevant data from FMP API to build CompanyContext.
This is the first stage of the pipeline - data gathering.

Model: GPT-5.2 (medium reasoning) - decides which API calls to make.
"""

from __future__ import annotations

from typing import Any

from er.agents.base import Agent, AgentContext
from er.data.fmp_client import FMPClient
from er.data.price_client import PriceClient
from er.types import CompanyContext, Phase, RunState


class DataOrchestratorAgent(Agent):
    """Stage 1: Data Orchestrator.

    Responsible for:
    1. Determining which FMP API endpoints to call for a given ticker
    2. Fetching all relevant financial data
    3. Building the CompanyContext object
    4. Storing all evidence with proper citations

    The CompanyContext is then passed to ALL subsequent agents.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Data Orchestrator.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)
        self._fmp_client: FMPClient | None = None
        self._price_client: PriceClient | None = None

    @property
    def name(self) -> str:
        return "data_orchestrator"

    @property
    def role(self) -> str:
        return "Fetch and organize all financial data from FMP API"

    async def _get_fmp_client(self) -> FMPClient:
        """Get or create FMP client."""
        if self._fmp_client is None:
            self._fmp_client = FMPClient(
                evidence_store=self.evidence_store,
                api_key=self.settings.FMP_API_KEY,
            )
        return self._fmp_client

    async def _get_price_client(self) -> PriceClient:
        """Get or create price client (for additional market data)."""
        if self._price_client is None:
            self._price_client = PriceClient(evidence_store=self.evidence_store)
        return self._price_client

    async def run(
        self,
        run_state: RunState,
        include_transcripts: bool = True,
        num_transcript_quarters: int = 4,
        manual_transcripts: list[dict] | None = None,
        **kwargs: Any,
    ) -> CompanyContext:
        """Execute Stage 1: Fetch all data and build CompanyContext.

        Args:
            run_state: Current run state with ticker.
            include_transcripts: Whether to fetch earnings transcripts.
            num_transcript_quarters: Number of transcript quarters to fetch.
            manual_transcripts: User-provided transcripts (from CLI).

        Returns:
            CompanyContext with all fetched data.
        """
        self.log_info(
            "Starting data orchestration",
            ticker=run_state.ticker,
            has_manual_transcripts=bool(manual_transcripts),
        )

        run_state.phase = Phase.FETCH_DATA

        # Get FMP client
        fmp_client = await self._get_fmp_client()

        # If we have manual transcripts, don't try to fetch from FMP
        fetch_transcripts = include_transcripts and not manual_transcripts

        # Fetch full context from FMP
        self.log_info("Fetching company context from FMP", ticker=run_state.ticker)

        fmp_data = await fmp_client.get_full_context(
            symbol=run_state.ticker,
            include_transcripts=fetch_transcripts,
            num_transcript_quarters=num_transcript_quarters,
        )

        # Convert to CompanyContext
        company_context = CompanyContext.from_fmp_data(fmp_data)

        # Inject manual transcripts if provided
        if manual_transcripts:
            self.log_info(
                "Using manual transcripts",
                count=len(manual_transcripts),
            )
            company_context.transcripts = manual_transcripts

        # Fetch real-time market data from yfinance
        try:
            price_client = await self._get_price_client()
            quote = await price_client.get_quote(run_state.ticker)

            # Store in dedicated market_data field
            company_context.market_data = {
                "price": quote.get("price"),
                "market_cap": quote.get("market_cap"),
                "pe_ratio": quote.get("pe_ratio"),
                "beta": quote.get("beta"),
                "volume": quote.get("volume"),
                "avg_volume": quote.get("avg_volume"),
                "fifty_two_week_high": quote.get("fifty_two_week_high"),
                "fifty_two_week_low": quote.get("fifty_two_week_low"),
                "forward_pe": quote.get("forward_pe"),
                "dividend_yield": quote.get("dividend_yield"),
            }

            # Also add to profile for backward compatibility
            if company_context.profile:
                company_context.profile["current_price"] = quote.get("price")
                company_context.profile["current_market_cap"] = quote.get("market_cap")
                company_context.profile["pe_ratio"] = quote.get("pe_ratio")
                company_context.profile["beta"] = quote.get("beta")
        except Exception as e:
            self.log_warning(
                "Failed to fetch real-time market data",
                ticker=run_state.ticker,
                error=str(e),
            )

        # Update run state with market data
        run_state.market_data = {
            "symbol": company_context.symbol,
            "company_name": company_context.company_name,
            "latest_revenue": company_context.latest_revenue,
            "latest_net_income": company_context.latest_net_income,
            "profile": company_context.profile,
        }

        self.log_info(
            "Completed data orchestration",
            ticker=run_state.ticker,
            evidence_count=len(company_context.evidence_ids),
            has_transcripts=bool(company_context.transcripts),
            has_segments=bool(company_context.revenue_product_segmentation),
        )

        return company_context

    async def close(self) -> None:
        """Close any open clients."""
        if self._fmp_client:
            await self._fmp_client.close()
            self._fmp_client = None
