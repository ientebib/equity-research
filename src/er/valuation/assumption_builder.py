"""
Assumption Builder for DCF Valuation.

Derives DCF inputs from historical financial data and research findings,
replacing hardcoded placeholder assumptions with data-driven estimates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from er.types import CompanyContext, VerifiedFact, VerifiedResearchPackage
from er.valuation.dcf import DCFInputs, WACCInputs


@dataclass
class AssumptionSet:
    """Complete set of assumptions for valuation."""

    # Growth assumptions
    revenue_cagr: float  # 5-year revenue CAGR
    revenue_projections: list[float]  # 5-year revenue projections

    # Margin assumptions
    current_operating_margin: float
    operating_margins: list[float]  # 5-year margin trajectory

    # WACC inputs
    wacc: float
    wacc_inputs: WACCInputs

    # Terminal assumptions
    terminal_growth: float

    # Metadata about sources
    sources: dict[str, str]  # What data each assumption is based on


class AssumptionBuilder:
    """Builds DCF assumptions from company data and research.

    Derives assumptions from:
    1. Historical financial statements (FMP data)
    2. Analyst estimates
    3. Verified facts from research
    4. Industry benchmarks
    """

    # Default assumptions when data is missing
    DEFAULT_RISK_FREE_RATE = 0.04  # 4% - approximate 10-year Treasury
    DEFAULT_EQUITY_RISK_PREMIUM = 0.05  # 5% historical ERP
    DEFAULT_TERMINAL_GROWTH = 0.025  # 2.5% - long-term GDP growth
    DEFAULT_TAX_RATE = 0.21  # US corporate tax rate

    def __init__(self) -> None:
        """Initialize the assumption builder."""
        pass

    def build(
        self,
        company_context: CompanyContext,
        verified_package: VerifiedResearchPackage | None = None,
    ) -> AssumptionSet:
        """Build assumptions from company data and research.

        Args:
            company_context: CompanyContext with financial data.
            verified_package: Optional verified facts from research.

        Returns:
            AssumptionSet with data-driven assumptions.
        """
        sources: dict[str, str] = {}

        # Extract historical growth rate
        revenue_cagr, growth_source = self._calculate_historical_growth(company_context)
        sources["revenue_cagr"] = growth_source

        # Check for analyst estimates
        analyst_growth = self._get_analyst_growth_estimate(company_context)
        if analyst_growth is not None:
            # Blend historical with analyst estimates (60/40)
            blended_growth = 0.6 * revenue_cagr + 0.4 * analyst_growth
            sources["revenue_cagr"] += f" + analyst estimates ({analyst_growth:.1%})"
            revenue_cagr = blended_growth

        # Get current revenue
        current_revenue = self._get_current_revenue(company_context)

        # Build revenue projections
        revenue_projections = self._build_revenue_projections(
            current_revenue, revenue_cagr
        )

        # Calculate operating margin and trajectory
        current_margin, margin_source = self._calculate_operating_margin(company_context)
        sources["operating_margin"] = margin_source

        # Build margin trajectory (assume slight improvement)
        operating_margins = self._build_margin_trajectory(current_margin)

        # Calculate WACC
        wacc_inputs = self._build_wacc_inputs(company_context)
        wacc = self._calculate_wacc(wacc_inputs)
        sources["wacc"] = f"CAPM with beta={wacc_inputs.beta:.2f}"

        # Terminal growth - use GDP assumption but cap relative to WACC
        terminal_growth = min(self.DEFAULT_TERMINAL_GROWTH, wacc - 0.02)
        sources["terminal_growth"] = "Long-term GDP growth assumption"

        return AssumptionSet(
            revenue_cagr=revenue_cagr,
            revenue_projections=revenue_projections,
            current_operating_margin=current_margin,
            operating_margins=operating_margins,
            wacc=wacc,
            wacc_inputs=wacc_inputs,
            terminal_growth=terminal_growth,
            sources=sources,
        )

    def build_dcf_inputs(
        self,
        company_context: CompanyContext,
        verified_package: VerifiedResearchPackage | None = None,
    ) -> DCFInputs:
        """Build DCFInputs directly from company data.

        Convenience method that returns DCFInputs ready for DCFEngine.

        Args:
            company_context: CompanyContext with financial data.
            verified_package: Optional verified facts from research.

        Returns:
            DCFInputs ready for DCF calculation.
        """
        assumptions = self.build(company_context, verified_package)

        return DCFInputs(
            revenue_projections=assumptions.revenue_projections,
            operating_margins=assumptions.operating_margins,
            wacc=assumptions.wacc,
            terminal_growth=assumptions.terminal_growth,
            current_revenue=assumptions.revenue_projections[0] / (1 + assumptions.revenue_cagr)
            if assumptions.revenue_projections else 0,
        )

    def _calculate_historical_growth(
        self, company_context: CompanyContext
    ) -> tuple[float, str]:
        """Calculate historical revenue CAGR from income statements.

        Returns:
            Tuple of (growth_rate, source_description).
        """
        income_annual = company_context.income_statement_annual or []

        if len(income_annual) < 2:
            return 0.10, "Default (insufficient historical data)"

        # Get revenues for available years (most recent first)
        revenues = []
        for stmt in income_annual[:5]:  # Up to 5 years
            rev = stmt.get("revenue", 0)
            if rev > 0:
                revenues.append(rev)

        if len(revenues) < 2:
            return 0.10, "Default (insufficient revenue data)"

        # Calculate CAGR: (end/start)^(1/n) - 1
        # revenues[0] is most recent, revenues[-1] is oldest
        start_revenue = revenues[-1]
        end_revenue = revenues[0]
        years = len(revenues) - 1

        if start_revenue <= 0:
            return 0.10, "Default (invalid start revenue)"

        cagr = (end_revenue / start_revenue) ** (1 / years) - 1

        # Cap at reasonable range
        cagr = max(-0.20, min(0.50, cagr))  # -20% to +50%

        return cagr, f"Historical {years}-year CAGR from income statements"

    def _get_analyst_growth_estimate(
        self, company_context: CompanyContext
    ) -> float | None:
        """Extract consensus growth estimate from analyst estimates.

        Returns:
            Estimated growth rate or None if not available.
        """
        estimates = company_context.analyst_estimates or []

        if not estimates:
            return None

        # Look for revenue estimates in next year vs current
        current_rev = None
        next_rev = None

        for est in estimates[:3]:  # Check recent estimates
            period = est.get("period", "")
            rev = est.get("estimatedRevenueAvg", 0)

            if "2024" in str(period) or "current" in str(period).lower():
                current_rev = rev
            elif "2025" in str(period) or "next" in str(period).lower():
                next_rev = rev

        if current_rev and next_rev and current_rev > 0:
            return (next_rev / current_rev) - 1

        return None

    def _get_current_revenue(self, company_context: CompanyContext) -> float:
        """Get most recent annual revenue."""
        income = company_context.income_statement_annual or []
        if income:
            return income[0].get("revenue", 0)
        return 0

    def _build_revenue_projections(
        self, current_revenue: float, cagr: float
    ) -> list[float]:
        """Build 5-year revenue projections."""
        if current_revenue <= 0:
            return [1e9 * (1 + cagr) ** i for i in range(1, 6)]  # Default $1B base

        # Gradually fade growth toward terminal rate
        fade_factor = 0.9  # Growth fades 10% per year toward maturity
        projections = []
        prev_rev = current_revenue
        growth = cagr

        for i in range(5):
            projected = prev_rev * (1 + growth)
            projections.append(projected)
            prev_rev = projected
            # Fade growth toward 3%
            growth = growth * fade_factor + 0.03 * (1 - fade_factor)

        return projections

    def _calculate_operating_margin(
        self, company_context: CompanyContext
    ) -> tuple[float, str]:
        """Calculate current operating margin from income statements.

        Returns:
            Tuple of (margin, source_description).
        """
        income = company_context.income_statement_annual or []

        if not income:
            return 0.15, "Default (no income statement data)"

        # Get most recent year
        latest = income[0]
        revenue = latest.get("revenue", 0)
        operating_income = latest.get("operatingIncome", 0)

        if revenue <= 0:
            return 0.15, "Default (no revenue)"

        margin = operating_income / revenue

        # Sanity check
        margin = max(-0.50, min(0.60, margin))  # -50% to +60%

        return margin, "Most recent annual income statement"

    def _build_margin_trajectory(self, current_margin: float) -> list[float]:
        """Build 5-year margin trajectory.

        Assumes gradual margin improvement/normalization toward industry average.
        """
        target_margin = max(current_margin, 0.15)  # At least 15% or current
        improvement_per_year = 0.01  # 1% per year improvement cap

        margins = []
        margin = current_margin

        for _ in range(5):
            if margin < target_margin:
                margin = min(margin + improvement_per_year, target_margin)
            margins.append(margin)

        return margins

    def _build_wacc_inputs(self, company_context: CompanyContext) -> WACCInputs:
        """Build WACC inputs from company data."""
        # Get beta from profile or market data
        beta = 1.0
        profile = company_context.profile or {}
        market_data = getattr(company_context, "market_data", {}) or {}

        if profile.get("beta"):
            beta = float(profile["beta"])
        elif market_data.get("beta"):
            beta = float(market_data["beta"])

        # Sanity check beta
        beta = max(0.5, min(2.5, beta))

        # Get debt from balance sheet
        balance_sheet = company_context.balance_sheet_annual or []
        debt_to_capital = 0.20  # Default

        if balance_sheet:
            latest = balance_sheet[0]
            total_debt = latest.get("totalDebt", 0)
            total_equity = latest.get("totalStockholdersEquity", 0)
            total_capital = total_debt + total_equity

            if total_capital > 0:
                debt_to_capital = total_debt / total_capital
                debt_to_capital = max(0, min(0.80, debt_to_capital))

        return WACCInputs(
            risk_free_rate=self.DEFAULT_RISK_FREE_RATE,
            equity_risk_premium=self.DEFAULT_EQUITY_RISK_PREMIUM,
            beta=beta,
            cost_of_debt=0.05,  # Could derive from interest expense / debt
            tax_rate=self.DEFAULT_TAX_RATE,
            debt_to_capital=debt_to_capital,
        )

    def _calculate_wacc(self, inputs: WACCInputs) -> float:
        """Calculate WACC from inputs."""
        cost_of_equity = (
            inputs.risk_free_rate + inputs.beta * inputs.equity_risk_premium
        )

        after_tax_cost_of_debt = inputs.cost_of_debt * (1 - inputs.tax_rate)

        equity_weight = 1 - inputs.debt_to_capital
        debt_weight = inputs.debt_to_capital

        wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt

        return wacc
