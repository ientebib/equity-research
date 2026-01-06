"""
Reverse DCF Engine.

Determines what growth assumptions are implied by current market price.
All calculations are code-based - no LLM arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReverseDCFInputs:
    """Inputs for reverse DCF calculation."""

    # Current market data
    current_price: float
    shares_outstanding: float
    net_debt: float

    # Financial assumptions
    current_revenue: float
    current_margin: float  # Operating margin
    tax_rate: float = 0.21

    # FCF conversion assumptions
    depreciation_pct: float = 0.04
    capex_pct: float = 0.05
    nwc_pct_delta: float = 0.10

    # Discount rate
    wacc: float = 0.10

    # Terminal assumptions
    terminal_margin: float | None = None  # None means same as current
    terminal_growth: float = 0.025

    # Projection period
    projection_years: int = 5


@dataclass
class ReverseDCFResult:
    """Result of reverse DCF calculation."""

    # Implied growth rate
    implied_revenue_cagr: float

    # Market vs calculated
    market_cap: float
    enterprise_value: float

    # Derived figures
    implied_year5_revenue: float
    implied_year5_fcf: float

    # Reasonableness check
    is_reasonable: bool
    reasonableness_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "implied_revenue_cagr": round(self.implied_revenue_cagr * 100, 2),
            "implied_revenue_cagr_pct": f"{self.implied_revenue_cagr * 100:.1f}%",
            "market_cap": round(self.market_cap, 0),
            "enterprise_value": round(self.enterprise_value, 0),
            "implied_year5_revenue": round(self.implied_year5_revenue, 0),
            "implied_year5_fcf": round(self.implied_year5_fcf, 0),
            "is_reasonable": self.is_reasonable,
            "reasonableness_notes": self.reasonableness_notes,
        }


class ReverseDCFEngine:
    """Reverse DCF engine to find implied growth.

    Given a market price, determines what revenue growth rate
    would justify that price under DCF assumptions.
    """

    def __init__(self) -> None:
        """Initialize the engine."""
        pass

    def calculate_implied_growth(
        self,
        inputs: ReverseDCFInputs,
    ) -> ReverseDCFResult:
        """Calculate implied revenue growth rate from market price.

        Uses binary search to find the growth rate that produces
        a DCF value equal to the current market price.

        Args:
            inputs: Reverse DCF inputs.

        Returns:
            ReverseDCFResult with implied growth.
        """
        # Market-implied enterprise value
        market_cap = inputs.current_price * inputs.shares_outstanding
        enterprise_value = market_cap + inputs.net_debt

        # Binary search for implied growth rate
        low_growth = -0.20  # -20%
        high_growth = 0.50  # 50%
        tolerance = 0.0001  # 0.01%

        implied_cagr = self._binary_search_growth(
            enterprise_value=enterprise_value,
            inputs=inputs,
            low=low_growth,
            high=high_growth,
            tolerance=tolerance,
        )

        # Calculate implied figures at that growth rate
        implied_year5_revenue = inputs.current_revenue * ((1 + implied_cagr) ** inputs.projection_years)
        terminal_margin = inputs.terminal_margin or inputs.current_margin
        implied_year5_fcf = self._calculate_fcf(
            revenue=implied_year5_revenue,
            margin=terminal_margin,
            tax_rate=inputs.tax_rate,
            depreciation_pct=inputs.depreciation_pct,
            capex_pct=inputs.capex_pct,
            nwc_pct_delta=0,  # No change in terminal year
        )

        # Reasonableness check
        is_reasonable, notes = self._check_reasonableness(
            implied_cagr=implied_cagr,
            current_margin=inputs.current_margin,
            terminal_margin=terminal_margin,
        )

        return ReverseDCFResult(
            implied_revenue_cagr=implied_cagr,
            market_cap=market_cap,
            enterprise_value=enterprise_value,
            implied_year5_revenue=implied_year5_revenue,
            implied_year5_fcf=implied_year5_fcf,
            is_reasonable=is_reasonable,
            reasonableness_notes=notes,
        )

    def _binary_search_growth(
        self,
        enterprise_value: float,
        inputs: ReverseDCFInputs,
        low: float,
        high: float,
        tolerance: float,
        max_iterations: int = 50,
    ) -> float:
        """Binary search to find growth rate that produces target EV."""
        for _ in range(max_iterations):
            mid = (low + high) / 2
            ev = self._calculate_ev_at_growth(inputs, mid)

            if abs(ev - enterprise_value) / enterprise_value < tolerance:
                return mid

            if ev < enterprise_value:
                low = mid
            else:
                high = mid

        return (low + high) / 2

    def _calculate_ev_at_growth(
        self,
        inputs: ReverseDCFInputs,
        growth_rate: float,
    ) -> float:
        """Calculate enterprise value at a given growth rate."""
        # Project revenues
        revenues = [
            inputs.current_revenue * ((1 + growth_rate) ** (i + 1))
            for i in range(inputs.projection_years)
        ]

        # Project margins (linear interpolation to terminal)
        terminal_margin = inputs.terminal_margin or inputs.current_margin
        margins = [
            inputs.current_margin + (terminal_margin - inputs.current_margin) * (i + 1) / inputs.projection_years
            for i in range(inputs.projection_years)
        ]

        # Calculate FCF for each year
        prev_revenue = inputs.current_revenue
        fcfs = []
        for i, (revenue, margin) in enumerate(zip(revenues, margins)):
            fcf = self._calculate_fcf(
                revenue=revenue,
                margin=margin,
                tax_rate=inputs.tax_rate,
                depreciation_pct=inputs.depreciation_pct,
                capex_pct=inputs.capex_pct,
                nwc_pct_delta=inputs.nwc_pct_delta,
                revenue_change=revenue - prev_revenue,
            )
            fcfs.append(fcf)
            prev_revenue = revenue

        # Present value of explicit FCF
        pv_fcf = sum(
            fcf / ((1 + inputs.wacc) ** (i + 1))
            for i, fcf in enumerate(fcfs)
        )

        # Terminal value
        final_fcf = fcfs[-1] if fcfs else 0
        terminal_value = (
            final_fcf * (1 + inputs.terminal_growth) /
            (inputs.wacc - inputs.terminal_growth)
        )
        pv_terminal = terminal_value / ((1 + inputs.wacc) ** inputs.projection_years)

        return pv_fcf + pv_terminal

    def _calculate_fcf(
        self,
        revenue: float,
        margin: float,
        tax_rate: float,
        depreciation_pct: float,
        capex_pct: float,
        nwc_pct_delta: float,
        revenue_change: float = 0,
    ) -> float:
        """Calculate free cash flow."""
        ebit = revenue * margin
        nopat = ebit * (1 - tax_rate)
        depreciation = revenue * depreciation_pct
        capex = revenue * capex_pct
        nwc_change = revenue_change * nwc_pct_delta

        return nopat + depreciation - capex - nwc_change

    def _check_reasonableness(
        self,
        implied_cagr: float,
        current_margin: float,
        terminal_margin: float,
    ) -> tuple[bool, list[str]]:
        """Check if implied assumptions are reasonable."""
        notes = []
        is_reasonable = True

        # Check growth rate
        if implied_cagr > 0.30:
            notes.append(f"Implied growth ({implied_cagr:.1%}) exceeds 30% - very aggressive")
            is_reasonable = False
        elif implied_cagr > 0.20:
            notes.append(f"Implied growth ({implied_cagr:.1%}) exceeds 20% - aggressive")
        elif implied_cagr < 0:
            notes.append(f"Implied growth ({implied_cagr:.1%}) is negative - suggests decline priced in")
            is_reasonable = False

        # Check margin
        if terminal_margin > 0.40:
            notes.append(f"Terminal margin ({terminal_margin:.1%}) above 40% - very high")
        elif terminal_margin > 0.30:
            notes.append(f"Terminal margin ({terminal_margin:.1%}) above 30% - elevated")

        if not notes:
            notes.append("Implied assumptions appear reasonable")

        return is_reasonable, notes


def calculate_implied_growth_simple(
    price: float,
    shares: float,
    revenue: float,
    margin: float,
    net_debt: float = 0,
    wacc: float = 0.10,
    terminal_growth: float = 0.025,
) -> ReverseDCFResult:
    """Convenience function for quick reverse DCF.

    Args:
        price: Current stock price.
        shares: Shares outstanding.
        revenue: Current revenue.
        margin: Current operating margin.
        net_debt: Net debt.
        wacc: Discount rate.
        terminal_growth: Terminal growth rate.

    Returns:
        ReverseDCFResult with implied growth.
    """
    inputs = ReverseDCFInputs(
        current_price=price,
        shares_outstanding=shares,
        net_debt=net_debt,
        current_revenue=revenue,
        current_margin=margin,
        wacc=wacc,
        terminal_growth=terminal_growth,
    )

    engine = ReverseDCFEngine()
    return engine.calculate_implied_growth(inputs)
