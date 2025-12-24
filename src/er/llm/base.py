"""
Base classes and interfaces for LLM clients.

This module defines:
- LLMRequest: Standardized request format
- LLMResponse: Standardized response format
- ToolCall: Tool call representation
- LLMClient: Protocol for all LLM providers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMRequest:
    """Standardized LLM request format.

    All providers convert from this format to their native format.
    """

    messages: list[dict[str, Any]]  # [{"role": "system"|"user"|"assistant", "content": "..."}]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None  # Tool definitions
    tool_choice: str | None = None  # "auto", "none", or specific tool
    response_format: dict[str, Any] | None = None  # For structured output (JSON mode)
    stop: list[str] | None = None  # Stop sequences


@dataclass
class LLMResponse:
    """Standardized LLM response format.

    All providers convert to this format from their native format.
    """

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    tool_calls: list[ToolCall] | None = None
    finish_reason: str = "stop"
    latency_ms: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens


@dataclass
class DryRunResponse:
    """Configuration for dry run mode responses."""

    content: str = "This is a dry run response."
    input_tokens: int = 100
    output_tokens: int = 50


# Default dry run responses by role
DRY_RUN_RESPONSES: dict[str, DryRunResponse] = {
    "orchestration": DryRunResponse(
        content='{"action": "continue", "next_phase": "research"}',
        input_tokens=150,
        output_tokens=30,
    ),
    "discovery": DryRunResponse(
        content='{"questions": ["What is the revenue growth?", "What are the margins?"], "focus_areas": ["financials", "competitive_position"]}',
        input_tokens=500,
        output_tokens=100,
    ),
    "decomposition": DryRunResponse(
        content='{"subtasks": [{"id": "task_1", "description": "Analyze revenue"}, {"id": "task_2", "description": "Analyze margins"}]}',
        input_tokens=400,
        output_tokens=150,
    ),
    "research": DryRunResponse(
        content='{"findings": "Based on the analysis, revenue grew 15% YoY.", "confidence": 0.85, "evidence_ids": ["ev_001"]}',
        input_tokens=2000,
        output_tokens=500,
    ),
    "synthesis": DryRunResponse(
        content='{"summary": "The company shows strong fundamentals with growing revenue and expanding margins.", "key_points": ["Revenue growth", "Margin expansion"], "confidence": 0.8}',
        input_tokens=3000,
        output_tokens=800,
    ),
    "judge": DryRunResponse(
        content='{"verdict": "buy", "confidence": 0.75, "reasoning": "Strong fundamentals and growth trajectory support a buy rating."}',
        input_tokens=4000,
        output_tokens=300,
    ),
    "factcheck": DryRunResponse(
        content='{"verified": true, "issues": [], "confidence": 0.9}',
        input_tokens=1000,
        output_tokens=50,
    ),
    "output": DryRunResponse(
        content='{"report_section": "## Executive Summary\\n\\nThe company demonstrates strong growth..."}',
        input_tokens=2000,
        output_tokens=1000,
    ),
    "default": DryRunResponse(
        content='{"status": "ok", "message": "Dry run response"}',
        input_tokens=100,
        output_tokens=50,
    ),
}


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM clients.

    All providers must implement this interface.
    """

    @property
    def provider(self) -> str:
        """Name of this provider (e.g., 'openai', 'anthropic', 'google')."""
        ...

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request.

        Args:
            request: The LLM request.

        Returns:
            LLM response.

        Raises:
            LLMError: If the request fails.
        """
        ...

    async def complete_with_tools(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request with tool calling.

        Args:
            request: The LLM request with tools defined.

        Returns:
            LLM response, potentially with tool_calls.

        Raises:
            LLMError: If the request fails.
        """
        ...

    def supports_model(self, model: str) -> bool:
        """Check if this client supports the given model.

        Args:
            model: Model name to check.

        Returns:
            True if supported.
        """
        ...

    async def close(self) -> None:
        """Close any open connections."""
        ...


class LLMError(Exception):
    """Base exception for LLM errors."""

    pass


class RateLimitError(LLMError):
    """Rate limit exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AuthenticationError(LLMError):
    """Authentication failed."""

    pass


class ModelNotFoundError(LLMError):
    """Model not found or not accessible."""

    pass


class ContextLengthError(LLMError):
    """Context length exceeded."""

    pass


class BudgetExceededError(LLMError):
    """Budget limit exceeded."""

    pass
