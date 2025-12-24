"""
Agent package.

This package implements the research agents for the 5-stage pipeline:
- DataOrchestratorAgent: Stage 1 - Fetch all FMP data, build CompanyContext
- DiscoveryAgent: Stage 2 - Find value drivers with 7 lenses (Gemini Deep Research)
- VerticalAnalystAgent: Stage 3 - Deep dive per vertical (o4-mini-deep-research)
- SynthesizerAgent: Stage 4 - Dual synthesis (Claude + GPT in parallel)
- JudgeAgent: Stage 5 - Compare syntheses, produce final report
"""

from er.agents.base import Agent, AgentContext
from er.agents.data_orchestrator import DataOrchestratorAgent
from er.agents.discovery import DiscoveryAgent
from er.agents.judge import JudgeAgent
from er.agents.synthesizer import SynthesizerAgent
from er.agents.vertical_analyst import VerticalAnalystAgent

__all__ = [
    "Agent",
    "AgentContext",
    "DataOrchestratorAgent",
    "DiscoveryAgent",
    "JudgeAgent",
    "SynthesizerAgent",
    "VerticalAnalystAgent",
]
