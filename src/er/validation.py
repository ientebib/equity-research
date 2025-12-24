"""
Message validation for the equity research system.

Validates agent messages to ensure they conform to the protocol.
"""

from __future__ import annotations

from er.types import AgentMessage, MessageType


def validate_message(msg: AgentMessage) -> list[str]:
    """Validate an agent message.

    Args:
        msg: The message to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors: list[str] = []

    # Messages that require confidence
    requires_confidence = {
        MessageType.RESEARCH_COMPLETE,
        MessageType.SYNTHESIS_COMPLETE,
        MessageType.VERDICT,
    }

    if msg.message_type in requires_confidence:
        if msg.confidence is None:
            errors.append(
                f"{msg.message_type.value} messages must have confidence"
            )
        elif not (0.0 <= msg.confidence <= 1.0):
            errors.append(
                f"Confidence must be between 0.0 and 1.0, got {msg.confidence}"
            )

    # RESEARCH_COMPLETE must have evidence
    if msg.message_type == MessageType.RESEARCH_COMPLETE:
        if not msg.evidence_ids:
            errors.append(
                "RESEARCH_COMPLETE messages must have at least one evidence_id"
            )

    # CHALLENGE must have non-empty content
    if msg.message_type == MessageType.CHALLENGE:
        if not msg.content or not msg.content.strip():
            errors.append("CHALLENGE messages must have non-empty content")

    # DEFENSE must reference challenge
    if msg.message_type == MessageType.DEFENSE:
        if "challenge_id" not in msg.context:
            errors.append(
                "DEFENSE messages must reference challenge_id in context"
            )

    # General validation
    if not msg.from_agent:
        errors.append("from_agent is required")

    if not msg.to_agent:
        errors.append("to_agent is required")

    if not msg.run_id:
        errors.append("run_id is required")

    return errors


def is_valid_message(msg: AgentMessage) -> bool:
    """Check if a message is valid.

    Args:
        msg: The message to check.

    Returns:
        True if valid, False otherwise.
    """
    return len(validate_message(msg)) == 0
