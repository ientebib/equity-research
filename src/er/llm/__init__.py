"""
LLM client package.

This package provides a unified interface for LLM providers:
- OpenAI (GPT-5.2 family)
- Anthropic (Claude 4.5 family)
- Google (Gemini 3 family)
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
from er.llm.router import AgentRole, EscalationLevel, LLMRouter

__all__ = [
    "AgentRole",
    "BudgetExceededError",
    "EscalationLevel",
    "LLMClient",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "LLMRouter",
    "RateLimitError",
    "ToolCall",
]
