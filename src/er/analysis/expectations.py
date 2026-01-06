"""
Implied Expectations Analysis.

Computes "what's priced in" by reverse-engineering current valuation
to determine what growth, margins, and other metrics the market expects.

Key insight: The current stock price embeds assumptions. Making those
assumptions explicit helps analysts evaluate whether they're reasonable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from er.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ImpliedExpectations:
    """Implied market expectations derived from current valuation.

    Reverse-engineers what growth, margins, and returns the market
    is pricing in, enabling analysts to assess if those are reasonable.
    """

    # Current valuation metrics
    current_price: float
    market_cap: float
    current_pe: float | None
    current_ev_ebitda: float | None
    current_ev_revenue: float | None

    # Implied growth expectations
    implied_revenue_growth_5yr: float | None  # CAGR needed to justify valuation
    implied_eps_growth_5yr: float | None
    implied_terminal_growth: float  # Long-term sustainable growth

    # Implied margin expectations
    implied_margin_trajectory: str  # "expanding", "stable", "contracting"
    implied_terminal_margin: float | None  # Long-term operating margin

    # Required assumptions for current price to be "fair"
    required_assumptions: list[str] = field(default_factory=list)
    # e.g., ["Revenue must grow 15%+ for 5 years", "Margins must expand 500bps"]

    # Upside catalysts (things that could make stock worth more)
    upside_catalysts: list[dict[str, Any]] = field(default_factory=list)
    # {"catalyst": "...", "probability": "medium", "potential_impact": "+15%"}

    # Downside catalysts (risks)
    downside_catalysts: list[dict[str, Any]] = field(default_factory=list)
    # {"catalyst": "...", "probability": "medium", "potential_impact": "-20%"}

    # Comparative analysis
    vs_historical_average: str = ""  # "above", "below", "in-line"
    vs_sector_peers: str = ""  # "premium", "discount", "in-line"
    premium_discount_pct: float | None = None

    # Scenario analysis summary
    bull_case_value: float | None = None
    base_case_value: float | None = None
    bear_case_value: float | None = None

    def to_prompt_string(self) -> str:
        """Format for LLM prompt."""
        lines = [
            "## What's Priced In",
            "",
            f"**Current Valuation:** {self._format_valuation()}",
            "",
            "### Implied Expectations",
        ]

        if self.implied_revenue_growth_5yr:
            lines.append(f"- Revenue CAGR (5yr): {self.implied_revenue_growth_5yr:.1%}")
        if self.implied_eps_growth_5yr:
            lines.append(f"- EPS CAGR (5yr): {self.implied_eps_growth_5yr:.1%}")
        if self.implied_terminal_margin:
            lines.append(f"- Terminal Margin: {self.implied_terminal_margin:.1%}")
        lines.append(f"- Margin Trajectory: {self.implied_margin_trajectory}")

        if self.required_assumptions:
            lines.append("\n### Required Assumptions")
            for assumption in self.required_assumptions[:5]:
                lines.append(f"- {assumption}")

        if self.upside_catalysts:
            lines.append("\n### Upside Catalysts")
            for cat in self.upside_catalysts[:3]:
                prob = cat.get('probability', 'unknown')
                impact = cat.get('potential_impact', '')
                lines.append(f"- {cat.get('catalyst', '?')} ({prob}, {impact})")

        if self.downside_catalysts:
            lines.append("\n### Downside Risks")
            for cat in self.downside_catalysts[:3]:
                prob = cat.get('probability', 'unknown')
                impact = cat.get('potential_impact', '')
                lines.append(f"- {cat.get('catalyst', '?')} ({prob}, {impact})")

        if self.bull_case_value and self.bear_case_value:
            lines.append("\n### Scenario Analysis")
            lines.append(f"- Bull Case: ${self.bull_case_value:.2f}")
            if self.base_case_value:
                lines.append(f"- Base Case: ${self.base_case_value:.2f}")
            lines.append(f"- Bear Case: ${self.bear_case_value:.2f}")

        return "\n".join(lines)

    def _format_valuation(self) -> str:
        """Format current valuation metrics."""
        parts = [f"${self.current_price:.2f}"]
        if self.current_pe:
            parts.append(f"P/E {self.current_pe:.1f}x")
        if self.current_ev_ebitda:
            parts.append(f"EV/EBITDA {self.current_ev_ebitda:.1f}x")
        return " | ".join(parts)


def compute_implied_expectations(
    company_context: Any,
    quant_metrics: dict[str, Any] | None = None,
) -> ImpliedExpectations:
    """Compute implied market expectations from current valuation.

    Args:
        company_context: CompanyContext with financial data.
        quant_metrics: Optional pre-computed quant metrics.

    Returns:
        ImpliedExpectations with "what's priced in" analysis.
    """
    # Extract relevant data
    profile = company_context.profile or {}
    ratios = company_context.key_metrics or {}
    price = profile.get("price", 0)
    market_cap = profile.get("mktCap", 0)

    # Get valuation multiples
    pe = ratios.get("peRatioTTM") or ratios.get("peRatio")
    ev_ebitda = ratios.get("enterpriseValueMultipleTTM")
    ev_revenue = ratios.get("evToSalesTTM") or ratios.get("priceToSalesRatioTTM")

    # Compute implied growth from PE (simplified Gordon growth model inversion)
    implied_growth = _compute_implied_growth(pe, profile.get("sector"))

    # Determine margin trajectory from recent trends
    margin_trajectory = _determine_margin_trajectory(company_context)

    # Compute terminal margin assumption
    terminal_margin = _estimate_terminal_margin(company_context)

    # Generate required assumptions
    required_assumptions = _generate_required_assumptions(
        pe, ev_ebitda, implied_growth, margin_trajectory
    )

    # Generate catalysts from sector and company data
    upside_catalysts = _identify_upside_catalysts(company_context)
    downside_catalysts = _identify_downside_catalysts(company_context)

    # Compare to historical/peers
    vs_historical = _compare_to_historical(pe, profile.get("sector"))
    vs_peers, premium_pct = _compare_to_peers(company_context)

    # Simple scenario analysis
    bull, base, bear = _compute_scenario_values(
        price, pe, implied_growth, margin_trajectory
    )

    return ImpliedExpectations(
        current_price=price,
        market_cap=market_cap,
        current_pe=pe,
        current_ev_ebitda=ev_ebitda,
        current_ev_revenue=ev_revenue,
        implied_revenue_growth_5yr=implied_growth,
        implied_eps_growth_5yr=implied_growth * 1.2 if implied_growth else None,  # EPS grows faster due to leverage
        implied_terminal_growth=0.03,  # Assume 3% terminal growth
        implied_margin_trajectory=margin_trajectory,
        implied_terminal_margin=terminal_margin,
        required_assumptions=required_assumptions,
        upside_catalysts=upside_catalysts,
        downside_catalysts=downside_catalysts,
        vs_historical_average=vs_historical,
        vs_sector_peers=vs_peers,
        premium_discount_pct=premium_pct,
        bull_case_value=bull,
        base_case_value=base,
        bear_case_value=bear,
    )


def _compute_implied_growth(pe: float | None, sector: str | None) -> float | None:
    """Compute implied growth from PE ratio.

    Uses a simplified reverse DCF approach:
    PE = (1 - g/r) / (r - g)

    Where r is cost of equity and g is growth.
    """
    if not pe or pe <= 0:
        return None

    # Sector-specific cost of equity estimates
    cost_of_equity = {
        "Technology": 0.10,
        "Healthcare": 0.09,
        "Consumer": 0.08,
        "Financials": 0.08,
        "Industrials": 0.08,
        "Energy": 0.10,
    }.get(sector or "", 0.09)

    terminal_growth = 0.03

    # Solve for implied 5-year growth
    # Simplified: Higher PE implies higher growth expectations
    # PE of 15 ~= market growth (~5%)
    # PE of 25 ~= 10% growth
    # PE of 40 ~= 15-20% growth

    if pe < 10:
        return 0.02  # Low/negative growth expected
    elif pe < 15:
        return 0.05
    elif pe < 20:
        return 0.08
    elif pe < 25:
        return 0.10
    elif pe < 35:
        return 0.15
    elif pe < 50:
        return 0.20
    else:
        return 0.25  # Very high growth expected


def _determine_margin_trajectory(company_context: Any) -> str:
    """Determine margin trajectory from historical data."""
    income_stmts = company_context.income_statement_quarterly or []

    if len(income_stmts) < 4:
        return "unknown"

    # Get operating margins for last 4 quarters
    margins = []
    for stmt in income_stmts[:8]:
        revenue = stmt.get("revenue", 0)
        op_income = stmt.get("operatingIncome", 0)
        if revenue > 0:
            margins.append(op_income / revenue)

    if len(margins) < 4:
        return "unknown"

    # Compare recent vs older margins
    recent_avg = sum(margins[:4]) / 4
    older_avg = sum(margins[4:8]) / max(len(margins[4:8]), 1) if len(margins) > 4 else recent_avg

    if recent_avg > older_avg * 1.05:
        return "expanding"
    elif recent_avg < older_avg * 0.95:
        return "contracting"
    else:
        return "stable"


def _estimate_terminal_margin(company_context: Any) -> float | None:
    """Estimate long-term terminal operating margin."""
    income_stmts = company_context.income_statement_quarterly or []

    if not income_stmts:
        return None

    # Get current margin
    stmt = income_stmts[0]
    revenue = stmt.get("revenue", 0)
    op_income = stmt.get("operatingIncome", 0)

    if revenue <= 0:
        return None

    current_margin = op_income / revenue

    # Terminal margin assumption based on sector
    profile = company_context.profile or {}
    sector = profile.get("sector", "")

    sector_terminal_margins = {
        "Technology": 0.25,  # Tech tends to high margins at scale
        "Healthcare": 0.20,
        "Consumer": 0.12,
        "Financials": 0.25,
        "Industrials": 0.12,
        "Energy": 0.15,
    }

    sector_terminal = sector_terminal_margins.get(sector, 0.15)

    # Blend current with sector terminal
    return (current_margin + sector_terminal) / 2


def _generate_required_assumptions(
    pe: float | None,
    ev_ebitda: float | None,
    implied_growth: float | None,
    margin_trajectory: str,
) -> list[str]:
    """Generate list of required assumptions for current valuation."""
    assumptions = []

    if implied_growth:
        years_str = "5+ years" if implied_growth > 0.15 else "3-5 years"
        assumptions.append(
            f"Revenue must grow {implied_growth:.0%}+ annually for {years_str}"
        )

    if pe and pe > 25:
        assumptions.append(
            "Earnings must grow faster than revenue (operating leverage)"
        )

    if margin_trajectory == "expanding":
        assumptions.append("Margins must continue expanding from current levels")
    elif margin_trajectory == "contracting":
        assumptions.append(
            "Current margin contraction must reverse or stock is expensive"
        )

    if ev_ebitda and ev_ebitda > 15:
        assumptions.append(
            "EBITDA must grow significantly to justify premium EV/EBITDA"
        )

    if pe and pe > 40:
        assumptions.append(
            "Exceptional execution with no major competitive threats"
        )

    return assumptions


def _identify_upside_catalysts(company_context: Any) -> list[dict[str, Any]]:
    """Identify potential upside catalysts."""
    catalysts = []

    profile = company_context.profile or {}
    sector = profile.get("sector", "")

    # Generic catalysts by sector
    if "Technology" in sector:
        catalysts.append({
            "catalyst": "AI/ML product adoption exceeds expectations",
            "probability": "medium",
            "potential_impact": "+20-30%",
        })
        catalysts.append({
            "catalyst": "Enterprise market share gains",
            "probability": "medium",
            "potential_impact": "+10-15%",
        })

    # Add margin expansion catalyst if margins have room
    income_stmts = company_context.income_statement_quarterly or []
    if income_stmts:
        stmt = income_stmts[0]
        revenue = stmt.get("revenue", 1)
        op_margin = stmt.get("operatingIncome", 0) / revenue if revenue else 0
        if op_margin < 0.20:
            catalysts.append({
                "catalyst": "Operating leverage drives margin expansion",
                "probability": "medium",
                "potential_impact": "+10-20%",
            })

    # M&A catalyst
    catalysts.append({
        "catalyst": "Strategic acquisition or partnership announcement",
        "probability": "low",
        "potential_impact": "+5-15%",
    })

    return catalysts[:5]


def _identify_downside_catalysts(company_context: Any) -> list[dict[str, Any]]:
    """Identify potential downside risks."""
    catalysts = []

    profile = company_context.profile or {}
    sector = profile.get("sector", "")

    # Macro risks
    catalysts.append({
        "catalyst": "Recession/macro slowdown impacts demand",
        "probability": "medium",
        "potential_impact": "-15-25%",
    })

    # Competition risk
    catalysts.append({
        "catalyst": "Increased competition erodes market share/pricing",
        "probability": "medium",
        "potential_impact": "-10-20%",
    })

    # Sector-specific risks
    if "Technology" in sector:
        catalysts.append({
            "catalyst": "Technology disruption/commoditization",
            "probability": "low",
            "potential_impact": "-20-40%",
        })

    # Execution risk
    catalysts.append({
        "catalyst": "Management execution miss or guidance cut",
        "probability": "medium",
        "potential_impact": "-10-15%",
    })

    # Valuation compression
    ratios = company_context.key_metrics or {}
    pe = ratios.get("peRatioTTM")
    if pe and pe > 30:
        catalysts.append({
            "catalyst": "Multiple compression as growth slows",
            "probability": "high",
            "potential_impact": "-15-30%",
        })

    return catalysts[:5]


def _compare_to_historical(pe: float | None, sector: str | None) -> str:
    """Compare current PE to historical averages."""
    if not pe:
        return "unknown"

    # Simplified historical averages by sector
    historical_pe = {
        "Technology": 25,
        "Healthcare": 18,
        "Consumer": 20,
        "Financials": 12,
        "Industrials": 18,
        "Energy": 12,
    }.get(sector or "", 18)

    if pe > historical_pe * 1.2:
        return "above"
    elif pe < historical_pe * 0.8:
        return "below"
    else:
        return "in-line"


def _compare_to_peers(company_context: Any) -> tuple[str, float | None]:
    """Compare valuation to sector peers."""
    ratios = company_context.key_metrics or {}
    pe = ratios.get("peRatioTTM")

    if not pe:
        return "unknown", None

    profile = company_context.profile or {}
    sector = profile.get("sector", "")

    # Simplified sector median PEs
    sector_median_pe = {
        "Technology": 28,
        "Healthcare": 20,
        "Consumer": 22,
        "Financials": 13,
        "Industrials": 19,
        "Energy": 13,
    }.get(sector, 20)

    premium_pct = (pe / sector_median_pe - 1) * 100

    if premium_pct > 20:
        return "premium", premium_pct
    elif premium_pct < -20:
        return "discount", premium_pct
    else:
        return "in-line", premium_pct


def _compute_scenario_values(
    current_price: float,
    pe: float | None,
    implied_growth: float | None,
    margin_trajectory: str,
) -> tuple[float | None, float | None, float | None]:
    """Compute bull/base/bear case values."""
    if not current_price or current_price <= 0:
        return None, None, None

    # Simple scenario analysis based on PE and growth
    if not pe or not implied_growth:
        # Use simple percentage moves
        return (
            current_price * 1.30,  # Bull: +30%
            current_price * 1.05,  # Base: +5%
            current_price * 0.75,  # Bear: -25%
        )

    # Bull case: Growth exceeds expectations, multiple expands
    bull_growth = implied_growth * 1.3
    bull_multiple = pe * 1.1
    bull = current_price * (1 + bull_growth) ** 2 * (bull_multiple / pe)

    # Base case: Growth meets expectations
    base = current_price * (1 + implied_growth) ** 2

    # Bear case: Growth disappoints, multiple contracts
    bear_growth = implied_growth * 0.5
    bear_multiple = pe * 0.8
    bear = current_price * (1 + bear_growth) ** 2 * (bear_multiple / pe)

    return bull, base, bear
