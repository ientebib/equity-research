"""
Base classes for output generation.

This module will implement:
- OutputGenerator: Abstract base class for output generators
  - generate() method
  - Output path management

- ReportGenerator: Markdown report generator
  - Jinja2 templates for consistent formatting
  - Evidence citation linking
  - Executive summary, analysis sections, risks, verdict

- ExcelGenerator: Financial model generator
  - openpyxl for Excel creation
  - Sheets: Summary, Financials, Valuation, Scenarios
  - Charts and formatting

- EvidenceAppendix: Evidence citation generator
  - Full evidence records with links
  - Organized by source tier
  - Content snippets

Features:
- Template-based generation
- Consistent styling
- PDF export (via LibreOffice if available)
- Incremental updates
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from er.types import RunState


class OutputGenerator(ABC):
    """Abstract base class for output generators."""

    @property
    @abstractmethod
    def output_name(self) -> str:
        """Name of this output type."""
        ...

    @abstractmethod
    async def generate(self, run_state: RunState, output_dir: Path) -> Path:
        """Generate the output and return the path to the generated file."""
        ...
