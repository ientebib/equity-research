"""
Run manifest management for the equity research system.

Creates and updates manifest.json with run metadata.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from er.budget import BudgetTracker
from er.logging import get_logger
from er.types import Phase, utc_now

logger = get_logger(__name__)


class RunManifest:
    """Manages the run manifest file.

    The manifest tracks:
    - Run metadata (run_id, ticker, timestamps)
    - Status (running, completed, failed)
    - Current phase
    - Budget info
    - Artifacts (paths to outputs)
    - Errors
    """

    def __init__(self, output_dir: Path, run_id: str, ticker: str) -> None:
        """Initialize manifest.

        Args:
            output_dir: Directory for run output.
            run_id: The run identifier.
            ticker: Stock ticker symbol.
        """
        self.output_dir = output_dir
        self.manifest_path = output_dir / "manifest.json"

        self.run_id = run_id
        self.ticker = ticker
        self.started_at = utc_now()
        self.completed_at: datetime | None = None
        self.status = "running"
        self.phase = Phase.INIT
        self.budget_tracker: BudgetTracker | None = None
        self.artifacts: dict[str, str] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def set_budget_tracker(self, tracker: BudgetTracker) -> None:
        """Set the budget tracker reference.

        Args:
            tracker: BudgetTracker instance.
        """
        self.budget_tracker = tracker

    def update_phase(self, phase: Phase) -> None:
        """Update current phase.

        Args:
            phase: The new phase.
        """
        self.phase = phase
        logger.info("Phase transition", phase=phase.value)
        self.save()

    def add_artifact(self, name: str, path: str) -> None:
        """Add an artifact path.

        Args:
            name: Artifact name (e.g., "report", "excel_model").
            path: Path to the artifact.
        """
        self.artifacts[name] = path
        self.save()

    def add_error(self, error: str) -> None:
        """Add an error summary.

        Args:
            error: Error message.
        """
        self.errors.append(error)
        logger.error("Run error", error=error)
        self.save()

    def add_warning(self, warning: str) -> None:
        """Add a warning.

        Args:
            warning: Warning message.
        """
        self.warnings.append(warning)
        logger.warning("Run warning", warning=warning)
        self.save()

    def complete(self, success: bool = True) -> None:
        """Mark the run as complete.

        Args:
            success: Whether the run succeeded.
        """
        self.completed_at = utc_now()
        self.status = "completed" if success else "failed"
        self.phase = Phase.COMPLETE if success else Phase.FAILED
        self.save()

    def fail(self, error: str) -> None:
        """Mark the run as failed.

        Args:
            error: Error message.
        """
        self.add_error(error)
        self.complete(success=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict.

        Returns:
            Dict representation.
        """
        budget_info: dict[str, Any] | None = None
        if self.budget_tracker:
            budget_info = {
                "limit": self.budget_tracker.budget_limit,
                "used": self.budget_tracker.total_cost_usd,
                "remaining": self.budget_tracker.get_remaining(),
            }

        return {
            "run_id": self.run_id,
            "ticker": self.ticker,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "phase": self.phase.value,
            "budget": budget_info,
            "artifacts": self.artifacts,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def save(self) -> None:
        """Save manifest to file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        with open(self.manifest_path, "wb") as f:
            f.write(orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2))

    @classmethod
    def load(cls, output_dir: Path) -> RunManifest | None:
        """Load manifest from file.

        Args:
            output_dir: Directory containing manifest.

        Returns:
            RunManifest or None if not found.
        """
        manifest_path = output_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, "rb") as f:
                data = orjson.loads(f.read())

            manifest = cls(
                output_dir=output_dir,
                run_id=data["run_id"],
                ticker=data["ticker"],
            )
            manifest.started_at = datetime.fromisoformat(data["started_at"])
            if data.get("completed_at"):
                manifest.completed_at = datetime.fromisoformat(data["completed_at"])
            manifest.status = data.get("status", "unknown")
            manifest.phase = Phase(data.get("phase", "init"))
            manifest.artifacts = data.get("artifacts", {})
            manifest.errors = data.get("errors", [])
            manifest.warnings = data.get("warnings", [])

            return manifest
        except Exception as e:
            logger.warning("Failed to load manifest", error=str(e))
            return None
