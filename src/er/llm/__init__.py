"""
LLM client package.

This package provides a unified interface for LLM providers:
- Anthropic (Claude family) - primary provider
- Claude Agent SDK - for multi-agent orchestration
"""

from er.llm.base import (
    BudgetExceededError,
    LLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    RateLimitError,
    ToolCall,
)
from er.llm.anthropic_client import AnthropicClient

__all__ = [
    "AnthropicClient",
    "BudgetExceededError",
    "LLMClient",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "RateLimitError",
    "ToolCall",
]
