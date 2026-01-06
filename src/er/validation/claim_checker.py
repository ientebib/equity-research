"""
Claim Validation Layer.

Validates numerical claims in synthesis reports against FMP data.
Flags inconsistencies for revision rather than silently passing errors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from er.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ClaimValidationResult:
    """Result of validating a single claim."""

    claim_text: str
    claim_type: str  # "revenue", "margin", "growth", "ratio", "other"
    claimed_value: float | str | None
    actual_value: float | str | None
    is_valid: bool
    error_message: str | None = None
    tolerance_pct: float = 5.0  # Percent tolerance for numerical comparisons


@dataclass
class ClaimValidationReport:
    """Complete validation report for a synthesis."""

    total_claims_checked: int
    valid_claims: int
    invalid_claims: int
    validation_results: list[ClaimValidationResult] = field(default_factory=list)

    @property
    def accuracy_rate(self) -> float:
        """Percentage of claims that validated correctly."""
        if self.total_claims_checked == 0:
            return 1.0
        return self.valid_claims / self.total_claims_checked

    def get_invalid_claims(self) -> list[ClaimValidationResult]:
        """Get list of claims that failed validation."""
        return [r for r in self.validation_results if not r.is_valid]

    def to_revision_instructions(self) -> str:
        """Generate revision instructions for invalid claims."""
        invalid = self.get_invalid_claims()
        if not invalid:
            return ""

        lines = ["## Numerical Claims to Correct", ""]
        for result in invalid:
            lines.append(f"- **Claim:** \"{result.claim_text[:100]}...\"")
            lines.append(f"  - **Issue:** {result.error_message}")
            if result.actual_value is not None:
                lines.append(f"  - **Correct Value:** {result.actual_value}")
            lines.append("")

        return "\n".join(lines)


class ClaimChecker:
    """Validates numerical claims against company financial data."""

    def __init__(self, company_context: Any) -> None:
        """Initialize with company context.

        Args:
            company_context: CompanyContext with FMP financial data.
        """
        self.company_context = company_context
        self._build_reference_data()

    def _build_reference_data(self) -> None:
        """Build reference data for validation."""
        self.reference_data: dict[str, Any] = {}

        # Extract from profile
        profile = self.company_context.profile or {}
        self.reference_data["market_cap"] = profile.get("mktCap")
        self.reference_data["price"] = profile.get("price")
        self.reference_data["sector"] = profile.get("sector")
        self.reference_data["industry"] = profile.get("industry")

        # Extract from latest income statement
        income_stmts = self.company_context.income_statement_quarterly or []
        if income_stmts:
            latest = income_stmts[0]
            self.reference_data["revenue"] = latest.get("revenue")
            self.reference_data["gross_profit"] = latest.get("grossProfit")
            self.reference_data["operating_income"] = latest.get("operatingIncome")
            self.reference_data["net_income"] = latest.get("netIncome")
            self.reference_data["eps"] = latest.get("eps")

            # Compute margins
            revenue = latest.get("revenue", 0)
            if revenue > 0:
                self.reference_data["gross_margin"] = latest.get("grossProfit", 0) / revenue
                self.reference_data["operating_margin"] = latest.get("operatingIncome", 0) / revenue
                self.reference_data["net_margin"] = latest.get("netIncome", 0) / revenue

        # Extract from latest balance sheet
        balance_sheets = self.company_context.balance_sheet_quarterly or []
        if balance_sheets:
            latest = balance_sheets[0]
            self.reference_data["total_assets"] = latest.get("totalAssets")
            self.reference_data["total_debt"] = latest.get("totalDebt")
            self.reference_data["cash"] = latest.get("cashAndCashEquivalents")
            self.reference_data["total_equity"] = latest.get("totalStockholdersEquity")

        # Extract from key metrics/ratios
        ratios = self.company_context.key_metrics or {}
        self.reference_data["pe_ratio"] = ratios.get("peRatioTTM") or ratios.get("peRatio")
        self.reference_data["ev_ebitda"] = ratios.get("enterpriseValueMultipleTTM")
        self.reference_data["roic"] = ratios.get("roicTTM")
        self.reference_data["roe"] = ratios.get("roeTTM")

        logger.debug(
            "Built reference data for validation",
            keys=list(self.reference_data.keys()),
        )

    def check_numerical_claim(
        self,
        claim: str,
        tolerance: float = 0.05,
    ) -> ClaimValidationResult:
        """Check if a numerical claim matches FMP data.

        Args:
            claim: Text of the claim to validate.
            tolerance: Tolerance for numerical comparison (0.05 = 5%).

        Returns:
            ClaimValidationResult with validation status.
        """
        claim_lower = claim.lower()

        # Try to identify what kind of claim this is and extract the value
        claim_type, claimed_value = self._parse_claim(claim)

        if claimed_value is None:
            return ClaimValidationResult(
                claim_text=claim,
                claim_type="unknown",
                claimed_value=None,
                actual_value=None,
                is_valid=True,  # Can't validate, assume ok
                error_message=None,
            )

        # Look up actual value
        actual_value = self._get_actual_value(claim_type, claim_lower)

        if actual_value is None:
            return ClaimValidationResult(
                claim_text=claim,
                claim_type=claim_type,
                claimed_value=claimed_value,
                actual_value=None,
                is_valid=True,  # No reference data, assume ok
                error_message=None,
            )

        # Compare values
        is_valid, error_msg = self._compare_values(
            claimed_value, actual_value, tolerance, claim_type
        )

        return ClaimValidationResult(
            claim_text=claim,
            claim_type=claim_type,
            claimed_value=claimed_value,
            actual_value=actual_value,
            is_valid=is_valid,
            error_message=error_msg,
            tolerance_pct=tolerance * 100,
        )

    def _parse_claim(self, claim: str) -> tuple[str, float | None]:
        """Parse a claim to extract its type and numerical value.

        Returns:
            Tuple of (claim_type, extracted_value).
        """
        claim_lower = claim.lower()

        # Revenue patterns
        if "revenue" in claim_lower:
            value = self._extract_money_value(claim)
            return "revenue", value

        # Margin patterns
        if "margin" in claim_lower:
            value = self._extract_percent_value(claim)
            if "gross" in claim_lower:
                return "gross_margin", value
            elif "operating" in claim_lower:
                return "operating_margin", value
            elif "net" in claim_lower:
                return "net_margin", value
            return "margin", value

        # Growth patterns
        if "growth" in claim_lower or "grew" in claim_lower or "increase" in claim_lower:
            value = self._extract_percent_value(claim)
            return "growth", value

        # Ratio patterns
        if "p/e" in claim_lower or "pe ratio" in claim_lower:
            value = self._extract_ratio_value(claim)
            return "pe_ratio", value

        if "ev/ebitda" in claim_lower:
            value = self._extract_ratio_value(claim)
            return "ev_ebitda", value

        # Market cap
        if "market cap" in claim_lower:
            value = self._extract_money_value(claim)
            return "market_cap", value

        # EPS
        if "eps" in claim_lower or "earnings per share" in claim_lower:
            value = self._extract_money_value(claim)
            return "eps", value

        return "other", None

    def _extract_money_value(self, text: str) -> float | None:
        """Extract a monetary value from text."""
        # Patterns: $1.5B, $1.5 billion, $1,500M, $1500 million
        patterns = [
            r'\$([0-9,.]+)\s*([BMT])\b',  # $1.5B
            r'\$([0-9,.]+)\s*(billion|million|trillion)',  # $1.5 billion
        ]

        multipliers = {
            'B': 1e9, 'billion': 1e9,
            'M': 1e6, 'million': 1e6,
            'T': 1e12, 'trillion': 1e12,
        }

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value_str = match.group(1).replace(',', '')
                suffix = match.group(2)
                try:
                    value = float(value_str)
                    multiplier = multipliers.get(suffix, multipliers.get(suffix.lower(), 1))
                    return value * multiplier
                except ValueError:
                    continue

        # Try simple dollar amount
        match = re.search(r'\$([0-9,.]+)', text)
        if match:
            try:
                return float(match.group(1).replace(',', ''))
            except ValueError:
                pass

        return None

    def _extract_percent_value(self, text: str) -> float | None:
        """Extract a percentage value from text."""
        # Patterns: 25%, 25.5%, 25 percent
        patterns = [
            r'([0-9.]+)\s*%',
            r'([0-9.]+)\s*percent',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1)) / 100
                except ValueError:
                    continue

        return None

    def _extract_ratio_value(self, text: str) -> float | None:
        """Extract a ratio value from text."""
        # Patterns: 25x, 25.5x
        match = re.search(r'([0-9.]+)\s*x', text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        # Try plain number near "times"
        match = re.search(r'([0-9.]+)\s*times', text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    def _get_actual_value(self, claim_type: str, claim_text: str) -> float | None:
        """Get the actual value for comparison based on claim type."""
        # Direct mapping for most types
        direct_mappings = {
            "revenue": "revenue",
            "gross_margin": "gross_margin",
            "operating_margin": "operating_margin",
            "net_margin": "net_margin",
            "pe_ratio": "pe_ratio",
            "ev_ebitda": "ev_ebitda",
            "market_cap": "market_cap",
            "eps": "eps",
        }

        if claim_type in direct_mappings:
            return self.reference_data.get(direct_mappings[claim_type])

        return None

    def _compare_values(
        self,
        claimed: float | None,
        actual: float | None,
        tolerance: float,
        claim_type: str,
    ) -> tuple[bool, str | None]:
        """Compare claimed value to actual value.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if claimed is None or actual is None:
            return True, None

        # For ratios and margins, use absolute tolerance
        if claim_type in ("gross_margin", "operating_margin", "net_margin"):
            # Margins are decimals (0.25 = 25%), tolerance is percentage points
            diff = abs(claimed - actual)
            if diff > 0.05:  # More than 5 percentage points off
                return False, (
                    f"Margin off by {diff*100:.1f} percentage points "
                    f"(claimed {claimed*100:.1f}%, actual {actual*100:.1f}%)"
                )
            return True, None

        # For other values, use percentage tolerance
        if actual != 0:
            pct_diff = abs(claimed - actual) / abs(actual)
            if pct_diff > tolerance:
                return False, (
                    f"Value off by {pct_diff*100:.1f}% "
                    f"(claimed {self._format_value(claimed, claim_type)}, "
                    f"actual {self._format_value(actual, claim_type)})"
                )

        return True, None

    def _format_value(self, value: float, claim_type: str) -> str:
        """Format a value for display."""
        if claim_type in ("gross_margin", "operating_margin", "net_margin", "growth"):
            return f"{value*100:.1f}%"
        elif claim_type in ("revenue", "market_cap"):
            if value >= 1e12:
                return f"${value/1e12:.1f}T"
            elif value >= 1e9:
                return f"${value/1e9:.1f}B"
            elif value >= 1e6:
                return f"${value/1e6:.1f}M"
            else:
                return f"${value:.2f}"
        elif claim_type in ("pe_ratio", "ev_ebitda"):
            return f"{value:.1f}x"
        elif claim_type == "eps":
            return f"${value:.2f}"
        else:
            return str(value)


