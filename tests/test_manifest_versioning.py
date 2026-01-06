"""Tests for manifest versioning and resume invalidation."""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from er.manifest import (
    RunManifest,
    MANIFEST_VERSION,
    MIN_RESUME_VERSION,
    is_version_compatible,
    _version_tuple,
)
from er.types import Phase


class TestVersionHelpers:
    """Tests for version utility functions."""

    def test_version_tuple(self):
        """Test version string to tuple conversion."""
        assert _version_tuple("1.0") == (1, 0)
        assert _version_tuple("2.1") == (2, 1)
        assert _version_tuple("10.5") == (10, 5)

    def test_version_tuple_invalid(self):
        """Test handling of invalid version strings."""
        assert _version_tuple("invalid") == (0, 0)
        assert _version_tuple("") == (0, 0)
        assert _version_tuple(None) == (0, 0)

    def test_is_version_compatible(self):
        """Test version compatibility checking."""
        # Current version should be compatible
        assert is_version_compatible(MANIFEST_VERSION) is True

        # Newer version should be compatible
        assert is_version_compatible("99.0") is True

        # Old version should not be compatible
        assert is_version_compatible("1.0") is False
        assert is_version_compatible("0.1") is False

    def test_is_version_compatible_custom_min(self):
        """Test version compatibility with custom minimum."""
        assert is_version_compatible("1.5", min_version="1.0") is True
        assert is_version_compatible("1.0", min_version="1.5") is False
        assert is_version_compatible("2.0", min_version="1.5") is True


class TestManifestVersioning:
    """Tests for manifest versioning."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_manifest_has_version(self, temp_dir):
        """Test that new manifests have version."""
        manifest = RunManifest(temp_dir, "test-run", "AAPL")

        assert manifest.version == MANIFEST_VERSION

    def test_manifest_serializes_version(self, temp_dir):
        """Test version is serialized."""
        manifest = RunManifest(temp_dir, "test-run", "AAPL")

        d = manifest.to_dict()

        assert "version" in d
        assert d["version"] == MANIFEST_VERSION

    def test_manifest_loads_version(self, temp_dir):
        """Test version is loaded from disk."""
        # Create and save
        manifest = RunManifest(temp_dir, "test-run", "AAPL")
        manifest.save()

        # Load
        loaded = RunManifest.load(temp_dir)

        assert loaded is not None
        assert loaded.version == MANIFEST_VERSION

    def test_manifest_loads_old_version(self, temp_dir):
        """Test loading manifest without version (pre-versioning)."""
        import orjson

        # Write old-style manifest
        manifest_path = temp_dir / "manifest.json"
        old_data = {
            "run_id": "old-run",
            "ticker": "MSFT",
            "started_at": "2024-01-01T00:00:00",
            "status": "completed",
            "phase": "complete",
            "artifacts": {},
            "errors": [],
            "warnings": [],
        }
        with open(manifest_path, "wb") as f:
            f.write(orjson.dumps(old_data))

        # Load should work
        loaded = RunManifest.load(temp_dir)

        assert loaded is not None
        assert loaded.version == "1.0"  # Default for old manifests


class TestCheckpoints:
    """Tests for checkpoint functionality."""

    @pytest.fixture
    def manifest(self):
        """Create manifest in temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield RunManifest(Path(tmpdir), "test-run", "TEST")

    def test_set_checkpoint(self, manifest):
        """Test setting a checkpoint."""
        manifest.set_checkpoint(Phase.DISCOVERY, "abc123")

        assert manifest.get_checkpoint(Phase.DISCOVERY) == "abc123"

    def test_get_checkpoint_missing(self, manifest):
        """Test getting nonexistent checkpoint."""
        result = manifest.get_checkpoint(Phase.VERTICALS)

        assert result is None

    def test_checkpoints_serialized(self, manifest):
        """Test checkpoints are serialized."""
        manifest.set_checkpoint(Phase.DISCOVERY, "hash1")
        manifest.set_checkpoint(Phase.VERTICALS, "hash2")

        d = manifest.to_dict()

        assert "checkpoints" in d
        assert d["checkpoints"]["discovery"] == "hash1"
        assert d["checkpoints"]["verticals"] == "hash2"

    def test_invalidate_from_phase(self, manifest):
        """Test invalidating checkpoints from a phase."""
        manifest.set_checkpoint(Phase.DISCOVERY, "hash1")
        manifest.set_checkpoint(Phase.VERTICALS, "hash2")
        manifest.set_checkpoint(Phase.FACT_CHECK, "hash3")

        manifest.invalidate_from_phase(Phase.VERTICALS)

        # Discovery should remain
        assert manifest.get_checkpoint(Phase.DISCOVERY) == "hash1"
        # Verticals and later should be gone
        assert manifest.get_checkpoint(Phase.VERTICALS) is None
        assert manifest.get_checkpoint(Phase.FACT_CHECK) is None

    def test_invalidate_all_phases(self, manifest):
        """Test invalidating all checkpoints."""
        manifest.set_checkpoint(Phase.DISCOVERY, "hash1")
        manifest.set_checkpoint(Phase.VERTICALS, "hash2")

        manifest.invalidate_from_phase(Phase.INIT)

        assert len(manifest.checkpoints) == 0


