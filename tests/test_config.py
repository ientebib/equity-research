"""
Tests for configuration module.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from er.config import Settings, clear_settings_cache, get_settings


class TestSettingsValidation:
    """Tests for Settings validation."""

    def test_settings_loads_from_env(self, mock_env_vars: dict[str, str]) -> None:
        """Test that settings correctly loads from environment variables."""
        settings = get_settings()

        assert settings.SEC_USER_AGENT == "Test User test@example.com"
        assert settings.OPENAI_API_KEY == "sk-test-fake-openai-key-1234567890"
        assert settings.ANTHROPIC_API_KEY == "sk-ant-test-fake-anthropic-key"
        assert settings.MAX_BUDGET_USD == 50.0
        assert settings.MAX_DELIBERATION_ROUNDS == 3
        assert settings.MAX_CONCURRENT_AGENTS == 4
        assert settings.LOG_LEVEL == "DEBUG"

    def test_validation_fails_without_any_api_key(self) -> None:
        """Test that validation fails if no LLM API key is provided."""
        env_vars = {
            "SEC_USER_AGENT": "Test User test@example.com",
            # No API keys
        }

        # Clear any existing keys from environment
        keys_to_clear = [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
        ]

        with patch.dict(os.environ, env_vars, clear=True):
            clear_settings_cache()

            with pytest.raises(ValidationError) as exc_info:
                # Use _env_file=None to prevent loading from .env
                Settings(_env_file=None)

            # Check the error message mentions API keys
            error_str = str(exc_info.value)
            assert "LLM provider" in error_str or "API key" in error_str

    def test_sec_user_agent_validation_requires_email(self) -> None:
        """Test that SEC_USER_AGENT must contain an @ symbol (email)."""
        env_vars = {
            "SEC_USER_AGENT": "Invalid User Agent Without Email",
            "OPENAI_API_KEY": "sk-test-key",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            clear_settings_cache()

            with pytest.raises(ValidationError) as exc_info:
                Settings()

            error_str = str(exc_info.value)
            assert "email" in error_str.lower() or "@" in error_str

    def test_sec_user_agent_validation_accepts_valid_email(
        self, mock_env_vars: dict[str, str]
    ) -> None:
        """Test that SEC_USER_AGENT accepts a valid email format."""
        settings = get_settings()
        assert "@" in settings.SEC_USER_AGENT

    def test_available_providers_property(self, mock_env_vars: dict[str, str]) -> None:
        """Test that available_providers returns correct list."""
        settings = get_settings()
        providers = settings.available_providers

        # Should have openai and anthropic (set in mock_env_vars)
        assert "openai" in providers
        assert "anthropic" in providers
        # Note: gemini may or may not be set depending on .env

    def test_available_providers_single_provider(self) -> None:
        """Test available_providers with only one provider configured."""
        env_vars = {
            "SEC_USER_AGENT": "Test test@example.com",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            clear_settings_cache()

            # Use _env_file=None to prevent loading from .env
            settings = Settings(_env_file=None)
            assert settings.available_providers == ["anthropic"]


class TestSettingsDefaults:
    """Tests for Settings default values."""

    def test_default_budget(self) -> None:
        """Test default budget value."""
        env_vars = {
            "SEC_USER_AGENT": "Test test@example.com",
            "OPENAI_API_KEY": "sk-test",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            os.environ.pop("MAX_BUDGET_USD", None)
            clear_settings_cache()

            settings = Settings()
            assert settings.MAX_BUDGET_USD == 25.0

    def test_default_directories(self) -> None:
        """Test default directory paths."""
        env_vars = {
            "SEC_USER_AGENT": "Test test@example.com",
            "OPENAI_API_KEY": "sk-test",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            os.environ.pop("CACHE_DIR", None)
            os.environ.pop("OUTPUT_DIR", None)
            clear_settings_cache()

            settings = Settings()
            assert settings.CACHE_DIR == Path(".cache")
            assert settings.OUTPUT_DIR == Path("output")


class TestSettingsMethods:
    """Tests for Settings methods."""

    def test_ensure_directories_creates_dirs(
        self, mock_settings: Settings, temp_dir: Path
    ) -> None:
        """Test that ensure_directories creates cache and output dirs."""
        mock_settings.ensure_directories()

        assert mock_settings.CACHE_DIR.exists()
        assert mock_settings.OUTPUT_DIR.exists()

    def test_get_run_output_dir(self, mock_settings: Settings) -> None:
        """Test get_run_output_dir creates run-specific directory."""
        run_dir = mock_settings.get_run_output_dir("run_test123")

        assert run_dir.exists()
        assert run_dir.name == "run_test123"
        assert run_dir.parent == mock_settings.OUTPUT_DIR

    def test_redacted_display_hides_keys(self, mock_settings: Settings) -> None:
        """Test that redacted_display masks API keys."""
        display = mock_settings.redacted_display()

        # API keys should be redacted
        openai_key = display.get("OPENAI_API_KEY")
        assert openai_key is not None
        assert "..." in str(openai_key)
        assert len(str(openai_key)) < len(str(mock_settings.OPENAI_API_KEY or ""))

        # Non-sensitive values should not be redacted
        assert display["SEC_USER_AGENT"] == mock_settings.SEC_USER_AGENT
        assert display["MAX_BUDGET_USD"] == mock_settings.MAX_BUDGET_USD


class TestSettingsCache:
    """Tests for settings caching."""

    def test_get_settings_returns_same_instance(
        self, mock_env_vars: dict[str, str]
    ) -> None:
        """Test that get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_clear_settings_cache_clears_cache(
        self, mock_env_vars: dict[str, str]
    ) -> None:
        """Test that clear_settings_cache clears the cache."""
        settings1 = get_settings()
        clear_settings_cache()
        settings2 = get_settings()

        # Should be different instances (though with same values)
        assert settings1 is not settings2
