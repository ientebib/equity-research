"""
Configuration management using pydantic-settings.

Loads configuration from environment variables and .env files.
Validates required fields and provides typed access to settings.

This configuration is for Anthropic-only operation using Claude models
and the Claude Agent SDK.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Required:
        SEC_USER_AGENT: Email identification for SEC EDGAR API (must contain @)
        ANTHROPIC_API_KEY: Anthropic API key for Claude models

    Optional:
        FMP_API_KEY: Financial Modeling Prep API key for transcripts
        FINNHUB_API_KEY: Finnhub API key for transcripts
        MAX_BUDGET_USD: Maximum budget per run in USD
        MAX_DELIBERATION_ROUNDS: Maximum deliberation rounds
        MAX_CONCURRENT_AGENTS: Maximum concurrent agent tasks
        CACHE_DIR: Directory for caching data
        OUTPUT_DIR: Directory for output files
        LOG_LEVEL: Logging level
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required - SEC identification
    SEC_USER_AGENT: str = Field(
        ...,
        description="Email identification for SEC EDGAR API (required by SEC)",
    )

    # Required - Anthropic API Key
    ANTHROPIC_API_KEY: str = Field(
        ...,
        description="Anthropic API key for Claude models (required)",
    )

    # Optional data provider API keys
    FMP_API_KEY: str | None = Field(
        default=None, description="Financial Modeling Prep API key"
    )
    FINNHUB_API_KEY: str | None = Field(default=None, description="Finnhub API key")

    # Budget and limits
    MAX_BUDGET_USD: float = Field(
        default=25.0, ge=0.0, description="Maximum budget per run in USD"
    )
    MAX_DELIBERATION_ROUNDS: int = Field(
        default=5, ge=1, le=20, description="Maximum deliberation rounds"
    )
    MAX_CONCURRENT_AGENTS: int = Field(
        default=6, ge=1, le=20, description="Maximum concurrent agent tasks"
    )

    # Directories
    CACHE_DIR: Path = Field(default=Path(".cache"), description="Cache directory")
    OUTPUT_DIR: Path = Field(default=Path("output"), description="Output directory")

    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

    # Model defaults - all Claude models
    MODEL_WORKHORSE: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Default model for workhorse tasks (fast, cheap)",
    )
    MODEL_RESEARCH: str = Field(
        default="claude-sonnet-4-5-20250929",
        description="Default model for research tasks (balanced)",
    )
    MODEL_JUDGE: str = Field(
        default="claude-opus-4-5-20251101",
        description="Default model for judge/deliberation (high quality)",
    )
    MODEL_SYNTHESIS: str = Field(
        default="claude-opus-4-5-20251101",
        description="Default model for synthesis (high quality with extended thinking)",
    )

    @property
    def model_workhorse(self) -> str:
        """Get workhorse model (lowercase alias)."""
        return self.MODEL_WORKHORSE

    @property
    def model_research(self) -> str:
        """Get research model (lowercase alias)."""
        return self.MODEL_RESEARCH

    @property
    def model_judge(self) -> str:
        """Get judge model (lowercase alias)."""
        return self.MODEL_JUDGE

    @property
    def model_synthesis(self) -> str:
        """Get synthesis model (lowercase alias)."""
        return self.MODEL_SYNTHESIS

    @property
    def anthropic_api_key(self) -> str:
        """Get Anthropic API key (lowercase alias)."""
        return self.ANTHROPIC_API_KEY

    @field_validator("SEC_USER_AGENT")
    @classmethod
    def validate_sec_user_agent(cls, v: str) -> str:
        """Validate that SEC_USER_AGENT contains an email address."""
        if "@" not in v:
            raise ValueError(
                "SEC_USER_AGENT must contain an email address (SEC requirement)"
            )
        return v

    def ensure_directories(self) -> None:
        """Create cache and output directories if they don't exist."""
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def get_run_output_dir(self, run_id: str) -> Path:
        """Get the output directory for a specific run."""
        run_dir = self.OUTPUT_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def redacted_display(self) -> dict[str, str | int | float | None]:
        """Return settings with API keys redacted for display."""
        def redact(key: str, value: str | None) -> str | None:
            if value is None:
                return None
            if "KEY" in key or "SECRET" in key:
                return f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            return value

        return {
            "SEC_USER_AGENT": self.SEC_USER_AGENT,
            "ANTHROPIC_API_KEY": redact("ANTHROPIC_API_KEY", self.ANTHROPIC_API_KEY),
            "FMP_API_KEY": redact("FMP_API_KEY", self.FMP_API_KEY),
            "FINNHUB_API_KEY": redact("FINNHUB_API_KEY", self.FINNHUB_API_KEY),
            "MAX_BUDGET_USD": self.MAX_BUDGET_USD,
            "MAX_DELIBERATION_ROUNDS": self.MAX_DELIBERATION_ROUNDS,
            "MAX_CONCURRENT_AGENTS": self.MAX_CONCURRENT_AGENTS,
            "CACHE_DIR": str(self.CACHE_DIR),
            "OUTPUT_DIR": str(self.OUTPUT_DIR),
            "LOG_LEVEL": self.LOG_LEVEL,
            "MODEL_WORKHORSE": self.MODEL_WORKHORSE,
            "MODEL_RESEARCH": self.MODEL_RESEARCH,
            "MODEL_JUDGE": self.MODEL_JUDGE,
            "MODEL_SYNTHESIS": self.MODEL_SYNTHESIS,
        }


@lru_cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Settings instance loaded from environment.

    Raises:
        ValidationError: If required settings are missing or invalid.
    """
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache (useful for testing)."""
    get_settings.cache_clear()
