"""
Pytest configuration and fixtures for equity research tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from er.config import Settings, clear_settings_cache
from er.types import Phase, RunState


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test outputs."""
    return tmp_path


@pytest.fixture
def mock_env_vars() -> Generator[dict[str, str], None, None]:
    """Provide mock environment variables for testing.

    Sets up fake API keys and required configuration.
    """
    env_vars = {
        "SEC_USER_AGENT": "Test User test@example.com",
        "OPENAI_API_KEY": "sk-test-fake-openai-key-1234567890",
        "ANTHROPIC_API_KEY": "sk-ant-test-fake-anthropic-key",
        "GEMINI_API_KEY": "",  # Override any .env value
        "PREFERRED_PROVIDER": "",  # Avoid forcing provider in tests
        "FMP_API_KEY": "test-fmp-key",
        "FINNHUB_API_KEY": None,
        "MAX_BUDGET_USD": "50.0",
        "MAX_DELIBERATION_ROUNDS": "3",
        "MAX_CONCURRENT_AGENTS": "4",
        "CACHE_DIR": ".test_cache",
        "OUTPUT_DIR": "test_output",
        "LOG_LEVEL": "DEBUG",
    }

    # Filter out None values
    active_vars = {k: v for k, v in env_vars.items() if v is not None}

    with patch.dict(os.environ, active_vars, clear=False):
        # Clear any cached settings
        clear_settings_cache()
        yield env_vars


@pytest.fixture
def mock_settings(mock_env_vars: dict[str, str], temp_dir: Path) -> Generator[Settings, None, None]:
    """Provide a Settings instance with mock configuration.

    Uses temp_dir for cache and output directories.
    """
    # Override dirs to use temp_dir
    with patch.dict(
        os.environ,
        {
            "CACHE_DIR": str(temp_dir / "cache"),
            "OUTPUT_DIR": str(temp_dir / "output"),
        },
    ):
        clear_settings_cache()
        from er.config import get_settings

        settings = get_settings()
        settings.ensure_directories()
        yield settings
        clear_settings_cache()


@pytest.fixture
def run_state(mock_settings: Settings) -> RunState:
    """Provide a RunState instance for testing."""
    return RunState.create(
        ticker="AAPL",
        budget_usd=mock_settings.MAX_BUDGET_USD,
    )


@pytest.fixture
def completed_run_state(run_state: RunState) -> RunState:
    """Provide a RunState that has progressed through phases."""
    run_state.phase = Phase.COMPLETE
    run_state.market_data = {
        "price": 150.0,
        "market_cap": 2500000000000,
        "pe_ratio": 25.0,
    }
    run_state.record_cost(tokens=10000, cost_usd=0.50)
    return run_state


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None, None, None]:
    """Automatically reset settings cache before and after each test."""
    clear_settings_cache()
    yield
    clear_settings_cache()
