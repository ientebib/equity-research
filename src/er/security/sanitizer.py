"""
Input Sanitization for Prompt Injection Defense.

Protects against prompt injection attacks in user-provided content
and external data sources (web fetches, filings, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ThreatLevel(str, Enum):
    """Threat level of detected injection attempt."""

    NONE = "none"
    LOW = "low"  # Suspicious but likely benign
    MEDIUM = "medium"  # Potential injection attempt
    HIGH = "high"  # Clear injection attempt
    CRITICAL = "critical"  # Malicious payload

    @property
    def severity(self) -> int:
        """Return numeric severity for comparison."""
        return {
            ThreatLevel.NONE: 0,
            ThreatLevel.LOW: 1,
            ThreatLevel.MEDIUM: 2,
            ThreatLevel.HIGH: 3,
            ThreatLevel.CRITICAL: 4,
        }[self]


@dataclass
class SanitizationResult:
    """Result of input sanitization."""

    original_length: int
    sanitized_length: int
    sanitized_text: str
    threat_level: ThreatLevel
    threats_detected: list[str] = field(default_factory=list)
    modifications_made: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "original_length": self.original_length,
            "sanitized_length": self.sanitized_length,
            "threat_level": self.threat_level.value,
            "threats_detected": self.threats_detected,
            "modifications_made": self.modifications_made,
        }

    @property
    def is_safe(self) -> bool:
        """Check if input is safe to use."""
        return self.threat_level in (ThreatLevel.NONE, ThreatLevel.LOW)


class InputSanitizer:
    """Sanitizes user and external input for prompt injection defense.

    Protection against:
    1. Prompt injection attempts
    2. Jailbreak patterns
    3. Instruction override attempts
    4. System prompt extraction attempts
    """

    # Patterns indicating injection attempts
    INJECTION_PATTERNS = [
        # Direct instruction override
        (r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions?", ThreatLevel.HIGH),
        (r"disregard\s+(all\s+)?(previous|above|prior)\s+instructions?", ThreatLevel.HIGH),
        (r"forget\s+(everything|all)\s+(you\s+)?know", ThreatLevel.HIGH),

        # Role manipulation
        (r"you\s+are\s+now\s+(?!analyzing|researching|evaluating)", ThreatLevel.MEDIUM),
        (r"pretend\s+(to\s+be|you\s+are)", ThreatLevel.MEDIUM),
        (r"act\s+as\s+(?!an\s+analyst)", ThreatLevel.MEDIUM),
        (r"roleplay\s+as", ThreatLevel.MEDIUM),

        # System prompt extraction
        (r"(print|show|reveal|output)\s+(your\s+)?(system\s+)?prompt", ThreatLevel.HIGH),
        (r"what\s+(are|is)\s+your\s+(instructions?|rules?|guidelines?)", ThreatLevel.MEDIUM),
        (r"repeat\s+(your\s+)?(initial|system|original)\s+prompt", ThreatLevel.HIGH),

        # Jailbreak patterns
        (r"DAN\s+mode", ThreatLevel.CRITICAL),
        (r"developer\s+mode\s+(enabled|on)", ThreatLevel.CRITICAL),
        (r"jailbreak", ThreatLevel.CRITICAL),

        # Code execution attempts
        (r"```\s*(python|bash|javascript|sh)\s*\n.*?(exec|eval|system|subprocess)", ThreatLevel.HIGH),
        (r"os\.(system|popen|exec)", ThreatLevel.CRITICAL),

        # Data exfiltration attempts
        (r"(send|post|transmit)\s+(to|data)\s+https?://", ThreatLevel.HIGH),

        # Markdown/formatting abuse
        (r"\[INST\]", ThreatLevel.MEDIUM),
        (r"<\|im_start\|>", ThreatLevel.MEDIUM),
        (r"<\|system\|>", ThreatLevel.HIGH),
    ]

    # Patterns to sanitize (replace with safe versions)
    SANITIZE_PATTERNS = [
        # Markdown injection
        (r"```\s*system", "```text"),
        (r"\[hidden\].*?\[/hidden\]", "[content removed]"),

        # XML-like injections
        (r"<system>.*?</system>", "[content removed]"),
        (r"<instructions?>.*?</instructions?>", "[content removed]"),
    ]

    def __init__(
        self,
        max_length: int = 100000,
        strict_mode: bool = False,
    ) -> None:
        """Initialize the sanitizer.

        Args:
            max_length: Maximum allowed input length.
            strict_mode: If True, block medium-threat content.
        """
        self.max_length = max_length
        self.strict_mode = strict_mode

    def sanitize(self, text: str, source: str = "unknown") -> SanitizationResult:
        """Sanitize input text.

        Args:
            text: Text to sanitize.
            source: Source of the text (for logging).

        Returns:
            SanitizationResult with sanitized text.
        """
        original_length = len(text)
        threats: list[str] = []
        modifications: list[str] = []
        max_threat = ThreatLevel.NONE

        # Truncate if too long
        if len(text) > self.max_length:
            text = text[:self.max_length]
            modifications.append(f"Truncated to {self.max_length} chars")

        # Check for injection patterns
        for pattern, threat_level in self.INJECTION_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
            if matches:
                threats.append(f"Pattern detected: {pattern[:50]}...")
                if threat_level.severity > max_threat.severity:
                    max_threat = threat_level

        # Apply sanitization patterns
        sanitized = text
        for pattern, replacement in self.SANITIZE_PATTERNS:
            if re.search(pattern, sanitized, re.IGNORECASE | re.DOTALL):
                sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE | re.DOTALL)
                modifications.append(f"Sanitized pattern: {pattern[:30]}...")

        # Escape potential instruction delimiters
        sanitized = self._escape_delimiters(sanitized)

        return SanitizationResult(
            original_length=original_length,
            sanitized_length=len(sanitized),
            sanitized_text=sanitized,
            threat_level=max_threat,
            threats_detected=threats,
            modifications_made=modifications,
        )

    def _escape_delimiters(self, text: str) -> str:
        """Escape common instruction delimiters."""
        # Replace triple backticks that might contain system/instructions
        text = re.sub(
            r"```\s*(system|instructions?|prompt)",
            "```text",
            text,
            flags=re.IGNORECASE,
        )
        return text

    def is_safe_input(self, text: str) -> bool:
        """Quick check if input is safe.

        Args:
            text: Text to check.

        Returns:
            True if safe, False if potentially dangerous.
        """
        result = self.sanitize(text)
        if self.strict_mode:
            return result.threat_level == ThreatLevel.NONE
        return result.is_safe

    def sanitize_batch(
        self,
        texts: list[str],
        source: str = "batch",
    ) -> list[SanitizationResult]:
        """Sanitize multiple texts.

        Args:
            texts: List of texts to sanitize.
            source: Source identifier.

        Returns:
            List of SanitizationResults.
        """
        return [self.sanitize(text, source) for text in texts]


def sanitize_evidence(evidence_text: str) -> str:
    """Sanitize evidence text before including in prompts.

    Convenience function for common use case.

    Args:
        evidence_text: Evidence text from external source.

    Returns:
        Sanitized text safe for prompt inclusion.
    """
    sanitizer = InputSanitizer()
    result = sanitizer.sanitize(evidence_text, source="evidence")

    if result.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL):
        return "[Content blocked due to security concerns]"

    return result.sanitized_text
