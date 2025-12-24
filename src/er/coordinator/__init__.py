"""
Coordinator package.

This package implements the research orchestration:
- Event store for message logging
- Phase transitions
- Agent coordination
- Budget management
- 5-stage pipeline
"""

from er.coordinator.event_store import EventStore
from er.coordinator.pipeline import (
    PipelineConfig,
    PipelineResult,
    ResearchPipeline,
    run_research,
)

__all__ = [
    "EventStore",
    "PipelineConfig",
    "PipelineResult",
    "ResearchPipeline",
    "run_research",
]