class TestInputHash:
    """Tests for input hash functionality."""

    @pytest.fixture
    def manifest(self):
        """Create manifest in temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield RunManifest(Path(tmpdir), "test-run", "TEST")

    def test_set_input_hash(self, manifest):
        """Test setting input hash."""
        params = {"ticker": "AAPL", "budget": 1.0}

        manifest.set_input_hash(params)

        assert manifest.input_hash != ""
        assert len(manifest.input_hash) == 16

    def test_input_hash_deterministic(self, manifest):
        """Test input hash is deterministic."""
        params = {"ticker": "AAPL", "budget": 1.0}

        manifest.set_input_hash(params)
        hash1 = manifest.input_hash

        manifest.set_input_hash(params)
        hash2 = manifest.input_hash

        assert hash1 == hash2

    def test_input_hash_changes_with_params(self, manifest):
        """Test input hash changes with different params."""
        manifest.set_input_hash({"ticker": "AAPL"})
        hash1 = manifest.input_hash

        manifest.set_input_hash({"ticker": "MSFT"})
        hash2 = manifest.input_hash

        assert hash1 != hash2

    def test_input_hash_serialized(self, manifest):
        """Test input hash is serialized."""
        manifest.set_input_hash({"test": "params"})

        d = manifest.to_dict()

        assert "input_hash" in d
        assert d["input_hash"] == manifest.input_hash


class TestCanResume:
    """Tests for resume capability checking."""

    @pytest.fixture
    def manifest(self):
        """Create manifest in temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield RunManifest(Path(tmpdir), "test-run", "TEST")

    def test_can_resume_running(self, manifest):
        """Test can resume a running manifest."""
        manifest.phase = Phase.VERTICALS
        manifest.status = "running"

        assert manifest.can_resume() is True

    def test_cannot_resume_completed(self, manifest):
        """Test cannot resume completed manifest."""
        manifest.phase = Phase.COMPLETE
        manifest.status = "completed"

        assert manifest.can_resume() is False

    def test_cannot_resume_failed(self, manifest):
        """Test cannot resume failed manifest."""
        manifest.phase = Phase.VERTICALS
        manifest.status = "failed"

        assert manifest.can_resume() is False

    def test_cannot_resume_init(self, manifest):
        """Test cannot resume if still in INIT."""
        manifest.phase = Phase.INIT
        manifest.status = "running"

        assert manifest.can_resume() is False

    def test_cannot_resume_old_version(self, manifest):
        """Test cannot resume old version manifest."""
        manifest.version = "0.1"
        manifest.phase = Phase.VERTICALS
        manifest.status = "running"

        assert manifest.can_resume() is False


class TestManifestPersistence:
    """Tests for manifest save/load with new fields."""

    def test_full_roundtrip(self):
        """Test full save/load roundtrip with all new fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Create manifest with all fields
            manifest = RunManifest(output_dir, "roundtrip-test", "NVDA")
            manifest.set_input_hash({"ticker": "NVDA", "budget": 2.0})
            manifest.set_checkpoint(Phase.DISCOVERY, "discovery_hash")
            manifest.set_checkpoint(Phase.VERTICALS, "verticals_hash")
            manifest.update_phase(Phase.FACT_CHECK)
            manifest.add_artifact("report", "/path/to/report.md")
            manifest.save()

            # Load and verify
            loaded = RunManifest.load(output_dir)

            assert loaded is not None
            assert loaded.version == MANIFEST_VERSION
            assert loaded.input_hash == manifest.input_hash
            assert loaded.get_checkpoint(Phase.DISCOVERY) == "discovery_hash"
            assert loaded.get_checkpoint(Phase.VERTICALS) == "verticals_hash"
            assert loaded.phase == Phase.FACT_CHECK
            assert loaded.artifacts["report"] == "/path/to/report.md"
