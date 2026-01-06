"""
Anthropic LLM client implementation.

Supports Claude 4.5 family models using the AsyncAnthropic client.
"""

from __future__ import annotations

import time
from typing import Any

import orjson
from anthropic import AsyncAnthropic, APIError, RateLimitError as AnthropicRateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from er.llm.base import (
    AuthenticationError,
    ContextLengthError,
    LLMError,
    LLMRequest,
    LLMResponse,
    ModelNotFoundError,
    RateLimitError,
    ToolCall,
)
from er.logging import get_logger

logger = get_logger(__name__)

# Supported Anthropic models (Claude 4.5 family)
SUPPORTED_MODELS = {
    # Claude 4.5 family (current generation)
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5-20250929",
    # Claude 4 family
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    # Legacy Claude 3.5 (still supported)
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
}

# Models that support extended thinking
EXTENDED_THINKING_MODELS = {
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
}


class AnthropicClient:
    """Anthropic LLM client using AsyncAnthropic.

    Supports Claude 4.5 family with tool calling and extended thinking.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Anthropic client.

        Args:
            api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY env var.
        """
        self._client = AsyncAnthropic(api_key=api_key)
        self._provider = "anthropic"

    @property
    def provider(self) -> str:
        """Name of this provider."""
        return self._provider

    def supports_model(self, model: str) -> bool:
        """Check if this client supports the given model.

        Args:
            model: Model name to check.

        Returns:
            True if supported.
        """
        return model in SUPPORTED_MODELS or model.startswith("claude-")

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic format.

        Anthropic requires system message as a separate parameter.

        Args:
            messages: OpenAI-style messages.

        Returns:
            Tuple of (system_message, converted_messages).
        """
        system_message: str | None = None
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # Anthropic takes system as a separate param
                if system_message:
                    system_message += f"\n\n{content}"
                else:
                    system_message = content
            elif role == "assistant":
                converted.append({"role": "assistant", "content": content})
            elif role == "tool":
                # Convert tool result to Anthropic format
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": content,
                        }
                    ],
                })
            else:
                # user message
                converted.append({"role": "user", "content": content})

        return system_message, converted

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style tools to Anthropic format.

        Args:
            tools: OpenAI-style tool definitions.

        Returns:
            Anthropic-style tool definitions.
        """
        converted = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                converted.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
            else:
                # Already in Anthropic format or other format
                converted.append(tool)
        return converted

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request.

        Args:
            request: The LLM request.

        Returns:
            LLM response.

        Raises:
            LLMError: If the request fails.
        """
        start_time = time.monotonic()

        try:
            # Convert messages
            system_message, messages = self._convert_messages(request.messages)

            # Build the request parameters
            params: dict[str, Any] = {
                "model": request.model,
                "messages": messages,
                "max_tokens": request.max_tokens or 4096,
            }

            if system_message:
                params["system"] = system_message

            # Anthropic doesn't support temperature for some models
            if request.temperature is not None:
                params["temperature"] = request.temperature

            if request.stop:
                params["stop_sequences"] = request.stop

            # Make the API call
            response = await self._client.messages.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract text content
            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self._provider,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason or "stop",
                latency_ms=latency_ms,
            )

        except AnthropicRateLimitError as e:
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)

            logger.warning(
                "Anthropic rate limit hit",
                model=request.model,
                retry_after=retry_after,
            )
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)

            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise AuthenticationError(f"Anthropic authentication failed: {error_msg}") from e

            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context" in error_msg.lower() or "too long" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"Anthropic API error: {error_msg}") from e

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def complete_with_tools(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request with tool calling.

        Args:
            request: The LLM request with tools defined.

        Returns:
            LLM response, potentially with tool_calls.

        Raises:
            LLMError: If the request fails.
        """
        if not request.tools:
            return await self.complete(request)

        start_time = time.monotonic()

        try:
            # Convert messages and tools
            system_message, messages = self._convert_messages(request.messages)
            tools = self._convert_tools(request.tools)

            # Build the request parameters
            params: dict[str, Any] = {
                "model": request.model,
                "messages": messages,
                "max_tokens": request.max_tokens or 4096,
                "tools": tools,
            }

            if system_message:
                params["system"] = system_message

            if request.temperature is not None:
                params["temperature"] = request.temperature

            if request.tool_choice:
                if request.tool_choice == "auto":
                    params["tool_choice"] = {"type": "auto"}
                elif request.tool_choice == "none":
                    params["tool_choice"] = {"type": "none"}
                else:
                    # Specific tool
                    params["tool_choice"] = {"type": "tool", "name": request.tool_choice}

            # Make the API call
            response = await self._client.messages.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract content and tool calls
            content = ""
            tool_calls: list[ToolCall] = []

            for block in response.content:
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=block.input if isinstance(block.input, dict) else {},
                        )
                    )

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self._provider,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                tool_calls=tool_calls if tool_calls else None,
                finish_reason=response.stop_reason or "stop",
                latency_ms=latency_ms,
            )

        except AnthropicRateLimitError as e:
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)

            logger.warning(
                "Anthropic rate limit hit",
                model=request.model,
                retry_after=retry_after,
            )
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)

            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise AuthenticationError(f"Anthropic authentication failed: {error_msg}") from e

            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context" in error_msg.lower() or "too long" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"Anthropic API error: {error_msg}") from e

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def complete_with_thinking(
        self,
        request: LLMRequest,
        budget_tokens: int = 10000,
        expected_output_tokens: int = 8000,
    ) -> LLMResponse:
        """Send a completion request with extended thinking.

        Extended thinking enables Claude to reason through complex problems
        step-by-step before providing a final answer.

        IMPORTANT: max_tokens = budget_tokens + expected_output_tokens + buffer
        The budget_tokens is a SUBSET of max_tokens, not additional. If you want
        20K thinking and 15K output, you need max_tokens >= 35K.

        Args:
            request: The LLM request. Note: request.max_tokens is IGNORED in favor
                     of computing it from budget_tokens + expected_output_tokens.
            budget_tokens: Maximum tokens for thinking blocks (min 1024).
            expected_output_tokens: Expected tokens for visible output. This should
                                   match what you expect the model to produce.
                                   - Synthesis reports: 20000-25000
                                   - Judge feedback: 8000-10000
                                   - Short responses: 4000-8000

        Returns:
            LLM response with thinking content accessible via metadata.

        Raises:
            LLMError: If the request fails.
        """
        start_time = time.monotonic()

        # Validate model supports extended thinking
        if request.model not in EXTENDED_THINKING_MODELS:
            logger.warning(
                "Model may not support extended thinking",
                model=request.model,
            )

        # Ensure budget_tokens meets minimum
        if budget_tokens < 1024:
            budget_tokens = 1024

        # Ensure expected_output_tokens is reasonable
        if expected_output_tokens < 1000:
            expected_output_tokens = 1000

        try:
            # Convert messages
            system_message, messages = self._convert_messages(request.messages)

            # Compute max_tokens correctly:
            # max_tokens = budget_tokens (for thinking) + expected_output_tokens + buffer
            # The buffer accounts for slight variations in output length
            buffer = 1000
            max_tokens = budget_tokens + expected_output_tokens + buffer

            # Log the configuration for debugging
            logger.debug(
                "Extended thinking configuration",
                budget_tokens=budget_tokens,
                expected_output_tokens=expected_output_tokens,
                max_tokens=max_tokens,
                model=request.model,
            )

            params: dict[str, Any] = {
                "model": request.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": budget_tokens,
                },
            }

            if system_message:
                params["system"] = system_message

            # Note: temperature is not supported with extended thinking
            # Anthropic uses fixed temperature for thinking mode

            if request.stop:
                params["stop_sequences"] = request.stop

            # Make the API call with streaming (required for long operations)
            # Anthropic requires streaming for requests that may take >10 minutes
            content = ""
            thinking_content = ""
            input_tokens = 0
            output_tokens = 0
            model_name = request.model
            stop_reason = "stop"

            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    # Handle different event types
                    if hasattr(event, 'type'):
                        if event.type == 'content_block_delta':
                            if hasattr(event.delta, 'text'):
                                content += event.delta.text
                            elif hasattr(event.delta, 'thinking'):
                                thinking_content += event.delta.thinking
                        elif event.type == 'message_start':
                            if hasattr(event.message, 'model'):
                                model_name = event.message.model
                        elif event.type == 'message_delta':
                            if hasattr(event, 'usage'):
                                output_tokens = getattr(event.usage, 'output_tokens', 0)
                            if hasattr(event.delta, 'stop_reason'):
                                stop_reason = event.delta.stop_reason or "stop"

                # Get final message for accurate token counts
                final_message = await stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens
                model_name = final_message.model
                stop_reason = final_message.stop_reason or "stop"

            latency_ms = int((time.monotonic() - start_time) * 1000)
            thinking_tokens = len(thinking_content) // 4  # Rough estimate

            # Check for potential truncation (stop_reason indicates if output was cut off)
            was_truncated = stop_reason == "max_tokens"
            if was_truncated:
                logger.warning(
                    "Extended thinking output was truncated - consider increasing expected_output_tokens",
                    output_tokens=output_tokens,
                    expected_output_tokens=expected_output_tokens,
                    budget_tokens=budget_tokens,
                    max_tokens=max_tokens,
                )

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self._provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=stop_reason,
                latency_ms=latency_ms,
                metadata={
                    "thinking": thinking_content,
                    "thinking_tokens": thinking_tokens,
                    "budget_tokens": budget_tokens,
                    "expected_output_tokens": expected_output_tokens,
                    "max_tokens": max_tokens,
                    "was_truncated": was_truncated,
                },
            )

        except AnthropicRateLimitError as e:
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)

            logger.warning(
                "Anthropic rate limit hit",
                model=request.model,
                retry_after=retry_after,
            )
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)

            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise AuthenticationError(f"Anthropic authentication failed: {error_msg}") from e

            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context" in error_msg.lower() or "too long" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            if "thinking" in error_msg.lower():
                raise LLMError(f"Extended thinking error: {error_msg}") from e

            raise LLMError(f"Anthropic API error: {error_msg}") from e

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def complete_with_web_search(
        self,
        request: LLMRequest,
        max_searches: int = 10,
        allowed_domains: list[str] | None = None,
    ) -> LLMResponse:
        """Send a completion request with web search capability.

        Uses Claude's built-in web search tool to find current information.

        IMPORTANT: Each web search returns full page content from multiple results,
        which can consume 60-80K tokens per search. With max_searches=10, this can
        easily reach 600K+ input tokens. Use allowed_domains to restrict to high-quality
        sources and reduce token consumption.

        Args:
            request: The LLM request.
            max_searches: Maximum number of web searches to perform (default 10).
                         Each search can consume ~60K tokens of context.
            allowed_domains: Optional list of domains to restrict searches to.
                           Recommended for cost control. Example:
                           ["bloomberg.com", "reuters.com", "wsj.com", "seekingalpha.com"]

        Returns:
            LLM response with web search results incorporated.

        Raises:
            LLMError: If the request fails.
        """
        start_time = time.monotonic()

        try:
            # Convert messages
            system_message, messages = self._convert_messages(request.messages)

            # Build web search tool configuration
            web_search_tool: dict[str, Any] = {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_searches,
            }

            # Add domain filtering to reduce token consumption
            # Each search returns full page content, so restricting to
            # high-quality sources helps control costs
            if allowed_domains:
                web_search_tool["allowed_domains"] = allowed_domains

            # Build the request parameters with web search tool
            params: dict[str, Any] = {
                "model": request.model,
                "messages": messages,
                "max_tokens": request.max_tokens or 16000,
                "tools": [web_search_tool],
            }

            if system_message:
                params["system"] = system_message

            if request.temperature is not None:
                params["temperature"] = request.temperature

            if request.stop:
                params["stop_sequences"] = request.stop

            # Make the API call
            response = await self._client.messages.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract text content (web search results are incorporated into the response)
            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self._provider,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason or "stop",
                latency_ms=latency_ms,
            )

        except AnthropicRateLimitError as e:
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)

            logger.warning(
                "Anthropic rate limit hit",
                model=request.model,
                retry_after=retry_after,
            )
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)

            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise AuthenticationError(f"Anthropic authentication failed: {error_msg}") from e

            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context" in error_msg.lower() or "too long" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"Anthropic API error: {error_msg}") from e

    async def close(self) -> None:
        """Close the client."""
        await self._client.close()
