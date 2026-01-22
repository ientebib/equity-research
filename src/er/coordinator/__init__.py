"""
Coordinator package.

This package implements the research orchestration:
- Event store for message logging
- Agent research pipeline using Claude Agent SDK
- Multi-agent architecture (Anthropic's pattern)
"""

from er.coordinator.event_store import EventStore
from er.coordinator.anthropic_sdk_agent import (
    ResearchPipeline,
    PipelineResult,
)

__all__ = [
    "EventStore",
    "ResearchPipeline",
    "PipelineResult",
]
