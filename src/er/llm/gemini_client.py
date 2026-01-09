"""
Google Gemini LLM client implementation.

Supports Gemini 3 family models using the google-genai SDK (Google AI Studio).
Note: This uses the Google AI Studio API, not Vertex AI.
"""

from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types
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

# Supported Gemini models (Gemini 3 family)
SUPPORTED_MODELS = {
    # Gemini 3 family (current generation)
    "gemini-3-pro",
    "gemini-3-flash",
    "gemini-3-ultra",
    # Legacy Gemini 2.5
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    # Legacy Gemini 2 (still supported)
    "gemini-2.0-flash",
    "gemini-2.0-pro",
    # Legacy Gemini 1.5
    "gemini-1.5-pro",
    "gemini-1.5-flash",
}

# Deep Research agent model
DEEP_RESEARCH_AGENT = "deep-research-pro-preview-12-2025"


class GeminiClient:
    """Google Gemini LLM client using google-genai SDK.

    Supports Gemini 3 family with tool calling.
    Uses Google AI Studio API (not Vertex AI).
    """

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Gemini client.

        Args:
            api_key: Google AI Studio API key. If None, uses GEMINI_API_KEY env var.
        """
        # Create client with API key for Google AI Studio
        self._client = genai.Client(api_key=api_key)
        self._provider = "google"

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
        return model in SUPPORTED_MODELS or model.startswith("gemini-")

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[types.Content]]:
        """Convert OpenAI-style messages to Gemini format.

        Args:
            messages: OpenAI-style messages.

        Returns:
            Tuple of (system_instruction, contents).
        """
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # Gemini takes system instruction separately
                if system_instruction:
                    system_instruction += f"\n\n{content}"
                else:
                    system_instruction = content
            elif role == "assistant":
                contents.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=content)],
                    )
                )
            elif role == "tool":
                # Tool result - add as function response
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=msg.get("name", "function"),
                                response={"result": content},
                            )
                        ],
                    )
                )
            else:
                # user message
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=content)],
                    )
                )

        return system_instruction, contents

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[types.Tool]:
        """Convert OpenAI-style tools to Gemini format.

        Args:
            tools: OpenAI-style tool definitions.

        Returns:
            Gemini-style tool definitions.
        """
        function_declarations = []

        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                # Convert JSON schema parameters to Gemini format
                params = func.get("parameters", {})

                function_declarations.append(
                    types.FunctionDeclaration(
                        name=func.get("name", ""),
                        description=func.get("description", ""),
                        parameters=params,
                    )
                )

        return [types.Tool(function_declarations=function_declarations)]

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
            system_instruction, contents = self._convert_messages(request.messages)

            # Build generation config
            config = types.GenerateContentConfig(
                temperature=request.temperature,
                max_output_tokens=request.max_tokens,
                stop_sequences=request.stop,
            )

            if request.response_format and request.response_format.get("type") == "json_object":
                config.response_mime_type = "application/json"

            if system_instruction:
                config.system_instruction = system_instruction

            # Make the API call
            response = await self._client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract text content
            content = ""
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        content += part.text

            # Get token counts
            input_tokens = 0
            output_tokens = 0
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            # Determine finish reason
            finish_reason = "stop"
            if response.candidates:
                reason = response.candidates[0].finish_reason
                if reason:
                    finish_reason = str(reason).lower()

            grounding_chunks: list[dict[str, Any]] = []
            if response.candidates:
                candidate = response.candidates[0]
                grounding_metadata = getattr(candidate, "grounding_metadata", None)
                chunks = getattr(grounding_metadata, "grounding_chunks", None) if grounding_metadata else None
                if chunks:
                    for chunk in chunks:
                        web = getattr(chunk, "web", None)
                        if not web:
                            continue
                        url = getattr(web, "uri", None) or getattr(web, "url", None) or ""
                        title = getattr(web, "title", None) or ""
                        snippet = getattr(web, "snippet", None) or ""
                        grounding_chunks.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                        })

            return LLMResponse(
                content=content,
                model=request.model,
                provider=self._provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                metadata={"grounding_chunks": grounding_chunks},
            )

        except Exception as e:
            error_msg = str(e)

            if "429" in error_msg or "rate" in error_msg.lower():
                logger.warning("Gemini rate limit hit", model=request.model)
                raise RateLimitError(f"Gemini rate limit: {error_msg}") from e

            if "401" in error_msg or "403" in error_msg or "api key" in error_msg.lower():
                raise AuthenticationError(f"Gemini authentication failed: {error_msg}") from e

            if "not found" in error_msg.lower() or "invalid model" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context" in error_msg.lower() or "too long" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"Gemini API error: {error_msg}") from e

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
            system_instruction, contents = self._convert_messages(request.messages)
            tools = self._convert_tools(request.tools)

            # Build generation config
            config = types.GenerateContentConfig(
                temperature=request.temperature,
                max_output_tokens=request.max_tokens,
                stop_sequences=request.stop,
                tools=tools,
            )

            if request.response_format and request.response_format.get("type") == "json_object":
                config.response_mime_type = "application/json"

            if system_instruction:
                config.system_instruction = system_instruction

            # Handle tool choice
            if request.tool_choice:
                if request.tool_choice == "auto":
                    config.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="AUTO")
                    )
                elif request.tool_choice == "none":
                    config.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="NONE")
                    )
                else:
                    # Specific tool - force that tool
                    config.tool_config = types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY",
                            allowed_function_names=[request.tool_choice],
                        )
                    )

            # Make the API call
            response = await self._client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract content and tool calls
            content = ""
            tool_calls: list[ToolCall] = []

            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        content += part.text
                    elif part.function_call:
                        # Extract function call
                        fc = part.function_call
                        tool_calls.append(
                            ToolCall(
                                id=f"call_{fc.name}_{int(time.time() * 1000)}",
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {},
                            )
                        )

            # Get token counts
            input_tokens = 0
            output_tokens = 0
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            # Determine finish reason
            finish_reason = "stop"
            if response.candidates:
                reason = response.candidates[0].finish_reason
                if reason:
                    finish_reason = str(reason).lower()

            return LLMResponse(
                content=content,
                model=request.model,
                provider=self._provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=tool_calls if tool_calls else None,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
            )

        except Exception as e:
            error_msg = str(e)

            if "429" in error_msg or "rate" in error_msg.lower():
                logger.warning("Gemini rate limit hit", model=request.model)
                raise RateLimitError(f"Gemini rate limit: {error_msg}") from e

            if "401" in error_msg or "403" in error_msg or "api key" in error_msg.lower():
                raise AuthenticationError(f"Gemini authentication failed: {error_msg}") from e

            if "not found" in error_msg.lower() or "invalid model" in error_msg.lower():
                raise ModelNotFoundError(f"Model not found: {request.model}") from e

            if "context" in error_msg.lower() or "too long" in error_msg.lower():
                raise ContextLengthError(f"Context length exceeded: {error_msg}") from e

            raise LLMError(f"Gemini API error: {error_msg}") from e

    async def complete_with_grounding(
        self,
        request: LLMRequest,
        enable_google_search: bool = True,
    ) -> LLMResponse:
        """Send a completion request with Google Search grounding.

        Uses Grounding with Google Search for real-time web information.

        Args:
            request: The LLM request.
            enable_google_search: Whether to enable Google Search grounding.

        Returns:
            LLM response with grounded information.
        """
        start_time = time.monotonic()

        try:
            # Convert messages
            system_instruction, contents = self._convert_messages(request.messages)

            # Build generation config with Google Search grounding
            tools = []

            if enable_google_search:
                # Add Google Search grounding tool
                grounding_tool = types.Tool(google_search=types.GoogleSearch())
                tools.append(grounding_tool)

            # Add any user-provided tools
            if request.tools:
                tools.extend(self._convert_tools(request.tools))

            config = types.GenerateContentConfig(
                temperature=request.temperature,
                max_output_tokens=request.max_tokens,
                stop_sequences=request.stop,
                tools=tools if tools else None,
            )

            if (
                request.response_format
                and request.response_format.get("type") == "json_object"
                and not enable_google_search
            ):
                config.response_mime_type = "application/json"

            if system_instruction:
                config.system_instruction = system_instruction

            # Make the API call
            response = await self._client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Extract text content
            content = ""
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        content += part.text

            # Get token counts
            input_tokens = 0
            output_tokens = 0
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            # Determine finish reason
            finish_reason = "stop"
            if response.candidates:
                reason = response.candidates[0].finish_reason
                if reason:
                    finish_reason = str(reason).lower()

            metadata: dict[str, Any] | None = None
            if response.candidates and getattr(response.candidates[0], "grounding_metadata", None):
                gm = response.candidates[0].grounding_metadata
                metadata = {}
                chunks = []
                for chunk in gm.grounding_chunks or []:
                    entry: dict[str, Any] = {}
                    if chunk.web:
                        entry["title"] = chunk.web.title or ""
                        entry["url"] = chunk.web.uri or ""
                        entry["source"] = chunk.web.domain or ""
                    if chunk.retrieved_context:
                        if not entry.get("title"):
                            entry["title"] = chunk.retrieved_context.title or chunk.retrieved_context.document_name or ""
                        if not entry.get("url"):
                            entry["url"] = chunk.retrieved_context.uri or ""
                        if chunk.retrieved_context.text:
                            entry["snippet"] = chunk.retrieved_context.text
                    if entry.get("url") or entry.get("title"):
                        chunks.append(entry)
                if chunks:
                    metadata["grounding_chunks"] = chunks
                if gm.web_search_queries:
                    metadata["web_search_queries"] = list(gm.web_search_queries)

            return LLMResponse(
                content=content,
                model=request.model,
                provider=self._provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                metadata=metadata,
            )

        except Exception as e:
            error_msg = str(e)

            if "429" in error_msg or "rate" in error_msg.lower():
                logger.warning("Gemini rate limit hit", model=request.model)
                raise RateLimitError(f"Gemini rate limit: {error_msg}") from e

            if "401" in error_msg or "403" in error_msg or "api key" in error_msg.lower():
                raise AuthenticationError(f"Gemini authentication failed: {error_msg}") from e

            raise LLMError(f"Gemini API error: {error_msg}") from e

    async def deep_research(
        self,
        query: str,
        poll_interval: float = 10.0,
        max_wait_seconds: float = 600.0,
    ) -> LLMResponse:
        """Run Deep Research agent for multi-step research tasks.

        Uses the Interactions API to run the Deep Research agent which
        performs iterative search, reading, and synthesis.

        Args:
            query: The research query/prompt.
            poll_interval: Seconds between status checks.
            max_wait_seconds: Maximum time to wait for completion.

        Returns:
            LLM response with research results.

        Raises:
            LLMError: If the research fails or times out.
        """
        import asyncio

        start_time = time.monotonic()

        logger.info(
            "Starting Deep Research",
            query=query[:100] + "..." if len(query) > 100 else query,
        )

        try:
            # Create the interaction
            interaction = await self._client.aio.interactions.create(
                input=query,
                agent=DEEP_RESEARCH_AGENT,
                background=True,
            )

            logger.info("Deep Research started", interaction_id=interaction.id)

            # Poll for completion
            elapsed = 0.0
            while elapsed < max_wait_seconds:
                interaction = await self._client.aio.interactions.get(interaction.id)

                if interaction.status == "completed":
                    latency_ms = int((time.monotonic() - start_time) * 1000)

                    # Extract the final output
                    content = ""
                    if interaction.outputs:
                        # Log all outputs for debugging
                        logger.debug(
                            "Deep Research outputs",
                            interaction_id=interaction.id,
                            output_count=len(interaction.outputs),
                            output_types=[type(o).__name__ for o in interaction.outputs],
                        )
                        # Get the last text output
                        for output in reversed(interaction.outputs):
                            if hasattr(output, 'text') and output.text:
                                content = output.text
                                break

                        # If no text found, log what we got
                        if not content:
                            logger.warning(
                                "Deep Research completed but no text output found",
                                interaction_id=interaction.id,
                                outputs=str(interaction.outputs)[:500],
                            )

                    logger.info(
                        "Deep Research completed",
                        interaction_id=interaction.id,
                        latency_ms=latency_ms,
                        output_length=len(content),
                    )

                    return LLMResponse(
                        content=content,
                        model=DEEP_RESEARCH_AGENT,
                        provider=self._provider,
                        input_tokens=0,  # Not provided by Interactions API
                        output_tokens=len(content) // 4,  # Estimate
                        finish_reason="stop",
                        latency_ms=latency_ms,
                    )

                elif interaction.status == "failed":
                    error_msg = str(interaction.error) if interaction.error else "Unknown error"
                    logger.error(
                        "Deep Research failed",
                        interaction_id=interaction.id,
                        error=error_msg,
                    )
                    raise LLMError(f"Deep Research failed: {error_msg}")

                # Still running, wait and poll again
                await asyncio.sleep(poll_interval)
                elapsed = time.monotonic() - start_time

            # Timeout
            logger.error(
                "Deep Research timed out",
                interaction_id=interaction.id,
                elapsed_seconds=elapsed,
            )
            raise LLMError(
                f"Deep Research timed out after {max_wait_seconds}s",
            )

        except LLMError:
            raise
        except Exception as e:
            error_msg = str(e)

            if "429" in error_msg or "rate" in error_msg.lower():
                raise RateLimitError(f"Gemini rate limit: {error_msg}") from e

            if "401" in error_msg or "403" in error_msg or "api key" in error_msg.lower():
                raise AuthenticationError(f"Gemini authentication failed: {error_msg}") from e

            raise LLMError(f"Deep Research error: {error_msg}") from e

    async def close(self) -> None:
        """Close the client.

        Note: google-genai client doesn't require explicit close.
        """
        pass
