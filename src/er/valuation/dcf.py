"""
Deterministic DCF (Discounted Cash Flow) Engine.

All calculations are code-based - no LLM arithmetic.
This ensures reproducible, auditable valuation calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DCFInputs:
    """Inputs for DCF calculation."""

    # Revenue projections (year 1-5)
    revenue_projections: list[float]

    # Operating margin trajectory
    operating_margins: list[float]

    # Tax rate
    tax_rate: float = 0.21

    # Depreciation as % of revenue
    depreciation_pct: float = 0.04

    # CapEx as % of revenue
    capex_pct: float = 0.05

    # Working capital change as % of revenue change
    nwc_pct_delta: float = 0.10

    # Terminal growth rate
    terminal_growth: float = 0.025

    # Discount rate (WACC)
    wacc: float = 0.10

    # Current year revenue (for projections)
    current_revenue: float = 0.0


@dataclass
class WACCInputs:
    """Inputs for WACC calculation."""

    # Cost of equity
    risk_free_rate: float = 0.04
    equity_risk_premium: float = 0.05
    beta: float = 1.0

    # Cost of debt
    cost_of_debt: float = 0.05
    tax_rate: float = 0.21

    # Capital structure
    debt_to_capital: float = 0.20


@dataclass
class DCFResult:
    """Result of DCF calculation."""

    # Per-share valuation
    intrinsic_value_per_share: float
    enterprise_value: float
    equity_value: float

    # Components
    pv_fcf: float  # Present value of explicit FCF
    terminal_value: float
    pv_terminal: float  # Present value of terminal

    # Cash flow projections
    fcf_projections: list[float] = field(default_factory=list)
    discount_factors: list[float] = field(default_factory=list)

    # Inputs used
    wacc: float = 0.0
    terminal_growth: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "intrinsic_value_per_share": round(self.intrinsic_value_per_share, 2),
            "enterprise_value": round(self.enterprise_value, 0),
            "equity_value": round(self.equity_value, 0),
            "pv_fcf": round(self.pv_fcf, 0),
            "terminal_value": round(self.terminal_value, 0),
            "pv_terminal": round(self.pv_terminal, 0),
            "fcf_projections": [round(f, 0) for f in self.fcf_projections],
            "discount_factors": [round(d, 4) for d in self.discount_factors],
            "wacc": self.wacc,
            "terminal_growth": self.terminal_growth,
        }


class DCFEngine:
    """Deterministic DCF valuation engine.

    All arithmetic is performed in code - never by LLM.
    This ensures:
    1. Reproducibility
    2. Auditability
    3. Numerical accuracy
    """

    def __init__(self) -> None:
        """Initialize the DCF engine."""
        pass

    def calculate_wacc(self, inputs: WACCInputs) -> float:
        """Calculate Weighted Average Cost of Capital.

        WACC = (E/V) * Re + (D/V) * Rd * (1-T)

        Args:
            inputs: WACC calculation inputs.

        Returns:
            WACC as decimal (e.g., 0.10 for 10%).
        """
        # Cost of equity using CAPM
        cost_of_equity = (
            inputs.risk_free_rate +
            inputs.beta * inputs.equity_risk_premium
        )

        # After-tax cost of debt
        after_tax_cost_of_debt = inputs.cost_of_debt * (1 - inputs.tax_rate)

        # Weighted average
        equity_weight = 1 - inputs.debt_to_capital
        debt_weight = inputs.debt_to_capital

        wacc = (
            equity_weight * cost_of_equity +
            debt_weight * after_tax_cost_of_debt
        )

        return wacc

    def calculate_dcf(
        self,
        inputs: DCFInputs,
        net_debt: float = 0.0,
        shares_outstanding: float = 1.0,
    ) -> DCFResult:
        """Calculate DCF valuation.

        Args:
            inputs: DCF calculation inputs.
            net_debt: Net debt (debt - cash).
            shares_outstanding: Diluted shares outstanding.

        Returns:
            DCFResult with valuation.
        """
        # Calculate FCF for each projection year
        fcf_projections = []
        prev_revenue = inputs.current_revenue

        for i, revenue in enumerate(inputs.revenue_projections):
            margin = inputs.operating_margins[i] if i < len(inputs.operating_margins) else inputs.operating_margins[-1]

            # Operating income
            ebit = revenue * margin

            # After-tax operating income (NOPAT)
            nopat = ebit * (1 - inputs.tax_rate)

            # Add back depreciation
            depreciation = revenue * inputs.depreciation_pct

            # Subtract CapEx
            capex = revenue * inputs.capex_pct

            # Subtract change in NWC
            revenue_change = revenue - prev_revenue
            nwc_change = revenue_change * inputs.nwc_pct_delta

            # Free Cash Flow
            fcf = nopat + depreciation - capex - nwc_change
            fcf_projections.append(fcf)

            prev_revenue = revenue

        # Calculate discount factors
        discount_factors = [
            1 / ((1 + inputs.wacc) ** (i + 1))
            for i in range(len(fcf_projections))
        ]

        # Present value of explicit period FCF
        pv_fcf = sum(
            fcf * df
            for fcf, df in zip(fcf_projections, discount_factors)
        )

        # Terminal value using Gordon Growth Model
        final_fcf = fcf_projections[-1] if fcf_projections else 0
        terminal_value = (
            final_fcf * (1 + inputs.terminal_growth) /
            (inputs.wacc - inputs.terminal_growth)
        )

        # Present value of terminal
        terminal_year = len(fcf_projections)
        pv_terminal = terminal_value / ((1 + inputs.wacc) ** terminal_year)

        # Enterprise value
        enterprise_value = pv_fcf + pv_terminal

        # Equity value
        equity_value = enterprise_value - net_debt

        # Per-share value
        intrinsic_value_per_share = equity_value / shares_outstanding

        return DCFResult(
            intrinsic_value_per_share=intrinsic_value_per_share,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            pv_fcf=pv_fcf,
            terminal_value=terminal_value,
            pv_terminal=pv_terminal,
            fcf_projections=fcf_projections,
            discount_factors=discount_factors,
            wacc=inputs.wacc,
            terminal_growth=inputs.terminal_growth,
        )

    def sensitivity_analysis(
        self,
        inputs: DCFInputs,
        net_debt: float,
        shares_outstanding: float,
        wacc_range: list[float] | None = None,
        terminal_growth_range: list[float] | None = None,
    ) -> dict[str, list[tuple[float, float, float]]]:
        """Run sensitivity analysis on WACC and terminal growth.

        Args:
            inputs: Base DCF inputs.
            net_debt: Net debt.
            shares_outstanding: Shares outstanding.
            wacc_range: WACC values to test.
            terminal_growth_range: Terminal growth values to test.

        Returns:
            Dict with sensitivity results.
        """
        if wacc_range is None:
            wacc_range = [0.08, 0.09, 0.10, 0.11, 0.12]
        if terminal_growth_range is None:
            terminal_growth_range = [0.015, 0.020, 0.025, 0.030, 0.035]

        results: list[tuple[float, float, float]] = []

        for wacc in wacc_range:
            for tg in terminal_growth_range:
                # Create modified inputs
                modified_inputs = DCFInputs(
                    revenue_projections=inputs.revenue_projections,
                    operating_margins=inputs.operating_margins,
                    tax_rate=inputs.tax_rate,
                    depreciation_pct=inputs.depreciation_pct,
                    capex_pct=inputs.capex_pct,
                    nwc_pct_delta=inputs.nwc_pct_delta,
                    terminal_growth=tg,
                    wacc=wacc,
                    current_revenue=inputs.current_revenue,
                )

                result = self.calculate_dcf(
                    modified_inputs, net_debt, shares_outstanding
                )
                results.append((wacc, tg, result.intrinsic_value_per_share))

        return {"sensitivity": results}
