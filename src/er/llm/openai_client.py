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

    def __init__(self, api_key: str | None = None, timeout: float = 1800.0) -> None:
        """Initialize the OpenAI client.

        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY env var.
            timeout: Request timeout in seconds (default 30 minutes for long syntheses).
        """
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)
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
        Uses the Responses API which supports the reasoning parameter.

        Args:
            request: The LLM request.
            reasoning_effort: One of "low", "medium", "high".

        Returns:
            LLM response.

        Raises:
            LLMError: If the request fails.
        """
        start_time = time.monotonic()

        try:
            # Build the request parameters for Responses API
            params: dict[str, Any] = {
                "model": request.model,
                "input": request.messages,
            }

            # Add reasoning effort for supported models
            if request.model in REASONING_MODELS:
                params["reasoning"] = {"effort": reasoning_effort}

            if request.max_tokens:
                params["max_output_tokens"] = request.max_tokens

            # Make the API call using Responses API
            response = await self._client.responses.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract content using output_text property
            content = ""
            if hasattr(response, "output_text") and response.output_text:
                content = response.output_text
            else:
                # Fallback: manually iterate through output
                if hasattr(response, "output") and response.output:
                    for item in response.output:
                        if hasattr(item, "content") and item.content:
                            for block in item.content:
                                if hasattr(block, "text"):
                                    content += block.text

            # Extract usage
            input_tokens = 0
            output_tokens = 0
            reasoning_tokens = 0
            if hasattr(response, "usage") and response.usage:
                input_tokens = getattr(response.usage, "input_tokens", 0)
                output_tokens = getattr(response.usage, "output_tokens", 0)
                if hasattr(response.usage, "output_tokens_details"):
                    details = response.usage.output_tokens_details
                    reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0

            return LLMResponse(
                content=content,
                model=response.model if hasattr(response, "model") else request.model,
                provider=self._provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="stop",
                latency_ms=latency_ms,
                metadata={"reasoning_tokens": reasoning_tokens, "reasoning_effort": reasoning_effort},
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

    async def complete_with_web_search(
        self,
        request: LLMRequest,
        reasoning_effort: str = "high",
    ) -> LLMResponse:
        """Send a completion request with web search enabled.

        Uses the Responses API with web_search_preview tool for GPT-5.2.
        The model will automatically search the web when needed.

        Note: This can take several minutes as the model performs web searches.

        Args:
            request: The LLM request.
            reasoning_effort: Reasoning effort level.

        Returns:
            LLM response with web search results incorporated.

        Raises:
            LLMError: If the request fails.
        """
        start_time = time.monotonic()

        try:
            # Use Responses API with web search tool
            # This is similar to deep_research but synchronous (not background)
            params: dict[str, Any] = {
                "model": request.model,
                "input": request.messages,
                "tools": [{"type": "web_search"}],
            }

            # Add reasoning effort for supported models
            if request.model in REASONING_MODELS:
                params["reasoning"] = {"effort": reasoning_effort}

            if request.max_tokens:
                params["max_output_tokens"] = request.max_tokens

            # Calculate approximate prompt size
            prompt_chars = sum(len(str(m.get("content", ""))) for m in request.messages)

            logger.info(
                "Starting web search completion (Responses API - may take several minutes)",
                model=request.model,
                reasoning_effort=reasoning_effort,
                prompt_chars=prompt_chars,
                max_output_tokens=request.max_tokens,
            )

            # Make the synchronous Responses API call
            response = await self._client.responses.create(**params)

            latency_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "Web search completion finished",
                model=request.model,
                latency_seconds=latency_ms / 1000,
            )

            # Debug response structure (only at debug level)
            logger.debug(
                "Web search response structure",
                response_type=type(response).__name__,
                status=getattr(response, "status", "N/A"),
                has_output_text=hasattr(response, "output_text"),
                output_count=len(response.output) if hasattr(response, "output") and response.output else 0,
            )

            # Extract content using output_text property (simpler and more reliable)
            content = ""
            if hasattr(response, "output_text") and response.output_text:
                content = response.output_text
            else:
                # Fallback: manually iterate through output
                if hasattr(response, "output") and response.output:
                    for item in response.output:
                        if hasattr(item, "content") and item.content:
                            for block in item.content:
                                if hasattr(block, "text"):
                                    content += block.text

            logger.debug(
                "Web search content extracted",
                content_length=len(content),
            )

            # Extract usage
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage") and response.usage:
                input_tokens = getattr(response.usage, "input_tokens", 0)
                output_tokens = getattr(response.usage, "output_tokens", 0)

            return LLMResponse(
                content=content,
                model=request.model,
                provider=self._provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="stop",
                latency_ms=latency_ms,
                metadata={"web_search_enabled": True},
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
            tools: list[dict[str, Any]] = [{"type": "web_search"}]
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
                    # Extract the final output - iterate ALL outputs and ALL content blocks
                    content = ""
                    annotations = []

                    # First try output_text property (simpler if available)
                    if hasattr(result, "output_text") and result.output_text:
                        content = result.output_text
                    elif result.output:
                        # Iterate through ALL output items (not just the last one!)
                        for output_item in result.output:
                            if hasattr(output_item, "content") and output_item.content:
                                for block in output_item.content:
                                    # Append text (not overwrite!)
                                    if hasattr(block, "text"):
                                        content += block.text
                                    # Collect annotations from all blocks
                                    if hasattr(block, "annotations"):
                                        annotations.extend(block.annotations)

                    latency_ms = int(elapsed * 1000)

                    # Extract usage
                    input_tokens = 0
                    output_tokens = 0
                    if hasattr(result, "usage") and result.usage:
                        input_tokens = getattr(result.usage, "input_tokens", 0)
                        output_tokens = getattr(result.usage, "output_tokens", 0)

                    logger.debug(
                        "Deep research completed",
                        response_id=response_id,
                        content_length=len(content),
                        annotation_count=len(annotations),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )

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
