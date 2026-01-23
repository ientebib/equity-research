"""
Agent package.

This package implements the research agents for the pipeline:
- AnthropicDiscoveryAgent: Stage 2 - Discovery using Claude Agent SDK with subagents
- VerificationAgent: Stage 3.5 - Fact verification
- IntegratorAgent: Stage 3.75 - Cross-vertical integration
- JudgeAgent: Stage 5 - Editorial review

All agents use Anthropic Claude via the Agent SDK or direct client.
"""

from er.agents.base import Agent, AgentContext
from er.agents.data_orchestrator import DataOrchestratorAgent
from er.agents.discovery_anthropic import AnthropicDiscoveryAgent
from er.agents.integrator import IntegratorAgent
from er.agents.judge import JudgeAgent
from er.agents.verifier import VerificationAgent

__all__ = [
    "Agent",
    "AgentContext",
    "AnthropicDiscoveryAgent",
    "DataOrchestratorAgent",
    "IntegratorAgent",
    "JudgeAgent",
    "VerificationAgent",
]
