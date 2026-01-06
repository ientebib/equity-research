"""
Token counting and preflight checking utilities.

Provides accurate token counting for different models and preflight checks
to warn or compress context before sending to LLMs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from er.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# Model context limits (in tokens)
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # OpenAI models
    "gpt-5.2-mini": 128000,
    "gpt-5.2": 128000,
    "o3-mini": 200000,
    "o4-mini": 200000,
    "o4-mini-deep-research-2025-06-26": 200000,

    # Anthropic models
    "claude-sonnet-4-20250514": 200000,
    "claude-opus-4-20250514": 200000,

    # Default fallback
    "default": 128000,
}

# Approximate characters per token (varies by content type)
CHARS_PER_TOKEN_ESTIMATES: dict[str, float] = {
    "code": 3.5,
    "english": 4.0,
    "json": 3.0,
    "mixed": 3.5,
}


def estimate_tokens(text: str, content_type: str = "mixed") -> int:
    """Estimate token count from text length.

    This is a fast approximation. For exact counts, use count_tokens().

    Args:
        text: Text to estimate tokens for.
        content_type: Type of content ("code", "english", "json", "mixed").

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    chars_per_token = CHARS_PER_TOKEN_ESTIMATES.get(content_type, 3.5)
    return int(len(text) / chars_per_token)


def count_tokens(text: str, model: str = "gpt-5.2") -> int:
    """Count tokens for a given text and model.

    Uses tiktoken for OpenAI models and character estimation for others.

    Args:
        text: Text to count tokens for.
        model: Model name to use for tokenization.

    Returns:
        Token count.
    """
    if not text:
        return 0

    # Try tiktoken for OpenAI models
    if "gpt" in model.lower() or model.startswith("o"):
        try:
            import tiktoken
            # Use cl100k_base encoding (GPT-4 style)
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            logger.debug("tiktoken not available, using estimate")
            return estimate_tokens(text, "mixed")
        except Exception as e:
            logger.debug(f"tiktoken error: {e}, using estimate")
            return estimate_tokens(text, "mixed")

    # For Claude models, use character estimation
    # Claude uses a similar BPE tokenizer, ~4 chars per token
    return estimate_tokens(text, "english")


def get_model_limit(model: str) -> int:
    """Get the context limit for a model.

    Args:
        model: Model name.

    Returns:
        Context limit in tokens.
    """
    return MODEL_CONTEXT_LIMITS.get(model, MODEL_CONTEXT_LIMITS["default"])


def preflight_check(
    context: str,
    model: str,
    reserved_output_tokens: int = 10000,
    warn_threshold: float = 0.80,
    compress_threshold: float = 0.85,
) -> tuple[str, list[str]]:
    """Check context size and optionally compress.

    Args:
        context: Context string to check.
        model: Target model.
        reserved_output_tokens: Tokens to reserve for model output.
        warn_threshold: Warn at this fraction of limit (e.g., 0.80 = 80%).
        compress_threshold: Compress at this fraction (e.g., 0.85 = 85%).

    Returns:
        Tuple of (possibly_compressed_context, list_of_warnings).
    """
    warnings: list[str] = []

    if not context:
        return context, warnings

    model_limit = get_model_limit(model)
    available_tokens = model_limit - reserved_output_tokens

    token_count = count_tokens(context, model)
    usage_fraction = token_count / available_tokens

    logger.debug(
        "Preflight check",
        model=model,
        tokens=token_count,
        limit=available_tokens,
        usage_pct=f"{usage_fraction:.1%}",
    )

    # Check thresholds
    if usage_fraction >= compress_threshold:
        # Need to compress
        target_tokens = int(available_tokens * 0.75)  # Target 75% of limit
        compressed = compress_context(context, target_tokens, model)

        new_count = count_tokens(compressed, model)
        warnings.append(
            f"Context compressed from {token_count:,} to {new_count:,} tokens "
            f"({usage_fraction:.0%} -> {new_count/available_tokens:.0%} of limit)"
        )

        logger.warning(
            "Context compressed due to size",
            original_tokens=token_count,
            compressed_tokens=new_count,
            model=model,
        )

        return compressed, warnings

    elif usage_fraction >= warn_threshold:
        # Just warn
        warnings.append(
            f"Context at {usage_fraction:.0%} of limit "
            f"({token_count:,} / {available_tokens:,} tokens) for {model}"
        )

        logger.warning(
            "Context approaching limit",
            tokens=token_count,
            limit=available_tokens,
            usage_pct=f"{usage_fraction:.1%}",
            model=model,
        )

    return context, warnings


def compress_context(
    context: str,
    target_tokens: int,
    model: str,
) -> str:
    """Compress context to fit within target token limit.

    Uses multiple strategies:
    1. Remove redundant whitespace
    2. Truncate from the middle (keep beginning and end)
    3. Summarize sections

    Args:
        context: Context to compress.
        target_tokens: Target token count.
        model: Model for token counting.

    Returns:
        Compressed context.
    """
    # Step 1: Remove redundant whitespace
    import re
    compressed = re.sub(r'\n{3,}', '\n\n', context)
    compressed = re.sub(r' {2,}', ' ', compressed)
    compressed = re.sub(r'\t+', ' ', compressed)

    current_tokens = count_tokens(compressed, model)
    if current_tokens <= target_tokens:
        return compressed

    # Step 2: Truncate from middle (preserve beginning and end)
    # Keep first 60% and last 20% of target
    chars_per_token = 4.0  # Conservative estimate
    target_chars = int(target_tokens * chars_per_token)

    head_chars = int(target_chars * 0.60)
    tail_chars = int(target_chars * 0.20)

    if len(compressed) > target_chars:
        head = compressed[:head_chars]
        tail = compressed[-tail_chars:] if tail_chars > 0 else ""

        # Find natural break points
        head_break = head.rfind('\n\n')
        if head_break > head_chars * 0.8:
            head = head[:head_break]

        tail_break = tail.find('\n\n')
        if tail_break > 0 and tail_break < tail_chars * 0.2:
            tail = tail[tail_break:]

        compressed = (
            head +
            "\n\n[... context truncated to fit token limit ...]\n\n" +
            tail
        )

    return compressed


def check_prompt_fits(
    prompt: str,
    model: str,
    expected_output_tokens: int = 8000,
) -> tuple[bool, int, int]:
    """Check if a prompt fits within model limits.

    Args:
        prompt: The full prompt to check.
        model: Target model.
        expected_output_tokens: Expected output token count.

    Returns:
        Tuple of (fits, prompt_tokens, available_tokens).
    """
    model_limit = get_model_limit(model)
    available = model_limit - expected_output_tokens

    prompt_tokens = count_tokens(prompt, model)
    fits = prompt_tokens <= available

    return fits, prompt_tokens, available
