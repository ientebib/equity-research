"""
Agent package.

This package implements the research agents for the pipeline:
- DataOrchestratorAgent: Stage 1 - Fetch all FMP data, build CompanyContext
- DiscoveryAgent: Stage 2A - Find value drivers with 7 lenses (GPT-5.2, internal focus)
- ExternalDiscoveryAgent: Stage 2B - Find competitive intel, news, market context (Claude Sonnet)
- DiscoveryMerger: Stage 2C - Merge internal + external discovery outputs
- VerticalAnalystAgent: Stage 3 - Deep dive per vertical (Gemini Deep Research)
- SynthesizerAgent: Stage 4 - Dual synthesis (Claude Opus + GPT-5.2 in parallel)
- JudgeAgent: Stage 5 - Compare syntheses, produce final verdict
"""

from er.agents.base import Agent, AgentContext
from er.agents.data_orchestrator import DataOrchestratorAgent
from er.agents.discovery import DiscoveryAgent
from er.agents.external_discovery import ExternalDiscoveryAgent, ExternalDiscoveryOutput
from er.agents.discovery_merger import DiscoveryMerger
from er.agents.judge import JudgeAgent
from er.agents.synthesizer import SynthesizerAgent
from er.agents.vertical_analyst import VerticalAnalystAgent

__all__ = [
    "Agent",
    "AgentContext",
    "DataOrchestratorAgent",
    "DiscoveryAgent",
    "ExternalDiscoveryAgent",
    "ExternalDiscoveryOutput",
    "DiscoveryMerger",
    "JudgeAgent",
    "SynthesizerAgent",
    "VerticalAnalystAgent",
]
