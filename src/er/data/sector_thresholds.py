"""
Sector-specific thresholds for financial ratio analysis.

Different sectors have vastly different "normal" ranges for financial metrics.
A DSO of 90 days might be alarming for a retailer but normal for an enterprise
software company. This module provides sector-aware thresholds.
"""

from __future__ import annotations

from typing import Any


# Threshold configuration per sector/business model combination
# Format: {sector: {ratio_name: {warning: float, critical: float, skip: bool}}}
#
# "warning" - Yellow flag threshold
# "critical" - Red flag threshold
# "skip" - True if this ratio doesn't apply to the sector
# "special_ratios" - Sector-specific ratios to check instead

SECTOR_THRESHOLDS: dict[str, dict[str, Any]] = {
    # ==================== Technology ====================
    "Technology/SaaS": {
        "dso": {"warning": 90, "critical": 120},  # SaaS has longer enterprise sales cycles
        "dio": {"skip": True},  # No physical inventory
        "roic": {"warning": 0.05, "critical": 0},  # Growth > profitability in early stage
        "sbc_to_revenue": {"warning": 0.20, "critical": 0.30},  # Higher SBC is normal
        "gross_margin": {"warning": 0.60, "critical": 0.50},  # Should be high for SaaS
        "net_debt_to_ebitda": {"warning": 3, "critical": 5},
        "current_ratio": {"warning": 1.0, "critical": 0.8},  # Can run leaner
        "special_metrics": ["arr_growth", "net_retention", "rule_of_40"],
    },
    "Technology/Hardware": {
        "dso": {"warning": 60, "critical": 90},
        "dio": {"warning": 60, "critical": 90},  # Inventory matters
        "roic": {"warning": 0.10, "critical": 0.05},
        "sbc_to_revenue": {"warning": 0.10, "critical": 0.20},
        "gross_margin": {"warning": 0.30, "critical": 0.20},
        "net_debt_to_ebitda": {"warning": 3, "critical": 4},
    },
    "Technology/Semiconductor": {
        "dso": {"warning": 50, "critical": 75},
        "dio": {"warning": 90, "critical": 120},  # Long production cycles
        "roic": {"warning": 0.12, "critical": 0.08},  # Capital intensive
        "gross_margin": {"warning": 0.45, "critical": 0.35},
        "capex_to_revenue": {"warning": 0.15, "critical": 0.25},  # High capex is normal
    },

    # ==================== Financials ====================
    "Financials/Bank": {
        # Traditional ratios don't apply
        "skip_ratios": ["dso", "dio", "gross_margin", "roic", "current_ratio"],
        "special_ratios": {
            "net_interest_margin": {"warning": 0.02, "critical": 0.015},
            "efficiency_ratio": {"warning": 0.65, "critical": 0.75},  # Lower is better
            "tier1_capital_ratio": {"warning": 0.10, "critical": 0.08},
            "npl_ratio": {"warning": 0.02, "critical": 0.04},  # Non-performing loans
        },
        "debt_to_equity": {"skip": True},  # Banks are naturally leveraged
    },
    "Financials/Insurance": {
        "skip_ratios": ["dso", "dio", "gross_margin"],
        "special_ratios": {
            "combined_ratio": {"warning": 1.0, "critical": 1.05},  # Below 100% is profitable
            "loss_ratio": {"warning": 0.70, "critical": 0.80},
        },
        "roic": {"warning": 0.08, "critical": 0.05},
    },
    "Financials/Asset_Management": {
        "skip_ratios": ["dso", "dio"],
        "special_ratios": {
            "aum_growth": {"warning": 0.05, "critical": 0},
            "fee_rate": {"warning": 0.003, "critical": 0.002},  # 30 bps
        },
        "operating_margin": {"warning": 0.25, "critical": 0.15},
    },
    "Financials/REIT": {
        "skip_ratios": ["dso", "dio", "roic"],
        "special_ratios": {
            "ffo_per_share_growth": {"warning": 0.02, "critical": 0},
            "occupancy_rate": {"warning": 0.90, "critical": 0.85},
            "debt_to_assets": {"warning": 0.50, "critical": 0.60},
        },
        "net_debt_to_ebitda": {"warning": 6, "critical": 8},  # REITs are levered
    },

    # ==================== Healthcare ====================
    "Healthcare/Pharma": {
        "dso": {"warning": 70, "critical": 100},
        "dio": {"warning": 120, "critical": 180},  # Long production cycles
        "roic": {"warning": 0.08, "critical": 0.05},
        "rd_to_revenue": {"warning": 0.10, "critical": 0.05},  # R&D should be high
        "gross_margin": {"warning": 0.60, "critical": 0.50},
    },
    "Healthcare/Biotech": {
        "dso": {"warning": 90, "critical": 120},
        "roic": {"skip": True},  # Many pre-revenue
        "gross_margin": {"warning": 0.50, "critical": 0.40},
        "net_debt_to_ebitda": {"skip": True},  # EBITDA often negative
        "special_metrics": ["cash_runway_months", "pipeline_value"],
    },
    "Healthcare/Services": {
        "dso": {"warning": 50, "critical": 75},
        "roic": {"warning": 0.10, "critical": 0.06},
        "gross_margin": {"warning": 0.25, "critical": 0.15},
    },

    # ==================== Consumer ====================
    "Consumer/Retail": {
        "dso": {"warning": 15, "critical": 30},  # Should be very low
        "dio": {"warning": 60, "critical": 90},
        "roic": {"warning": 0.12, "critical": 0.08},
        "gross_margin": {"warning": 0.25, "critical": 0.18},
        "current_ratio": {"warning": 1.2, "critical": 1.0},
    },
    "Consumer/E-commerce": {
        "dso": {"warning": 20, "critical": 40},
        "dio": {"warning": 45, "critical": 70},  # Faster turns expected
        "roic": {"warning": 0.08, "critical": 0.04},  # Growth focus
        "gross_margin": {"warning": 0.20, "critical": 0.15},
        "special_metrics": ["gmv_growth", "take_rate"],
    },
    "Consumer/CPG": {
        "dso": {"warning": 40, "critical": 60},
        "dio": {"warning": 50, "critical": 80},
        "roic": {"warning": 0.15, "critical": 0.10},  # Should be high
        "gross_margin": {"warning": 0.35, "critical": 0.25},
    },
    "Consumer/Restaurant": {
        "dso": {"warning": 10, "critical": 20},  # Mostly cash sales
        "dio": {"warning": 15, "critical": 25},  # Food spoils
        "roic": {"warning": 0.12, "critical": 0.08},
        "gross_margin": {"warning": 0.60, "critical": 0.50},  # Food cost
    },

    # ==================== Industrials ====================
    "Industrials/Manufacturing": {
        "dso": {"warning": 50, "critical": 75},
        "dio": {"warning": 70, "critical": 100},
        "roic": {"warning": 0.10, "critical": 0.07},
        "gross_margin": {"warning": 0.25, "critical": 0.18},
        "net_debt_to_ebitda": {"warning": 3, "critical": 4},
    },
    "Industrials/Aerospace": {
        "dso": {"warning": 60, "critical": 90},
        "dio": {"warning": 150, "critical": 200},  # Long production cycles
        "roic": {"warning": 0.12, "critical": 0.08},
        "gross_margin": {"warning": 0.15, "critical": 0.10},  # Cost-plus contracts
    },
    "Industrials/Construction": {
        "dso": {"warning": 70, "critical": 100},  # Progress billing
        "roic": {"warning": 0.10, "critical": 0.06},
        "gross_margin": {"warning": 0.12, "critical": 0.08},
        "net_debt_to_ebitda": {"warning": 3, "critical": 4},
    },

    # ==================== Energy ====================
    "Energy/Oil_Gas": {
        "dso": {"warning": 45, "critical": 70},
        "roic": {"warning": 0.08, "critical": 0.04},  # Cyclical
        "net_debt_to_ebitda": {"warning": 2.5, "critical": 3.5},
        "special_metrics": ["reserve_replacement", "finding_costs"],
    },
    "Energy/Utilities": {
        "skip_ratios": ["dso", "dio"],
        "roic": {"warning": 0.06, "critical": 0.04},  # Regulated returns
        "net_debt_to_ebitda": {"warning": 5, "critical": 6},  # Utilities are levered
        "interest_coverage": {"warning": 2.5, "critical": 2.0},
    },
    "Energy/Renewables": {
        "roic": {"warning": 0.06, "critical": 0.03},  # Long payback
        "net_debt_to_ebitda": {"warning": 5, "critical": 7},  # Project finance
    },

    # ==================== Materials ====================
    "Materials/Mining": {
        "dso": {"warning": 45, "critical": 70},
        "dio": {"warning": 60, "critical": 90},
        "roic": {"warning": 0.08, "critical": 0.04},  # Cyclical
        "net_debt_to_ebitda": {"warning": 2, "critical": 3},
    },
    "Materials/Chemicals": {
        "dso": {"warning": 50, "critical": 75},
        "dio": {"warning": 60, "critical": 90},
        "roic": {"warning": 0.10, "critical": 0.06},
        "gross_margin": {"warning": 0.25, "critical": 0.18},
    },

    # ==================== Telecom ====================
    "Telecom/Wireless": {
        "dso": {"warning": 40, "critical": 60},
        "roic": {"warning": 0.06, "critical": 0.04},  # Capital intensive
        "net_debt_to_ebitda": {"warning": 3, "critical": 4},
        "capex_to_revenue": {"warning": 0.15, "critical": 0.20},
    },

    # ==================== Default ====================
    "Default": {
        "dso": {"warning": 60, "critical": 90},
        "dio": {"warning": 60, "critical": 90},
        "roic": {"warning": 0.08, "critical": 0.05},
        "sbc_to_revenue": {"warning": 0.15, "critical": 0.25},
        "gross_margin": {"warning": 0.30, "critical": 0.20},
        "operating_margin": {"warning": 0.08, "critical": 0.03},
        "net_debt_to_ebitda": {"warning": 4, "critical": 5},
        "interest_coverage": {"warning": 3, "critical": 2},
        "current_ratio": {"warning": 1.2, "critical": 1.0},
        "debt_to_equity": {"warning": 1.5, "critical": 2.5},
    },
}


