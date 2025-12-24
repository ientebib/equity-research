"""
Custom exception hierarchy for the equity research system.

All exceptions inherit from ERError, which provides optional context
for structured error handling and logging.
"""

from __future__ import annotations

from typing import Any


class ERError(Exception):
    """Base exception for all equity research errors.

    Attributes:
        message: Human-readable error message.
        context: Optional structured context for logging/debugging.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            ctx_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} ({ctx_str})"
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r}, context={self.context!r})"


class ConfigurationError(ERError):
    """Raised when configuration is invalid or missing.

    Examples:
        - Missing required API keys
        - Invalid SEC_USER_AGENT format
        - Invalid budget limits
    """

    pass


class BudgetExceededError(ERError):
    """Raised when the run budget has been exceeded.

    Context should include:
        - budget_limit: The configured budget limit
        - current_cost: The current accumulated cost
        - attempted_cost: The cost of the operation that exceeded the budget
    """

    pass


class DataFetchError(ERError):
    """Raised when fetching external data fails.

    Context should include:
        - source: The data source (e.g., "SEC", "yfinance")
        - url: The URL that was being fetched
        - status_code: HTTP status code if applicable
        - retry_count: Number of retries attempted
    """

    pass


class EvidenceNotFoundError(ERError):
    """Raised when required evidence cannot be found.

    Context should include:
        - evidence_type: The type of evidence being searched for
        - query: The search query or criteria
        - sources_searched: List of sources that were searched
    """

    pass


class ValidationError(ERError):
    """Raised when data validation fails.

    Context should include:
        - field: The field that failed validation
        - value: The invalid value
        - expected: Description of what was expected
    """

    pass


class LLMError(ERError):
    """Raised when LLM API calls fail.

    Context should include:
        - provider: The LLM provider (openai, anthropic, gemini)
        - model: The model being used
        - error_type: The type of error (rate_limit, token_limit, etc.)
        - retry_count: Number of retries attempted
    """

    pass


class AgentError(ERError):
    """Raised when an agent encounters an error during execution.

    Context should include:
        - agent_name: Name of the agent that failed
        - phase: The phase the agent was in
        - task: Description of the task being performed
    """

    pass


class CoordinatorError(ERError):
    """Raised when the coordinator encounters an error.

    Context should include:
        - run_id: The run ID
        - phase: The current phase
        - agents_active: List of active agents
    """

    pass
