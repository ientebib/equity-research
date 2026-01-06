"""Analysis modules for equity research.

Contains:
- expectations.py: Implied expectations and "what's priced in" analysis
"""

from er.analysis.expectations import (
    ImpliedExpectations,
    compute_implied_expectations,
)

__all__ = [
    "ImpliedExpectations",
    "compute_implied_expectations",
]
