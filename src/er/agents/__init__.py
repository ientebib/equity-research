"""
Agent package.

This package implements the research agents for the pipeline:
- AnthropicDiscoveryAgent: Stage 2 - Discovery using Claude Agent SDK with subagents
- SynthesizerAgent: Stage 4 - Synthesis with extended thinking
- JudgeAgent: Stage 5 - Verification
"""

from er.agents.base import Agent, AgentContext
from er.agents.data_orchestrator import DataOrchestratorAgent
from er.agents.discovery_anthropic import AnthropicDiscoveryAgent
from er.agents.judge import JudgeAgent
from er.agents.synthesizer import SynthesizerAgent
from er.agents.vertical_analyst import VerticalAnalystAgent

__all__ = [
    "Agent",
    "AgentContext",
    "DataOrchestratorAgent",
    "AnthropicDiscoveryAgent",
    "JudgeAgent",
    "SynthesizerAgent",
    "VerticalAnalystAgent",
]
