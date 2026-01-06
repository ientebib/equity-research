"""Validation modules for equity research.

Contains:
- claim_checker.py: Validates numerical claims against FMP data
"""

from er.validation.claim_checker import (
    ClaimChecker,
    ClaimValidationResult,
    validate_synthesis_claims,
)

__all__ = [
    "ClaimChecker",
    "ClaimValidationResult",
    "validate_synthesis_claims",
]
