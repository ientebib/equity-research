"""
Tests for the OpenAI client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from er.llm.base import (
    AuthenticationError,
    ContextLengthError,
    LLMRequest,
    ModelNotFoundError,
    RateLimitError,
)
from er.llm.openai_client import OpenAIClient, SUPPORTED_MODELS


class TestOpenAIClientBasic:
    """Test basic OpenAI client functionality."""

    def test_provider_name(self) -> None:
        """Test provider name is correct."""
        with patch("er.llm.openai_client.AsyncOpenAI"):
            client = OpenAIClient(api_key="test-key")
            assert client.provider == "openai"

    def test_supports_gpt5_models(self) -> None:
        """Test that GPT-5.2 models are supported."""
        with patch("er.llm.openai_client.AsyncOpenAI"):
            client = OpenAIClient(api_key="test-key")

            assert client.supports_model("gpt-5.2")
            assert client.supports_model("gpt-5.2-2025-12-11")
            assert client.supports_model("gpt-5.2-mini")

    def test_supports_legacy_models(self) -> None:
        """Test that legacy GPT-4o models are supported."""
        with patch("er.llm.openai_client.AsyncOpenAI"):
            client = OpenAIClient(api_key="test-key")

            assert client.supports_model("gpt-4o")
            assert client.supports_model("gpt-4o-mini")

    def test_supports_reasoning_models(self) -> None:
        """Test that o1/o3 reasoning models are supported."""
        with patch("er.llm.openai_client.AsyncOpenAI"):
            client = OpenAIClient(api_key="test-key")

            assert client.supports_model("o1")
            assert client.supports_model("o1-mini")
            assert client.supports_model("o3-mini")


class TestOpenAIClientComplete:
    """Test OpenAI client complete method."""

    @pytest.mark.asyncio
    async def test_complete_returns_response(self) -> None:
        """Test complete returns a valid LLMResponse."""
        mock_response = MagicMock()
        mock_response.model = "gpt-5.2"
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="Test response", tool_calls=None),
                finish_reason="stop",
            )
        ]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

        with patch("er.llm.openai_client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = OpenAIClient(api_key="test-key")
            request = LLMRequest(
                messages=[{"role": "user", "content": "Hello"}],
                model="gpt-5.2",
            )

            response = await client.complete(request)

            assert response.content == "Test response"
            assert response.model == "gpt-5.2"
            assert response.provider == "openai"
            assert response.input_tokens == 10
            assert response.output_tokens == 20

    @pytest.mark.asyncio
    async def test_complete_with_temperature(self) -> None:
        """Test complete passes temperature correctly."""
        mock_response = MagicMock()
        mock_response.model = "gpt-5.2"
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Response"), finish_reason="stop")
        ]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

        with patch("er.llm.openai_client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_create = AsyncMock(return_value=mock_response)
            mock_client.chat.completions.create = mock_create
            mock_openai.return_value = mock_client

            client = OpenAIClient(api_key="test-key")
            request = LLMRequest(
                messages=[{"role": "user", "content": "Hello"}],
                model="gpt-5.2",
                temperature=0.5,
            )

            await client.complete(request)

            # Verify temperature was passed
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["temperature"] == 0.5


class TestOpenAIClientToolCalling:
    """Test OpenAI client tool calling."""

    @pytest.mark.asyncio
    async def test_complete_with_tools_extracts_calls(self) -> None:
        """Test that tool calls are extracted correctly."""
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"location": "NYC"}'

        mock_response = MagicMock()
        mock_response.model = "gpt-5.2"
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="", tool_calls=[mock_tool_call]),
                finish_reason="tool_calls",
            )
        ]
        mock_response.usage = MagicMock(prompt_tokens=50, completion_tokens=30)

        with patch("er.llm.openai_client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            client = OpenAIClient(api_key="test-key")
            request = LLMRequest(
                messages=[{"role": "user", "content": "What's the weather?"}],
                model="gpt-5.2",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Get weather",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
            )

            response = await client.complete_with_tools(request)

            assert response.tool_calls is not None
            assert len(response.tool_calls) == 1
            assert response.tool_calls[0].id == "call_123"
            assert response.tool_calls[0].name == "get_weather"
            assert response.tool_calls[0].arguments == {"location": "NYC"}


class TestOpenAIClientErrorHandling:
    """Test OpenAI client error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_raises_error(self) -> None:
        """Test rate limit error is properly raised."""
        from openai import RateLimitError as OpenAIRateLimitError

        with patch("er.llm.openai_client.AsyncOpenAI") as mock_openai:
            mock_client = AsyncMock()
            mock_error = OpenAIRateLimitError(
                message="Rate limit exceeded",
                response=MagicMock(headers={}),
                body=None,
            )
            mock_client.chat.completions.create = AsyncMock(side_effect=mock_error)
            mock_openai.return_value = mock_client

            client = OpenAIClient(api_key="test-key")
            request = LLMRequest(
                messages=[{"role": "user", "content": "Hello"}],
                model="gpt-5.2",
            )

            with pytest.raises(RateLimitError):
                await client.complete(request)


class TestSupportedModels:
    """Test supported models list."""

    def test_supported_models_includes_gpt5(self) -> None:
        """Test GPT-5.2 models are in supported list."""
        assert "gpt-5.2" in SUPPORTED_MODELS
        assert "gpt-5.2-2025-12-11" in SUPPORTED_MODELS
        assert "gpt-5.2-mini" in SUPPORTED_MODELS

    def test_supported_models_includes_reasoning(self) -> None:
        """Test reasoning models are in supported list."""
        assert "o1" in SUPPORTED_MODELS
        assert "o1-mini" in SUPPORTED_MODELS
        assert "o3-mini" in SUPPORTED_MODELS
