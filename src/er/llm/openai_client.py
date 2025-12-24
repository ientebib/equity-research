"""
OpenAI LLM client implementation.

Supports GPT-5.2 family models using the AsyncOpenAI client.
Also supports o4-mini-deep-research via the Responses API.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import orjson
from openai import AsyncOpenAI, APIError, RateLimitError as OpenAIRateLimitError
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

# Supported OpenAI models (GPT-5.2 family)
SUPPORTED_MODELS = {
    # GPT-5.2 family (current generation)
    "gpt-5.2-2025-12-11",
    "gpt-5.2",
    "gpt-5.2-mini",
    "gpt-5.2-mini-2025-12-11",
    # Legacy models (still supported)
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4o-2024-11-20",
    "gpt-4-turbo",
    # Reasoning models
    "o1",
    "o1-mini",
    "o3-mini",
    "o4-mini",
    # Deep Research models (use Responses API)
    "o3-deep-research-2025-06-26",
    "o4-mini-deep-research-2025-06-26",
}

# Models that use the Responses API instead of Chat Completions
DEEP_RESEARCH_MODELS = {
    "o3-deep-research-2025-06-26",
    "o4-mini-deep-research-2025-06-26",
    "o4-mini-deep-research",  # alias
}

# Models that support reasoning_effort parameter
REASONING_MODELS = {
    "o1",
    "o1-mini",
    "o3-mini",
    "o4-mini",
    "gpt-5.2",
    "gpt-5.2-2025-12-11",
}


class OpenAIClient:
    """OpenAI LLM client using AsyncOpenAI.

    Supports GPT-5.2 family with tool calling and structured output.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the OpenAI client.

        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY env var.
        """
        self._client = AsyncOpenAI(api_key=api_key)
        self._provider = "openai"

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
        return model in SUPPORTED_MODELS or model.startswith("gpt-")

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
            # Build the request parameters
            params: dict[str, Any] = {
                "model": request.model,
                "messages": request.messages,
                "temperature": request.temperature,
            }

            if request.max_tokens:
                params["max_tokens"] = request.max_tokens

            if request.stop:
                params["stop"] = request.stop

            if request.response_format:
                params["response_format"] = request.response_format

            # Make the API call
            response = await self._client.chat.completions.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract the response
            choice = response.choices[0]
            content = choice.message.content or ""

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self._provider,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                finish_reason=choice.finish_reason or "stop",
                latency_ms=latency_ms,
            )

        except OpenAIRateLimitError as e:
            # Extract retry-after if available
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)

            logger.warning(
                "OpenAI rate limit hit",
                model=request.model,
                retry_after=retry_after,
            )
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)

            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise AuthenticationError(f"OpenAI authentication failed: {error_msg}") from e

            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context_length" in error_msg.lower() or "maximum context" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"OpenAI API error: {error_msg}") from e

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
            # Build the request parameters
            params: dict[str, Any] = {
                "model": request.model,
                "messages": request.messages,
                "temperature": request.temperature,
                "tools": request.tools,
            }

            if request.max_tokens:
                params["max_tokens"] = request.max_tokens

            if request.tool_choice:
                params["tool_choice"] = request.tool_choice

            if request.response_format:
                params["response_format"] = request.response_format

            # Make the API call
            response = await self._client.chat.completions.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract the response
            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract tool calls if present
            tool_calls: list[ToolCall] | None = None
            if choice.message.tool_calls:
                tool_calls = []
                for tc in choice.message.tool_calls:
                    try:
                        arguments = orjson.loads(tc.function.arguments)
                    except orjson.JSONDecodeError:
                        arguments = {"raw": tc.function.arguments}

                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=arguments,
                        )
                    )

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self._provider,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
                latency_ms=latency_ms,
            )

        except OpenAIRateLimitError as e:
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)

            logger.warning(
                "OpenAI rate limit hit",
                model=request.model,
                retry_after=retry_after,
            )
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)

            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                raise AuthenticationError(f"OpenAI authentication failed: {error_msg}") from e

            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context_length" in error_msg.lower() or "maximum context" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"OpenAI API error: {error_msg}") from e

    async def complete_with_reasoning(
        self,
        request: LLMRequest,
        reasoning_effort: str = "medium",
    ) -> LLMResponse:
        """Send a completion request with reasoning effort.

        For models that support reasoning (o1, o3, o4, gpt-5.2).

        Args:
            request: The LLM request.
            reasoning_effort: One of "low", "medium", "high", "xhigh".

        Returns:
            LLM response.

        Raises:
            LLMError: If the request fails.
        """
        start_time = time.monotonic()

        try:
            # Build the request parameters
            params: dict[str, Any] = {
                "model": request.model,
                "messages": request.messages,
            }

            # Add reasoning effort for supported models
            if request.model in REASONING_MODELS:
                params["reasoning"] = {"effort": reasoning_effort}

            if request.max_tokens:
                params["max_tokens"] = request.max_tokens

            if request.response_format:
                params["response_format"] = request.response_format

            # Make the API call
            response = await self._client.chat.completions.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract the response
            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract reasoning tokens if available
            reasoning_tokens = 0
            if hasattr(response.usage, "completion_tokens_details"):
                details = response.usage.completion_tokens_details
                if hasattr(details, "reasoning_tokens"):
                    reasoning_tokens = details.reasoning_tokens or 0

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self._provider,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                finish_reason=choice.finish_reason or "stop",
                latency_ms=latency_ms,
                metadata={"reasoning_tokens": reasoning_tokens} if reasoning_tokens else None,
            )

        except OpenAIRateLimitError as e:
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = float(retry_after_header)
            raise RateLimitError(str(e), retry_after=retry_after) from e

        except APIError as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower():
                raise AuthenticationError(f"OpenAI authentication failed: {error_msg}") from e
            if "model" in error_msg.lower() and "not found" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e
            raise LLMError(f"OpenAI API error: {error_msg}") from e

    async def deep_research(
        self,
        query: str,
        system_message: str | None = None,
        model: str = "o4-mini-deep-research-2025-06-26",
        poll_interval: float = 10.0,
        max_wait_seconds: float = 600.0,
        include_code_interpreter: bool = False,
    ) -> LLMResponse:
        """Run a deep research query using o4-mini-deep-research.

        This uses the Responses API which supports web search and runs
        asynchronously with polling.

        Args:
            query: The research query.
            system_message: Optional system/developer message.
            model: Deep research model to use.
            poll_interval: Seconds between polling attempts.
            max_wait_seconds: Maximum time to wait for completion.
            include_code_interpreter: Whether to include code interpreter tool.

        Returns:
            LLM response with research results.

        Raises:
            LLMError: If the request fails or times out.
        """
        start_time = time.monotonic()

        # Resolve model alias
        if model == "o4-mini-deep-research":
            model = "o4-mini-deep-research-2025-06-26"

        logger.info(
            "Starting deep research",
            model=model,
            query_length=len(query),
        )

        try:
            # Build input messages
            input_messages: list[dict[str, Any]] = []

            if system_message:
                input_messages.append({
                    "role": "developer",
                    "content": [{"type": "input_text", "text": system_message}],
                })

            input_messages.append({
                "role": "user",
                "content": [{"type": "input_text", "text": query}],
            })

            # Build tools list
            tools: list[dict[str, Any]] = [{"type": "web_search_preview"}]
            if include_code_interpreter:
                tools.append({
                    "type": "code_interpreter",
                    "container": {"type": "auto"},
                })

            # Create the research request (background mode)
            response = await self._client.responses.create(
                model=model,
                input=input_messages,
                reasoning={"summary": "auto"},
                tools=tools,
                background=True,
            )

            response_id = response.id
            logger.info("Deep research started", response_id=response_id)

            # Poll for completion
            elapsed = 0.0
            while elapsed < max_wait_seconds:
                await asyncio.sleep(poll_interval)
                elapsed = time.monotonic() - start_time

                # Check status
                result = await self._client.responses.retrieve(response_id)
                status = result.status

                logger.debug(
                    "Deep research poll",
                    response_id=response_id,
                    status=status,
                    elapsed=f"{elapsed:.1f}s",
                )

                if status == "succeeded":
                    # Extract the final output
                    content = ""
                    annotations = []

                    if result.output:
                        last_output = result.output[-1]
                        if hasattr(last_output, "content") and last_output.content:
                            for item in last_output.content:
                                if hasattr(item, "text"):
                                    content = item.text
                                if hasattr(item, "annotations"):
                                    annotations = item.annotations

                    latency_ms = int(elapsed * 1000)

                    # Extract usage
                    input_tokens = 0
                    output_tokens = 0
                    if hasattr(result, "usage") and result.usage:
                        input_tokens = getattr(result.usage, "input_tokens", 0)
                        output_tokens = getattr(result.usage, "output_tokens", 0)

                    return LLMResponse(
                        content=content,
                        model=model,
                        provider=self._provider,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        finish_reason="stop",
                        latency_ms=latency_ms,
                        metadata={
                            "response_id": response_id,
                            "annotations": [
                                {
                                    "title": getattr(a, "title", None),
                                    "url": getattr(a, "url", None),
                                }
                                for a in annotations
                                if hasattr(a, "url")
                            ],
                        },
                    )

                elif status == "failed":
                    error_msg = getattr(result, "error", "Unknown error")
                    raise LLMError(f"Deep research failed: {error_msg}")

                elif status == "cancelled":
                    raise LLMError("Deep research was cancelled")

                # Still in progress (queued, in_progress), continue polling

            # Timeout
            raise LLMError(
                f"Deep research timed out after {max_wait_seconds}s "
                f"(response_id={response_id})"
            )

        except OpenAIRateLimitError as e:
            raise RateLimitError(str(e)) from e

        except APIError as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower():
                raise AuthenticationError(f"OpenAI authentication failed: {error_msg}") from e
            raise LLMError(f"OpenAI API error: {error_msg}") from e

    async def close(self) -> None:
        """Close the client."""
        await self._client.close()