def validate_synthesis_claims(
    synthesis_text: str,
    company_context: Any,
    tolerance: float = 0.05,
) -> ClaimValidationReport:
    """Validate all numerical claims in a synthesis report.

    Args:
        synthesis_text: Full text of the synthesis report.
        company_context: CompanyContext with FMP financial data.
        tolerance: Tolerance for numerical comparison.

    Returns:
        ClaimValidationReport with all validation results.
    """
    checker = ClaimChecker(company_context)

    # Split into sentences and check each
    sentences = re.split(r'[.!?]', synthesis_text)

    results: list[ClaimValidationResult] = []
    valid_count = 0
    invalid_count = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Only check sentences that contain numbers
        if not re.search(r'\d', sentence):
            continue

        # Check the sentence as a claim
        result = checker.check_numerical_claim(sentence, tolerance)

        # Only include results where we actually validated something
        if result.claimed_value is not None:
            results.append(result)
            if result.is_valid:
                valid_count += 1
            else:
                invalid_count += 1

    logger.info(
        "Claim validation complete",
        total_checked=len(results),
        valid=valid_count,
        invalid=invalid_count,
    )

    return ClaimValidationReport(
        total_claims_checked=len(results),
        valid_claims=valid_count,
        invalid_claims=invalid_count,
        validation_results=results,
    )
