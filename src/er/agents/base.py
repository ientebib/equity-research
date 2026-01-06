"""
Base classes for agents.

This module implements:
- Agent: Abstract base class for all agents
- AgentContext: Runtime context with shared resources

Agent types implemented in separate modules:
- data_orchestrator.py: DataOrchestratorAgent for Stage 1
- discovery.py: DiscoveryAgent for Stage 2
- vertical_analyst.py: VerticalAnalystAgent for Stage 3
- synthesizer.py: SynthesizerAgent for Stage 4
- judge.py: JudgeAgent for Stage 5
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from er.budget import BudgetTracker
from er.evidence.store import EvidenceStore
from er.llm.router import LLMRouter
from er.logging import get_logger
from er.workspace.store import WorkspaceStore

if TYPE_CHECKING:
    from er.config import Settings
    from er.types import RunState

logger = get_logger(__name__)


@dataclass
class AgentContext:
    """Runtime context for agents.

    Contains shared resources that all agents need access to.
    """

    settings: Settings
    llm_router: LLMRouter
    evidence_store: EvidenceStore
    budget_tracker: BudgetTracker
    workspace_store: WorkspaceStore | None = None


class Agent(ABC):
    """Abstract base class for research agents.

    All agents in the equity research pipeline inherit from this class.
    Provides common interface and access to shared resources.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize agent with context.

        Args:
            context: Runtime context with shared resources.
        """
        self.context = context
        self._logger = get_logger(f"agent.{self.name}")

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this agent."""
        ...

    @property
    @abstractmethod
    def role(self) -> str:
        """Role description for this agent."""
        ...

    @abstractmethod
    async def run(self, run_state: RunState, **kwargs: Any) -> Any:
        """Execute the agent's main task.

        Args:
            run_state: Current run state.
            **kwargs: Additional arguments specific to the agent type.

        Returns:
            Agent-specific output (varies by agent type).
        """
        ...

    @property
    def llm_router(self) -> LLMRouter:
        """Get the LLM router."""
        return self.context.llm_router

    @property
    def evidence_store(self) -> EvidenceStore:
        """Get the evidence store."""
        return self.context.evidence_store

    @property
    def settings(self) -> Settings:
        """Get settings."""
        return self.context.settings

    @property
    def budget_tracker(self) -> BudgetTracker:
        """Get budget tracker."""
        return self.context.budget_tracker

    @property
    def workspace_store(self) -> WorkspaceStore | None:
        """Get workspace store (may be None if not configured)."""
        return self.context.workspace_store

    def log_info(self, message: str, **kwargs: Any) -> None:
        """Log info message with agent context."""
        self._logger.info(message, agent=self.name, **kwargs)

    def log_warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with agent context."""
        self._logger.warning(message, agent=self.name, **kwargs)

    def log_error(self, message: str, **kwargs: Any) -> None:
        """Log error message with agent context."""
        self._logger.error(message, agent=self.name, **kwargs)
