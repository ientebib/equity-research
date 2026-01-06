"""
Run manifest management for the equity research system.

Creates and updates manifest.json with run metadata.
Supports versioning for schema evolution and resume invalidation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from er.budget import BudgetTracker
from er.logging import get_logger
from er.types import Phase, utc_now

logger = get_logger(__name__)

# Manifest schema version - bump on breaking changes
MANIFEST_VERSION = "2.0"

# Minimum compatible version for resume
MIN_RESUME_VERSION = "2.0"


def _version_tuple(version: str) -> tuple[int, ...]:
    """Convert version string to tuple for comparison."""
    try:
        return tuple(int(x) for x in version.split("."))
    except (ValueError, AttributeError):
        return (0, 0)


def is_version_compatible(version: str, min_version: str = MIN_RESUME_VERSION) -> bool:
    """Check if a version is compatible for resume.

    Args:
        version: Version to check.
        min_version: Minimum required version.

    Returns:
        True if version is compatible.
    """
    return _version_tuple(version) >= _version_tuple(min_version)


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
        self.version = MANIFEST_VERSION
        self.started_at = utc_now()
        self.completed_at: datetime | None = None
        self.status = "running"
        self.phase = Phase.INIT
        self.budget_tracker: BudgetTracker | None = None
        self.artifacts: dict[str, str] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checkpoints: dict[str, str] = {}  # phase -> checkpoint hash
        self.input_hash: str = ""  # Hash of input parameters for cache invalidation

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

    def set_checkpoint(self, phase: Phase, data_hash: str) -> None:
        """Set a checkpoint for a phase.

        Args:
            phase: The phase to checkpoint.
            data_hash: Hash of phase output data.
        """
        self.checkpoints[phase.value] = data_hash
        self.save()

    def get_checkpoint(self, phase: Phase) -> str | None:
        """Get checkpoint hash for a phase.

        Args:
            phase: The phase to get checkpoint for.

        Returns:
            Checkpoint hash or None.
        """
        return self.checkpoints.get(phase.value)

    def set_input_hash(self, params: dict[str, Any]) -> None:
        """Set input hash from run parameters.

        Args:
            params: Run parameters to hash.
        """
        content = orjson.dumps(params, option=orjson.OPT_SORT_KEYS)
        self.input_hash = hashlib.sha256(content).hexdigest()[:16]
        self.save()

    def can_resume(self) -> bool:
        """Check if this manifest can be resumed.

        Returns:
            True if resumable.
        """
        # Check version compatibility
        if not is_version_compatible(self.version):
            logger.warning(
                "Manifest version incompatible for resume",
                manifest_version=self.version,
                min_version=MIN_RESUME_VERSION,
            )
            return False

        # Can't resume completed or failed runs
        if self.status in ("completed", "failed"):
            return False

        # Must have at least started
        if self.phase == Phase.INIT:
            return False

        return True

    def invalidate_from_phase(self, phase: Phase) -> None:
        """Invalidate checkpoints from a phase onwards.

        Used when inputs change and we need to re-run from a point.

        Args:
            phase: Phase to invalidate from (inclusive).
        """
        phase_order = [
            Phase.INIT,
            Phase.FETCH_DATA,
            Phase.DISCOVERY,
            Phase.DECOMPOSE,
            Phase.VERTICALS,
            Phase.FACT_CHECK,
            Phase.RESEARCH,
            Phase.SYNTHESIZE,
            Phase.DELIBERATE,
            Phase.OUTPUTS,
            Phase.COMPLETE,
        ]

        try:
            start_idx = phase_order.index(phase)
        except ValueError:
            return

        for p in phase_order[start_idx:]:
            if p.value in self.checkpoints:
                del self.checkpoints[p.value]

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
            "version": self.version,
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
            "checkpoints": self.checkpoints,
            "input_hash": self.input_hash,
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
            manifest.version = data.get("version", "1.0")
            manifest.started_at = datetime.fromisoformat(data["started_at"])
            if data.get("completed_at"):
                manifest.completed_at = datetime.fromisoformat(data["completed_at"])
            manifest.status = data.get("status", "unknown")
            manifest.phase = Phase(data.get("phase", "init"))
            manifest.artifacts = data.get("artifacts", {})
            manifest.errors = data.get("errors", [])
            manifest.warnings = data.get("warnings", [])
            manifest.checkpoints = data.get("checkpoints", {})
            manifest.input_hash = data.get("input_hash", "")

            return manifest
        except Exception as e:
            logger.warning("Failed to load manifest", error=str(e))
            return None