def get_thresholds(sector_classification: str) -> dict[str, Any]:
    """Get thresholds for a sector classification.

    Args:
        sector_classification: Sector/business model string (e.g., "Technology/SaaS").

    Returns:
        Threshold configuration for the sector.
    """
    # Try exact match first
    if sector_classification in SECTOR_THRESHOLDS:
        return SECTOR_THRESHOLDS[sector_classification]

    # Try just the sector part
    if "/" in sector_classification:
        sector = sector_classification.split("/")[0]
        for key in SECTOR_THRESHOLDS:
            if key.startswith(sector + "/"):
                return SECTOR_THRESHOLDS[key]

    # Fall back to default
    return SECTOR_THRESHOLDS["Default"]


def evaluate_ratio(
    ratio_name: str,
    value: float | None,
    sector_classification: str,
) -> dict[str, Any]:
    """Evaluate a ratio against sector-specific thresholds.

    Args:
        ratio_name: Name of the ratio (e.g., "dso", "roic").
        value: Current value of the ratio.
        sector_classification: Sector/business model classification.

    Returns:
        Dict with evaluation result: status, message, thresholds used.
    """
    if value is None:
        return {
            "status": "unavailable",
            "message": f"{ratio_name} data not available",
            "value": None,
        }

    thresholds = get_thresholds(sector_classification)

    # Check if this ratio should be skipped for this sector
    skip_ratios = thresholds.get("skip_ratios", [])
    if ratio_name in skip_ratios:
        return {
            "status": "not_applicable",
            "message": f"{ratio_name} not applicable for {sector_classification}",
            "value": value,
        }

    # Get ratio-specific thresholds
    ratio_config = thresholds.get(ratio_name, SECTOR_THRESHOLDS["Default"].get(ratio_name, {}))

    if not ratio_config or ratio_config.get("skip"):
        return {
            "status": "not_applicable",
            "message": f"{ratio_name} not applicable for {sector_classification}",
            "value": value,
        }

    warning_threshold = ratio_config.get("warning")
    critical_threshold = ratio_config.get("critical")

    # Determine if higher or lower is worse
    # For most ratios, exceeding threshold is bad (DSO, debt ratios)
    # For margins and returns, falling below is bad
    lower_is_worse = ratio_name in [
        "roic", "gross_margin", "operating_margin", "net_margin",
        "interest_coverage", "current_ratio", "income_quality",
        "fcf_conversion", "incremental_roic",
    ]

    if lower_is_worse:
        # Critical if below critical threshold
        if critical_threshold is not None and value < critical_threshold:
            return {
                "status": "critical",
                "message": f"{ratio_name} of {value:.2f} is below critical threshold of {critical_threshold}",
                "value": value,
                "threshold": critical_threshold,
            }
        if warning_threshold is not None and value < warning_threshold:
            return {
                "status": "warning",
                "message": f"{ratio_name} of {value:.2f} is below warning threshold of {warning_threshold}",
                "value": value,
                "threshold": warning_threshold,
            }
    else:
        # Critical if above critical threshold
        if critical_threshold is not None and value > critical_threshold:
            return {
                "status": "critical",
                "message": f"{ratio_name} of {value:.2f} exceeds critical threshold of {critical_threshold}",
                "value": value,
                "threshold": critical_threshold,
            }
        if warning_threshold is not None and value > warning_threshold:
            return {
                "status": "warning",
                "message": f"{ratio_name} of {value:.2f} exceeds warning threshold of {warning_threshold}",
                "value": value,
                "threshold": warning_threshold,
            }

    return {
        "status": "ok",
        "message": f"{ratio_name} of {value:.2f} is within normal range for {sector_classification}",
        "value": value,
    }


def compute_sector_aware_red_flags(
    ratios: dict[str, Any],
    sector_classification: str,
) -> list[str]:
    """Compute red flags using sector-specific thresholds.

    Args:
        ratios: Dict of ratio name -> value.
        sector_classification: Sector/business model classification.

    Returns:
        List of red flag messages.
    """
    flags = []

    # Map common ratio names to our threshold names
    ratio_mapping = {
        "daysOfSalesOutstanding": "dso",
        "daysOfInventoryOutstanding": "dio",
        "returnOnInvestedCapital": "roic",
        "stockBasedCompensationToRevenue": "sbc_to_revenue",
        "grossProfitMargin": "gross_margin",
        "operatingProfitMargin": "operating_margin",
        "netProfitMargin": "net_margin",
        "netDebtToEBITDA": "net_debt_to_ebitda",
        "interestCoverageRatio": "interest_coverage",
        "currentRatio": "current_ratio",
        "debtToEquityRatio": "debt_to_equity",
        "incomeQuality": "income_quality",
    }

    for api_name, threshold_name in ratio_mapping.items():
        value = ratios.get(api_name)
        if value is None:
            continue

        result = evaluate_ratio(threshold_name, value, sector_classification)

        if result["status"] == "critical":
            flags.append(f"CRITICAL ({sector_classification}): {result['message']}")
        elif result["status"] == "warning":
            flags.append(f"WARNING ({sector_classification}): {result['message']}")

    return flags
