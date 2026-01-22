"""
6-Stage Pipeline Coordinator with Editorial Review.

Orchestrates the complete equity research pipeline:
1. Data Orchestrator - Fetch FMP data, build CompanyContext
2. Discovery - Find value drivers with 7 lenses (GPT-5.2 with web search)
3. Deep Research - 2 parallel research groups (Gemini Deep Research)
4. Dual Synthesis - Claude Opus + GPT-5.2 synthesize in parallel
5. Editorial Review - Judge compares reports, generates feedback (Claude Opus)
6. Revision - Winning synthesizer revises based on feedback
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


class ProgressCallback(Protocol):
    """Protocol for progress callbacks."""

    def __call__(
        self,
        stage: float,
        stage_name: str,
        status: str,
        detail: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """Called when pipeline progress changes.

        Args:
            stage: Stage number (1-6).
            stage_name: Human-readable stage name.
            status: "starting", "running", "complete", "error".
            detail: Additional detail about what's happening.
            cost_usd: Current total cost.
        """
        ...

from er.agents.base import AgentContext
from er.agents.data_orchestrator import DataOrchestratorAgent
from er.agents.discovery import DiscoveryAgent
from er.agents.external_discovery import ExternalDiscoveryAgent, ExternalDiscoveryOutput
from er.agents.discovery_merger import DiscoveryMerger
from er.agents.coverage_auditor import CoverageAuditor
from er.agents.recency_guard import RecencyGuardAgent
from er.agents.integrator import IntegratorAgent
from er.agents.judge import JudgeAgent
from er.agents.synthesizer import SynthesizerAgent
from er.agents.verifier import VerificationAgent
from er.agents.vertical_analyst import VerticalAnalystAgent
from er.budget import BudgetTracker
from er.config import Settings
from er.coordinator.event_store import EventStore
from er.evidence.store import EvidenceStore
from er.exceptions import PipelinePaused
from er.llm.router import LLMRouter
from er.logging import get_logger, log_context, set_run_id, set_phase
from er.workspace.store import WorkspaceStore
from er.types import (
    CompanyContext,
    CoverageAction,
    CoverageScorecard,
    CrossVerticalMap,
    DiscoveryOutput,
    EditorialFeedback,
    GroupResearchOutput,
    Phase,
    ResearchGroup,
    RecencyGuardOutput,
    RunState,
    SynthesisOutput,
    VerifiedResearchPackage,
    VerticalAnalysis,
)

# Valuation and report modules
from er.valuation.assumption_builder import AssumptionBuilder
from er.valuation.dcf import DCFEngine, DCFInputs, WACCInputs, DCFResult
from er.valuation.reverse_dcf import ReverseDCFEngine, ReverseDCFInputs, ReverseDCFResult
from er.valuation.excel_export import ValuationExporter, ValuationWorkbook
from er.reports.compiler import ReportCompiler, CompiledReport
from er.peers.selector import PeerSelector, PeerGroup, create_default_peer_database

logger = get_logger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the research pipeline."""

    # Output
    output_dir: Path | None = None  # Directory for run artifacts and evidence cache

    # Resume from checkpoint
    resume_from_run_dir: Path | None = None  # Resume from a previous run's output directory

    # Stage 1: Data
    include_transcripts: bool = True
    num_transcript_quarters: int = 4
    manual_transcripts: list[dict] | None = None  # User-provided transcripts

    # Stage 2: Discovery
    use_web_search_discovery: bool = True
    use_dual_discovery: bool = True  # Run Internal + External discovery in parallel
    external_discovery_modes: tuple[str, ...] = ("light", "anchored")
    external_discovery_extra_queries: int = 6
    external_discovery_max_queries: int = 25
    external_discovery_overrides: dict[str, list[str]] | None = None
    external_discovery_override_mode: str = "append"

    # Stage 3: Verticals
    max_parallel_verticals: int = 5
    use_deep_research_verticals: bool = True
    max_verticals: int | None = None  # None = use all discovered

    # Stage 4, 5, 6: Synthesis, Editorial Review, Revision
    # (no config needed - always uses extended thinking)

    # Budget
    max_budget_usd: float | None = None  # None = no limit

    # Human-in-the-loop pause
    pause_after_stage: float | None = None  # e.g., 2.0 to pause after discovery


@dataclass
class PipelineResult:
    """Complete result from the pipeline."""

    ticker: str
    company_name: str

    # Stage outputs
    company_context: CompanyContext
    discovery_output: DiscoveryOutput
    group_research_outputs: list[GroupResearchOutput]  # 2 parallel groups
    vertical_analyses: list[VerticalAnalysis]  # Flattened from groups
    claude_synthesis: SynthesisOutput
    gpt_synthesis: SynthesisOutput

    # Editorial flow outputs
    editorial_feedback: EditorialFeedback  # Judge's editorial review
    final_report: SynthesisOutput  # Revised synthesis (the actual deliverable)

    # Run metadata
    run_state: RunState = field(default=None)
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_report_markdown(self) -> str:
        """Generate the final equity research report with metadata header.

        Returns the synthesizer's full report with a metadata header prepended.
        """
        final = self.final_report
        feedback = self.editorial_feedback

        # Build metadata header
        header = f"""---
**EQUITY RESEARCH REPORT**

| Metric | Value |
|--------|-------|
| Ticker | {self.ticker} |
| Company | {self.company_name} |
| Investment View | {final.investment_view} |
| Conviction | {final.conviction} |
| Confidence | {final.overall_confidence:.0%} |
| Preferred Synthesis | {feedback.preferred_synthesis} |
| Claude Score | {feedback.claude_score:.2f} |
| GPT Score | {feedback.gpt_score:.2f} |
| Run ID | {self.run_state.run_id if self.run_state else 'N/A'} |
| Started | {self.started_at.strftime("%Y-%m-%d %H:%M UTC")} |
| Completed | {self.completed_at.strftime("%Y-%m-%d %H:%M UTC")} |
| Duration | {self.duration_seconds:.0f}s |
| Total Cost | ${self.total_cost_usd:.2f} |
| Verticals | {len(self.vertical_analyses)} |
| Research Groups | {len(self.group_research_outputs)} |

---

"""
        # Return header + the synthesizer's full report
        return header + final.full_report


class ResearchPipeline:
    """8-stage equity research pipeline coordinator."""

    # Stage definitions for progress tracking
    STAGES = {
        1: "Data Collection",
        2: "Discovery",
        3: "Deep Research",
        3.5: "Verification",
        3.75: "Integration",
        4: "Dual Synthesis",
        5: "Editorial Review",
        6: "Revision",
    }

    def __init__(
        self,
        settings: Settings | None = None,
        config: PipelineConfig | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            settings: Application settings (loads from env if None).
            config: Pipeline configuration.
            progress_callback: Optional callback for progress updates.
        """
        self.settings = settings or Settings()
        self.config = config or PipelineConfig()
        self._progress_callback = progress_callback

        # Determine cache directory for evidence store
        cache_dir = self.config.output_dir / "evidence" if self.config.output_dir else Path("output/evidence")
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize shared resources
        self.evidence_store = EvidenceStore(cache_dir=cache_dir)
        self.budget_tracker = BudgetTracker(
            budget_limit=self.config.max_budget_usd or 1000.0,  # Default to $1000 if not set
            output_dir=self.config.output_dir,
        )
        self.llm_router = LLMRouter(settings=self.settings)

        # Event store for audit trail (initialized in run())
        self.event_store: EventStore | None = None

        # Workspace store (initialized per run in run())
        self.workspace_store: WorkspaceStore | None = None

        # Create agent context (workspace_store added in run())
        self.agent_context = AgentContext(
            settings=self.settings,
            llm_router=self.llm_router,
            evidence_store=self.evidence_store,
            budget_tracker=self.budget_tracker,
            workspace_store=None,  # Set per-run
        )

        # Initialize agents
        self._data_orchestrator: DataOrchestratorAgent | None = None
        self._discovery_agent: DiscoveryAgent | None = None
        self._external_discovery_agents: dict[str, ExternalDiscoveryAgent] | None = None
        self._discovery_merger: DiscoveryMerger | None = None
        self._coverage_auditor: CoverageAuditor | None = None
        self._recency_guard: RecencyGuardAgent | None = None
        self._verifier: VerificationAgent | None = None
        self._integrator: IntegratorAgent | None = None
        self._synthesizer: SynthesizerAgent | None = None
        self._judge: JudgeAgent | None = None

    def _save_stage_output(self, stage: str, data: Any) -> None:
        """Save stage output to JSON file for debugging and resume capability.

        Args:
            stage: Stage name (e.g., "stage1_company_context", "stage2_discovery").
            data: Data to save (dataclass or dict).
        """
        if not self.config.output_dir:
            return

        output_path = self.config.output_dir / f"{stage}.json"

        try:
            # Convert dataclass to dict if needed
            if hasattr(data, "__dataclass_fields__"):
                # Custom serialization for dataclasses with complex types
                data_dict = self._serialize_dataclass(data)
            elif isinstance(data, list):
                data_dict = [
                    self._serialize_dataclass(item) if hasattr(item, "__dataclass_fields__") else item
                    for item in data
                ]
            else:
                data_dict = data

            output_path.write_text(json.dumps(data_dict, indent=2, default=str))
            logger.info(f"Saved {stage} output", path=str(output_path), size_kb=output_path.stat().st_size / 1024)
        except Exception as e:
            logger.warning(f"Failed to save {stage} output", error=str(e))

    def _serialize_dataclass(self, obj: Any) -> dict:
        """Recursively serialize a dataclass to a JSON-safe dict."""
        if not hasattr(obj, "__dataclass_fields__"):
            return obj

        result = {}
        for field_name, field_type in obj.__dataclass_fields__.items():
            value = getattr(obj, field_name)
            if value is None:
                result[field_name] = None
            elif hasattr(value, "__dataclass_fields__"):
                result[field_name] = self._serialize_dataclass(value)
            elif isinstance(value, list):
                result[field_name] = [
                    self._serialize_dataclass(item) if hasattr(item, "__dataclass_fields__") else item
                    for item in value
                ]
            elif isinstance(value, dict):
                result[field_name] = {
                    k: self._serialize_dataclass(v) if hasattr(v, "__dataclass_fields__") else v
                    for k, v in value.items()
                }
            elif isinstance(value, datetime):
                result[field_name] = value.isoformat()
            elif hasattr(value, "value"):  # Enum
                result[field_name] = value.value
            else:
                result[field_name] = value
        return result

    def _load_checkpoint(self, stage: str) -> Any | None:
        """Load a stage checkpoint from JSON file.

        Args:
            stage: Stage name (e.g., "stage1_company_context").

        Returns:
            Loaded data as dict/list, or None if not found.
        """
        checkpoint_dir = self.config.resume_from_run_dir
        if not checkpoint_dir:
            return None

        checkpoint_path = checkpoint_dir / f"{stage}.json"
        if not checkpoint_path.exists():
            logger.debug(f"No checkpoint found for {stage}", path=str(checkpoint_path))
            return None

        try:
            data = json.loads(checkpoint_path.read_text())
            logger.info(f"Loaded checkpoint for {stage}", path=str(checkpoint_path))
            return data
        except Exception as e:
            logger.warning(f"Failed to load checkpoint for {stage}", error=str(e))
            return None

    def _load_company_context(self) -> CompanyContext | None:
        """Load CompanyContext from checkpoint."""
        data = self._load_checkpoint("stage1_company_context")
        if not data:
            return None
        return CompanyContext.from_dict(data)

    def _load_discovery_output(self) -> DiscoveryOutput | None:
        """Load DiscoveryOutput from checkpoint."""
        data = self._load_checkpoint("stage2_discovery_review")
        if not data:
            data = self._load_checkpoint("stage2_discovery")
        if not data:
            return None

        # Convert nested dicts to proper types
        from er.types import DiscoveredThread, ResearchGroup, ThreadType, ThreadBrief

        threads = []
        for t in data.get("research_threads", []):
            # Convert thread_type string to enum
            thread_type_str = t.get("thread_type", "segment")
            if isinstance(thread_type_str, str):
                t["thread_type"] = ThreadType(thread_type_str)
            # Convert tuple fields from lists
            if "research_questions" in t and isinstance(t["research_questions"], list):
                t["research_questions"] = tuple(t["research_questions"])
            if "evidence_ids" in t and isinstance(t["evidence_ids"], list):
                t["evidence_ids"] = tuple(t["evidence_ids"])
            threads.append(DiscoveredThread(**t))

        groups = []
        for g in data.get("research_groups", []):
            groups.append(ResearchGroup(**g))

        # Restore thread_briefs
        thread_briefs = []
        for tb in data.get("thread_briefs", []):
            if isinstance(tb, dict):
                thread_briefs.append(ThreadBrief(
                    thread_id=tb.get("thread_id", ""),
                    rationale=tb.get("rationale", ""),
                    hypotheses=tb.get("hypotheses", []),
                    key_questions=tb.get("key_questions", []),
                    required_evidence=tb.get("required_evidence", []),
                    key_evidence_ids=tb.get("key_evidence_ids", []),
                    recent_developments=tb.get("recent_developments", []),
                    recency_questions=tb.get("recency_questions", []),
                    recency_evidence_ids=tb.get("recency_evidence_ids", []),
                    confidence=tb.get("confidence", 0.5),
                ))

        return DiscoveryOutput(
            official_segments=data.get("official_segments", []),
            research_threads=threads,
            research_groups=groups,
            cross_cutting_themes=data.get("cross_cutting_themes", []),
            optionality_candidates=data.get("optionality_candidates", []),
            data_gaps=data.get("data_gaps", []),
            conflicting_signals=data.get("conflicting_signals", []),
            evidence_ids=data.get("evidence_ids", []),
            thread_briefs=thread_briefs,
            searches_performed=data.get("searches_performed", []),
        )

    def _load_vertical_analyses(self) -> tuple[list[GroupResearchOutput], list[VerticalAnalysis]] | None:
        """Load Stage 3 outputs from checkpoint."""
        group_data = self._load_checkpoint("stage3_group_research")
        vertical_data = self._load_checkpoint("stage3_verticals")

        if not group_data or not vertical_data:
            return None

        # Convert group research outputs
        groups = []
        for g in group_data:
            # Convert vertical analyses within each group using from_dict
            vas = []
            for v in g.get("vertical_analyses", []):
                if isinstance(v, dict):
                    vas.append(VerticalAnalysis.from_dict(v))
                elif isinstance(v, VerticalAnalysis):
                    vas.append(v)
            g["vertical_analyses"] = vas
            groups.append(GroupResearchOutput(**g))

        # Convert standalone vertical analyses using from_dict
        verticals = []
        for v in vertical_data:
            if isinstance(v, dict):
                verticals.append(VerticalAnalysis.from_dict(v))
            elif isinstance(v, VerticalAnalysis):
                verticals.append(v)

        return groups, verticals

    def _load_synthesis_outputs(self) -> tuple[SynthesisOutput, SynthesisOutput] | None:
        """Load Stage 4 synthesis outputs from checkpoint."""
        claude_data = self._load_checkpoint("stage4_claude_synthesis")
        gpt_data = self._load_checkpoint("stage4_gpt_synthesis")

        if not claude_data or not gpt_data:
            return None

        return SynthesisOutput(**claude_data), SynthesisOutput(**gpt_data)

    def _load_editorial_feedback(self) -> EditorialFeedback | None:
        """Load Stage 5 editorial feedback from checkpoint."""
        data = self._load_checkpoint("stage5_editorial_feedback")
        if not data:
            return None

        from er.types import InsightToIncorporate, ErrorToFix, GapToAddress

        # Convert nested types
        incorporate = [InsightToIncorporate(**i) for i in data.get("incorporate_from_other", [])]
        errors = [ErrorToFix(**e) for e in data.get("errors_to_fix", [])]
        gaps = [GapToAddress(**g) for g in data.get("gaps_to_address", [])]

        return EditorialFeedback(
            preferred_synthesis=data.get("preferred_synthesis", "claude"),
            preference_reasoning=data.get("preference_reasoning", ""),
            rejection_reason=data.get("rejection_reason"),  # None if not reject_both
            claude_score=data.get("claude_score", 0.5),
            gpt_score=data.get("gpt_score", 0.5),
            key_differentiators=data.get("key_differentiators", []),
            incorporate_from_other=incorporate,
            errors_to_fix=errors,
            gaps_to_address=gaps,
            revision_instructions=data.get("revision_instructions", ""),
            current_confidence=data.get("current_confidence", 0.5),
            recommended_confidence=data.get("recommended_confidence", 0.5),
            confidence_reasoning=data.get("confidence_reasoning", ""),
            analysis_quality=data.get("analysis_quality", "medium"),
            key_strengths=data.get("key_strengths", []),
            key_weaknesses=data.get("key_weaknesses", []),
        )

    def _get_completed_stages(self) -> set[float]:
        """Determine which stages have completed checkpoints.

        Returns a set of stage numbers (int or float) that have completed.
        Float stages like 3.5 and 3.75 are supported.
        """
        if not self.config.resume_from_run_dir:
            return set()

        completed: set[float] = set()
        stage_files = {
            1: "stage1_company_context.json",
            2: "stage2_discovery.json",
            3: "stage3_verticals.json",  # Need both stage3 files
            3.5: "stage3_5_verification.json",
            3.75: "stage3_75_integration.json",
            4: "stage4_claude_synthesis.json",  # Need both stage4 files
            5: "stage5_editorial_feedback.json",
            6: "stage6_final_report.json",
        }

        # Check stage 3 (needs both files)
        stage3_group = self.config.resume_from_run_dir / "stage3_group_research.json"
        stage3_vert = self.config.resume_from_run_dir / "stage3_verticals.json"

        # Check stage 4 (needs both files)
        stage4_claude = self.config.resume_from_run_dir / "stage4_claude_synthesis.json"
        stage4_gpt = self.config.resume_from_run_dir / "stage4_gpt_synthesis.json"

        for stage, filename in stage_files.items():
            if stage == 3:
                if stage3_group.exists() and stage3_vert.exists():
                    completed.add(3)
            elif stage == 4:
                if stage4_claude.exists() and stage4_gpt.exists():
                    completed.add(4)
            else:
                if (self.config.resume_from_run_dir / filename).exists():
                    completed.add(stage)

        return completed

    def _load_verification_output(self) -> VerifiedResearchPackage | None:
        """Load Stage 3.5 verification output from checkpoint."""
        data = self._load_checkpoint("stage3_5_verification")
        if not data:
            return None

        from er.types import (
            VerifiedFact, VerificationResult, VerificationStatus, Fact, FactCategory
        )

        # Reconstruct verification results
        verification_results = []
        for vr in data.get("verification_results", []):
            verified_facts = []
            for vf_data in vr.get("verified_facts", []):
                # Reconstruct original fact
                orig_fact_data = vf_data.get("original_fact", {})
                original_fact = Fact(
                    fact_id=orig_fact_data.get("fact_id", ""),
                    statement=orig_fact_data.get("statement", ""),
                    category=FactCategory(orig_fact_data.get("category", "other")),
                    evidence_id=orig_fact_data.get("evidence_id", ""),
                    evidence_ids=orig_fact_data.get("evidence_ids", []) or ([orig_fact_data.get("evidence_id")] if orig_fact_data.get("evidence_id") else []),
                    source=orig_fact_data.get("source", ""),
                    source_date=orig_fact_data.get("source_date"),
                    confidence=orig_fact_data.get("confidence", 0.5),
                    vertical_id=orig_fact_data.get("vertical_id"),
                )
                verified_facts.append(VerifiedFact(
                    original_fact=original_fact,
                    status=VerificationStatus(vf_data.get("status", "unverifiable")),
                    verification_notes=vf_data.get("verification_notes", ""),
                    ground_truth_source=vf_data.get("ground_truth_source"),
                    confidence_adjustment=vf_data.get("confidence_adjustment", 0.0),
                ))
            verification_results.append(VerificationResult(
                vertical_name=vr.get("vertical_name", ""),
                thread_id=vr.get("thread_id", ""),
                verified_facts=verified_facts,
                verified_count=vr.get("verified_count", 0),
                contradicted_count=vr.get("contradicted_count", 0),
                unverifiable_count=vr.get("unverifiable_count", 0),
                critical_contradictions=vr.get("critical_contradictions", []),
            ))

        # Reconstruct all_verified_facts
        all_verified_facts = []
        for vr in verification_results:
            all_verified_facts.extend(vr.verified_facts)

        return VerifiedResearchPackage(
            ticker=data.get("ticker", ""),
            verification_results=verification_results,
            all_verified_facts=all_verified_facts,
            total_facts=data.get("total_facts", 0),
            verified_count=data.get("verified_count", 0),
            contradicted_count=data.get("contradicted_count", 0),
            unverifiable_count=data.get("unverifiable_count", 0),
            critical_issues=data.get("critical_issues", []),
            evidence_ids=data.get("evidence_ids", []),
        )

    def _load_integration_output(self) -> CrossVerticalMap | None:
        """Load Stage 3.75 integration output from checkpoint."""
        data = self._load_checkpoint("stage3_75_integration")
        if not data:
            return None

        from er.types import (
            VerticalRelationship, SharedRisk, CrossVerticalInsight, RelationshipType
        )

        # Reconstruct relationships
        relationships = []
        for r in data.get("relationships", []):
            relationships.append(VerticalRelationship(
                source_vertical=r.get("source_vertical", ""),
                target_vertical=r.get("target_vertical", ""),
                relationship_type=RelationshipType(r.get("relationship_type", "dependency")),
                description=r.get("description", ""),
                strength=r.get("strength", "medium"),
                supporting_facts=r.get("supporting_facts", []),
            ))

        # Reconstruct shared risks
        shared_risks = []
        for sr in data.get("shared_risks", []):
            shared_risks.append(SharedRisk(
                risk_description=sr.get("risk_description", ""),
                affected_verticals=sr.get("affected_verticals", []),
                severity=sr.get("severity", "medium"),
                probability=sr.get("probability", "medium"),
                mitigation_notes=sr.get("mitigation_notes"),
            ))

        # Reconstruct cross-vertical insights
        cross_vertical_insights = []
        for cvi in data.get("cross_vertical_insights", []):
            cross_vertical_insights.append(CrossVerticalInsight(
                insight=cvi.get("insight", ""),
                related_verticals=cvi.get("related_verticals", []),
                implication=cvi.get("implication", ""),
                confidence=cvi.get("confidence", 0.5),
            ))

        return CrossVerticalMap(
            ticker=data.get("ticker", ""),
            relationships=relationships,
            shared_risks=shared_risks,
            cross_vertical_insights=cross_vertical_insights,
            key_dependencies=data.get("key_dependencies", []),
            foundational_verticals=data.get("foundational_verticals", []),
            evidence_ids=data.get("evidence_ids", []),
        )

    def _emit_progress(
        self,
        stage: float,
        status: str,
        detail: str = "",
    ) -> None:
        """Emit progress update to callback if registered."""
        if self._progress_callback is None:
            return

        stage_name = self.STAGES.get(stage, f"Stage {stage}")
        cost_usd = self.budget_tracker.total_cost_usd if self.budget_tracker else 0.0

        try:
            self._progress_callback(
                stage=stage,
                stage_name=stage_name,
                status=status,
                detail=detail,
                cost_usd=cost_usd,
            )
        except Exception as e:
            logger.warning(f"Progress callback failed: {e}")

    async def _log_stage_event(
        self,
        run_state: RunState,
        phase: str,
        status: str,
        detail: str = "",
    ) -> None:
        """Log a stage event to the event store for audit trail.

        Args:
            run_state: Current run state.
            phase: Stage/phase name (e.g., "discovery", "synthesis").
            status: Event status (e.g., "starting", "complete", "error").
            detail: Additional detail about the event.
        """
        if self.event_store is None:
            return

        from er.types import AgentMessage, MessageType

        message = AgentMessage.create(
            run_id=run_state.run_id,
            from_agent="pipeline",
            to_agent="coordinator",
            message_type=MessageType.HANDOFF if status == "complete" else MessageType.RESEARCH_COMPLETE,
            content=f"{phase}: {status} - {detail}" if detail else f"{phase}: {status}",
            context={
                "phase": phase,
                "status": status,
                "detail": detail,
                "ticker": run_state.ticker,
                "cost_usd": self.budget_tracker.total_cost_usd if self.budget_tracker else 0.0,
            },
        )

        try:
            await self.event_store.append(message)
        except Exception as e:
            logger.warning(f"Failed to log stage event: {e}")

    async def run(self, ticker: str) -> PipelineResult:
        """Run the complete 6-stage pipeline for a ticker.

        Args:
            ticker: Stock ticker symbol (e.g., "GOOGL").

        Returns:
            PipelineResult with all outputs.

        Raises:
            Exception: If any stage fails.
        """
        started_at = datetime.now(timezone.utc)
        start_time = asyncio.get_event_loop().time()

        # Check for resume mode
        completed_stages = self._get_completed_stages()
        is_resuming = bool(completed_stages)

        if is_resuming:
            logger.info(
                "Resuming pipeline from checkpoint",
                ticker=ticker,
                completed_stages=sorted(completed_stages),
                resume_dir=str(self.config.resume_from_run_dir),
            )
        else:
            logger.info("Starting research pipeline", ticker=ticker)

        # Initialize evidence store (async)
        await self.evidence_store.init()

        # Create run state
        run_state = RunState(
            run_id=f"run_{ticker}_{started_at.strftime('%Y%m%d_%H%M%S')}",
            ticker=ticker,
            phase=Phase.FETCH_DATA,
            started_at=started_at,
            budget_remaining_usd=self.config.max_budget_usd or 1000.0,
        )

        # Set logging context for all subsequent operations
        set_run_id(run_state.run_id)

        # Initialize event store for audit trail
        if self.config.output_dir:
            self.event_store = EventStore(output_dir=self.config.output_dir)
            await self.event_store.init(run_state.run_id)
            logger.info(
                "Event store initialized",
                run_id=run_state.run_id,
                output_dir=str(self.config.output_dir),
            )

            # Initialize workspace store for structured artifacts
            workspace_db_path = self.config.output_dir / "workspace.db"
            self.workspace_store = WorkspaceStore(workspace_db_path)
            self.workspace_store.init()
            self.agent_context.workspace_store = self.workspace_store
            logger.info(
                "Workspace store initialized",
                run_id=run_state.run_id,
                workspace_db=str(workspace_db_path),
            )

        try:
            # ============== STAGE 1: Data Orchestrator ==============
            set_phase("data_collection")
            if 1 in completed_stages:
                self._emit_progress(1, "complete", "Loaded from checkpoint")
                logger.info("Stage 1: Loading from checkpoint", ticker=ticker)
                company_context = self._load_company_context()
                if not company_context:
                    raise ValueError("Failed to load company_context from checkpoint")
            else:
                self._emit_progress(1, "starting", "Fetching SEC filings, financials, and company data...")
                logger.info("Stage 1: Data Orchestrator", ticker=ticker)
                company_context = await self._run_data_orchestrator(run_state)
                self._save_stage_output("stage1_company_context", company_context)
                await self._log_stage_event(run_state, "data_collection", "complete", company_context.company_name)
                self._emit_progress(1, "complete", f"Loaded {company_context.company_name}")

            # ============== STAGE 2: Discovery ==============
            set_phase("discovery")
            if 2 in completed_stages:
                self._emit_progress(2, "complete", "Loaded from checkpoint")
                logger.info("Stage 2: Loading from checkpoint", ticker=ticker)
                discovery_output = self._load_discovery_output()
                if not discovery_output:
                    raise ValueError("Failed to load discovery_output from checkpoint")
            else:
                self._emit_progress(2, "starting", "Discovering value drivers with 7 analytical lenses...")
                logger.info("Stage 2: Discovery", ticker=ticker)
                discovery_output = await self._run_discovery(run_state, company_context)
                self._save_stage_output("stage2_discovery", discovery_output)
                await self._log_stage_event(run_state, "discovery", "complete", f"{len(discovery_output.research_threads)} threads")
                self._emit_progress(2, "complete", f"Found {len(discovery_output.research_threads)} research verticals")

            # Coverage audit + recency guard (best-effort; no dedicated stage)
            coverage_scorecard = None
            if self.workspace_store:
                coverage_scorecard, _ = await self._run_coverage_audit(
                    run_state,
                    company_context,
                )
                run_recency_guard = True
                if self.config.resume_from_run_dir and discovery_output.thread_briefs:
                    has_recency = any(tb.recent_developments for tb in discovery_output.thread_briefs)
                    run_recency_guard = not has_recency

                if run_recency_guard:
                    await self._run_recency_guard(
                        run_state,
                        company_context,
                        discovery_output,
                        coverage_scorecard=coverage_scorecard,
                    )

                # Persist any recency enrichment added to ThreadBriefs
                if discovery_output.thread_briefs:
                    self._save_stage_output("stage2_discovery", discovery_output)

            if self.config.pause_after_stage == 2:
                logger.info("Pausing pipeline after discovery for approval", ticker=ticker)
                raise PipelinePaused(
                    "Awaiting approval after discovery",
                    context={"stage": 2},
                )

            # ============== STAGE 3: Deep Research (2 Parallel Groups) ==============
            set_phase("deep_research")
            if 3 in completed_stages:
                self._emit_progress(3, "complete", "Loaded from checkpoint")
                logger.info("Stage 3: Loading from checkpoint", ticker=ticker)
                loaded = self._load_vertical_analyses()
                if not loaded:
                    raise ValueError("Failed to load vertical analyses from checkpoint")
                group_research_outputs, vertical_analyses = loaded
            else:
                self._emit_progress(3, "starting", "Running deep research with 2 parallel Gemini groups...")
                logger.info("Stage 3: Deep Research (2 Parallel Groups)", ticker=ticker)
                group_research_outputs, vertical_analyses = await self._run_vertical_analysis(
                    run_state,
                    company_context,
                    discovery_output,
                )
                self._save_stage_output("stage3_group_research", group_research_outputs)
                self._save_stage_output("stage3_verticals", vertical_analyses)
                await self._log_stage_event(run_state, "deep_research", "complete", f"{len(vertical_analyses)} verticals")
                self._emit_progress(3, "complete", f"Completed {len(vertical_analyses)} vertical analyses")

            # ============== STAGE 3.5: Verification ==============
            set_phase("verification")
            if 3.5 in completed_stages:
                self._emit_progress(3.5, "complete", "Loaded from checkpoint")
                logger.info("Stage 3.5: Loading from checkpoint", ticker=ticker)
                verified_package = self._load_verification_output()
                if not verified_package:
                    raise ValueError("Failed to load verification output from checkpoint")
            else:
                self._emit_progress(3.5, "starting", "Verifying facts against ground truth data...")
                logger.info("Stage 3.5: Verification", ticker=ticker)

                verified_package = await self._run_verification(
                    run_state,
                    company_context,
                    group_research_outputs,
                )
                self._save_stage_output("stage3_5_verification", verified_package)
                await self._log_stage_event(
                    run_state, "verification", "complete",
                    f"{verified_package.verified_count}/{verified_package.total_facts} verified"
                )
                self._emit_progress(
                    3.5, "complete",
                    f"Verified {verified_package.verified_count}/{verified_package.total_facts} facts, "
                    f"{verified_package.contradicted_count} contradictions"
                )

            # ============== STAGE 3.75: Integration ==============
            set_phase("integration")
            if 3.75 in completed_stages:
                self._emit_progress(3.75, "complete", "Loaded from checkpoint")
                logger.info("Stage 3.75: Loading from checkpoint", ticker=ticker)
                cross_vertical_map = self._load_integration_output()
                if not cross_vertical_map:
                    raise ValueError("Failed to load integration output from checkpoint")
            else:
                self._emit_progress(3.75, "starting", "Finding cross-vertical patterns and dependencies...")
                logger.info("Stage 3.75: Integration", ticker=ticker)

                cross_vertical_map = await self._run_integration(
                    run_state,
                    verified_package,
                    company_context.company_name,
                )
                self._save_stage_output("stage3_75_integration", cross_vertical_map)
                await self._log_stage_event(
                    run_state, "integration", "complete",
                    f"{len(cross_vertical_map.relationships)} relationships, {len(cross_vertical_map.shared_risks)} shared risks"
                )
                self._emit_progress(
                    3.75, "complete",
                    f"Found {len(cross_vertical_map.relationships)} relationships, "
                    f"{len(cross_vertical_map.shared_risks)} shared risks"
                )

            # ============== STAGE 4: Dual Synthesis (Parallel) ==============
            set_phase("synthesis")
            if 4 in completed_stages:
                self._emit_progress(4, "complete", "Loaded from checkpoint")
                logger.info("Stage 4: Loading from checkpoint", ticker=ticker)
                loaded = self._load_synthesis_outputs()
                if not loaded:
                    raise ValueError("Failed to load synthesis outputs from checkpoint")
                claude_synthesis, gpt_synthesis = loaded
            else:
                self._emit_progress(4, "starting", "Running parallel synthesis (Claude Opus + GPT)...")
                logger.info("Stage 4: Dual Synthesis", ticker=ticker)
                claude_synthesis, gpt_synthesis = await self._run_synthesis(
                    run_state,
                    company_context,
                    discovery_output,
                    vertical_analyses,
                    verified_package=verified_package,
                    cross_vertical_map=cross_vertical_map,
                )
                self._save_stage_output("stage4_claude_synthesis", claude_synthesis)
                self._save_stage_output("stage4_gpt_synthesis", gpt_synthesis)
                await self._log_stage_event(run_state, "synthesis", "complete", f"Claude:{claude_synthesis.investment_view} GPT:{gpt_synthesis.investment_view}")
                self._emit_progress(4, "complete", f"Claude: {claude_synthesis.investment_view} | GPT: {gpt_synthesis.investment_view}")

            # ============== STAGE 5: Editorial Review ==============
            set_phase("editorial_review")
            if 5 in completed_stages:
                self._emit_progress(5, "complete", "Loaded from checkpoint")
                logger.info("Stage 5: Loading from checkpoint", ticker=ticker)
                editorial_feedback = self._load_editorial_feedback()
                if not editorial_feedback:
                    raise ValueError("Failed to load editorial feedback from checkpoint")
            else:
                self._emit_progress(5, "starting", "Judge reviewing both synthesis reports...")
                logger.info("Stage 5: Editorial Review", ticker=ticker)

                # Judge reviews both syntheses and produces editorial feedback
                editorial_feedback = await self._run_editorial_review(
                    run_state,
                    company_context,
                    claude_synthesis,
                    gpt_synthesis,
                    verified_package=verified_package,
                )

                logger.info(
                    "Editorial review complete",
                    ticker=ticker,
                    preferred=editorial_feedback.preferred_synthesis,
                    claude_score=editorial_feedback.claude_score,
                    gpt_score=editorial_feedback.gpt_score,
                    insights_to_incorporate=len(editorial_feedback.incorporate_from_other),
                )
                self._save_stage_output("stage5_editorial_feedback", editorial_feedback)
                await self._log_stage_event(run_state, "editorial_review", "complete", f"Winner:{editorial_feedback.preferred_synthesis}")
                self._emit_progress(5, "complete", f"Winner: {editorial_feedback.preferred_synthesis.upper()} ({editorial_feedback.claude_score:.1f} vs {editorial_feedback.gpt_score:.1f})")

            # ============== STAGE 6: Revision ==============
            set_phase("revision")
            # Stage 6 always runs (it's the final output)

            # Handle reject_both case - re-synthesize with rejection instructions
            if editorial_feedback.preferred_synthesis == "reject_both":
                self._emit_progress(6, "starting", "Both syntheses rejected - re-synthesizing...")
                logger.warning(
                    "Both syntheses rejected by Judge",
                    ticker=ticker,
                    rejection_reason=editorial_feedback.rejection_reason,
                )

                # Re-run synthesis with rejection instructions
                # Use Claude as the default re-synthesizer with the rejection reason as guidance
                final_report = await self._run_resynthesis(
                    run_state,
                    company_context,
                    discovery_output,
                    vertical_analyses,
                    editorial_feedback,
                    verified_package=verified_package,
                    cross_vertical_map=cross_vertical_map,
                )
            else:
                self._emit_progress(6, "starting", f"Revising {editorial_feedback.preferred_synthesis.upper()} synthesis with editorial feedback...")
                logger.info("Stage 6: Synthesis Revision", ticker=ticker)

                # Get the winning synthesis
                if editorial_feedback.preferred_synthesis == "claude":
                    winning_synthesis = claude_synthesis
                else:
                    winning_synthesis = gpt_synthesis

                # Revise the winning synthesis based on editorial feedback
                final_report = await self._run_revision(
                    run_state,
                    company_context,
                    winning_synthesis,
                    editorial_feedback,
                )
            self._emit_progress(6, "complete", f"Final verdict: {final_report.investment_view} ({final_report.conviction} conviction)")

            logger.info(
                "Revision complete",
                ticker=ticker,
                final_view=final_report.investment_view,
                final_conviction=final_report.conviction,
                report_len=len(final_report.full_report),
            )
            self._save_stage_output("stage6_final_report", final_report)
            await self._log_stage_event(run_state, "revision", "complete", f"{final_report.investment_view} ({final_report.conviction})")

            # ============== STAGE 7: Valuation & Report Compilation ==============
            # Run valuation and report compilation (non-blocking, artifacts stored)
            valuation_workbook: ValuationWorkbook | None = None
            compiled_report: CompiledReport | None = None
            peer_group: PeerGroup | None = None

            try:
                valuation_workbook, peer_group = await self._run_valuation(
                    run_state,
                    company_context,
                    final_report,
                )

                if valuation_workbook:
                    self._save_stage_output("stage7_valuation", valuation_workbook.to_dict())

                if peer_group:
                    self._save_stage_output("stage7_peers", peer_group.to_dict())

                # Compile the final report
                compiled_report = await self._compile_report(
                    run_state,
                    company_context,
                    final_report,
                    verified_package,
                    valuation_workbook,
                )

                if compiled_report:
                    self._save_stage_output("stage7_compiled_report", compiled_report.to_dict())

                    # Export Excel workbook
                    if self.config.output_dir and valuation_workbook:
                        excel_path = await self._export_excel(
                            valuation_workbook,
                            self.config.output_dir,
                        )
                        if excel_path:
                            logger.info(
                                "Excel export complete",
                                ticker=ticker,
                                excel_path=str(excel_path),
                            )

                logger.info(
                    "Valuation and report compilation complete",
                    ticker=ticker,
                    has_dcf=valuation_workbook is not None and valuation_workbook.dcf_result is not None,
                    has_reverse_dcf=valuation_workbook is not None and valuation_workbook.reverse_dcf_result is not None,
                    peer_count=len(peer_group.peers) if peer_group else 0,
                )

            except Exception as e:
                # Valuation failures shouldn't crash the pipeline
                logger.warning(
                    "Valuation/compilation failed (non-fatal)",
                    ticker=ticker,
                    error=str(e),
                )

            # Calculate totals
            end_time = asyncio.get_event_loop().time()
            duration_seconds = end_time - start_time
            total_cost = self.budget_tracker.total_cost_usd

            run_state.phase = Phase.COMPLETE

            logger.info(
                "Pipeline completed",
                ticker=ticker,
                duration_seconds=duration_seconds,
                total_cost_usd=total_cost,
                final_view=final_report.investment_view,
                final_conviction=final_report.conviction,
                preferred_synthesis=editorial_feedback.preferred_synthesis,
            )

            return PipelineResult(
                ticker=ticker,
                company_name=company_context.company_name,
                company_context=company_context,
                discovery_output=discovery_output,
                group_research_outputs=group_research_outputs,
                vertical_analyses=vertical_analyses,
                claude_synthesis=claude_synthesis,
                gpt_synthesis=gpt_synthesis,
                editorial_feedback=editorial_feedback,
                final_report=final_report,
                run_state=run_state,
                total_cost_usd=total_cost,
                duration_seconds=duration_seconds,
                started_at=started_at,
            )

        except PipelinePaused as e:
            run_state.phase = Phase.DISCOVERY
            logger.info(
                "Pipeline paused",
                ticker=ticker,
                reason=str(e),
            )
            raise

        except Exception as e:
            logger.error(
                "Pipeline failed",
                ticker=ticker,
                error=str(e),
                phase=run_state.phase.value if run_state.phase else "unknown",
            )
            raise

        finally:
            await self.close()

    async def _run_data_orchestrator(
        self,
        run_state: RunState,
    ) -> CompanyContext:
        """Stage 1: Fetch all data and build CompanyContext."""
        if self._data_orchestrator is None:
            self._data_orchestrator = DataOrchestratorAgent(self.agent_context)

        return await self._data_orchestrator.run(
            run_state,
            include_transcripts=self.config.include_transcripts,
            num_transcript_quarters=self.config.num_transcript_quarters,
            manual_transcripts=self.config.manual_transcripts,
        )

    async def _run_discovery(
        self,
        run_state: RunState,
        company_context: CompanyContext,
    ) -> DiscoveryOutput:
        """Stage 2: Discover all value drivers.

        If dual_discovery is enabled, runs Internal + External discovery in parallel
        and merges the results.
        """
        # Initialize Internal Discovery agent
        if self._discovery_agent is None:
            self._discovery_agent = DiscoveryAgent(self.agent_context)

        if not self.config.use_dual_discovery:
            # Single discovery (legacy mode)
            return await self._discovery_agent.run(
                run_state,
                company_context,
                use_web_search=self.config.use_web_search_discovery,
            )

        # Dual discovery mode - run Internal and External in parallel
        logger.info(
            "Running dual discovery (Internal + External)",
            ticker=run_state.ticker,
        )

        # Initialize External Discovery agents (light + anchored)
        if self._external_discovery_agents is None:
            self._external_discovery_agents = {}

        # Initialize Merger
        if self._discovery_merger is None:
            self._discovery_merger = DiscoveryMerger(self.agent_context)

        # Run both in parallel
        internal_task = asyncio.create_task(
            self._discovery_agent.run(
                run_state,
                company_context,
                use_web_search=self.config.use_web_search_discovery,
            )
        )

        external_modes = [
            mode for mode in self.config.external_discovery_modes
            if mode in ("light", "anchored")
        ]
        if not external_modes:
            external_modes = ["anchored"]

        external_tasks = []
        for mode in external_modes:
            if mode not in self._external_discovery_agents:
                self._external_discovery_agents[mode] = ExternalDiscoveryAgent(
                    self.agent_context,
                    mode=mode,
                    extra_queries=self.config.external_discovery_extra_queries,
                    max_total_queries=self.config.external_discovery_max_queries,
                )
            external_tasks.append(
                asyncio.create_task(
                    self._external_discovery_agents[mode].run(
                        run_state,
                        company_context,
                        override_queries=self.config.external_discovery_overrides,
                        override_mode=self.config.external_discovery_override_mode,
                    )
                )
            )

        # Wait for both with proper error handling
        internal_output = None
        external_outputs: list[ExternalDiscoveryOutput] = []

        try:
            results = await asyncio.gather(
                internal_task,
                *external_tasks,
                return_exceptions=True,
            )

            internal_output = results[0]
            external_results = results[1:]

            # Handle exceptions
            if isinstance(internal_output, Exception):
                logger.error("Internal discovery failed", error=str(internal_output))
                raise internal_output

            for mode, external_result in zip(external_modes, external_results):
                if isinstance(external_result, Exception):
                    logger.warning(
                        "External discovery failed, skipping mode",
                        error=str(external_result),
                        mode=mode,
                    )
                    continue
                external_outputs.append(external_result)

        except Exception as e:
            # If internal failed, we can't continue
            logger.error("Discovery failed", error=str(e))
            raise

        # Save individual outputs for debugging
        self._save_stage_output("stage2_internal_discovery", internal_output)
        for external_output in external_outputs:
            mode = external_output.mode or "external"
            self._save_stage_output(f"stage2_external_discovery_{mode}", external_output)

        if not external_outputs:
            logger.warning("All external discovery modes failed, using internal only")
            return internal_output

        # Merge the outputs
        merged_output = self._discovery_merger.merge(
            internal_output,
            external_outputs,
            run_state,
        )

        logger.info(
            "Discovery merge complete",
            ticker=run_state.ticker,
            internal_threads=len(internal_output.research_threads),
            external_variant_perceptions=sum(len(e.variant_perceptions) for e in external_outputs),
            external_strategic_shifts=sum(len(e.strategic_shifts) for e in external_outputs),
            merged_threads=len(merged_output.research_threads),
        )

        return merged_output

    async def _run_coverage_audit(
        self,
        run_state: RunState,
        company_context: CompanyContext,
    ) -> tuple[CoverageScorecard | None, list[CoverageAction]]:
        """Run coverage audit on evidence cards (best-effort)."""
        if self._coverage_auditor is None:
            self._coverage_auditor = CoverageAuditor(self.agent_context)

        evidence_cards: list[dict[str, Any]] = []
        if self.workspace_store:
            artifacts = self.workspace_store.list_artifacts("evidence_card")
            evidence_cards = [a.get("content", {}) for a in artifacts]

        if not evidence_cards:
            logger.info("Coverage audit skipped (no evidence cards)", ticker=run_state.ticker)
            return None, []

        scorecard, actions = await self._coverage_auditor.run(
            run_state=run_state,
            company_context=company_context,
            evidence_cards=evidence_cards,
        )
        return scorecard, actions

    async def _run_recency_guard(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
        coverage_scorecard: CoverageScorecard | None = None,
    ) -> RecencyGuardOutput | None:
        """Run recency guard checks (best-effort)."""
        if self._recency_guard is None:
            self._recency_guard = RecencyGuardAgent(self.agent_context)

        try:
            return await self._recency_guard.run(
                run_state=run_state,
                company_context=company_context,
                coverage_scorecard=coverage_scorecard,
                thread_briefs=discovery_output.thread_briefs,
                threads=discovery_output.research_threads,
            )
        except Exception as e:
            logger.warning("Recency guard failed", ticker=run_state.ticker, error=str(e))
            return None

    async def _run_vertical_analysis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
    ) -> tuple[list[GroupResearchOutput], list[VerticalAnalysis]]:
        """Stage 3: Deep research with 2 parallel research groups.

        Returns:
            Tuple of (group_outputs, flattened_vertical_analyses)
        """
        # Get research groups from discovery
        research_groups = discovery_output.research_groups

        # If no groups defined, create default groups from threads
        if not research_groups:
            logger.warning(
                "No research groups from discovery, creating default groups",
                ticker=run_state.ticker,
            )
            research_groups = self._create_default_groups(discovery_output)

        logger.info(
            "Running deep research with parallel groups",
            ticker=run_state.ticker,
            group_count=len(research_groups),
            total_verticals=len(discovery_output.research_threads),
        )

        review_notes = None
        if self.config.output_dir:
            notes_path = self.config.output_dir / "stage2_discovery_review_notes.txt"
            if notes_path.exists():
                review_notes = notes_path.read_text().strip() or None

        # Build all groups with their threads for co-analyst coordination
        all_groups_with_threads: list[tuple[ResearchGroup, list[DiscoveredThread]]] = []
        for group in research_groups[:2]:  # Max 2 groups
            threads = discovery_output.get_threads_for_group(group)
            all_groups_with_threads.append((group, threads))

        # Run research groups in parallel (2 groups max)
        async def research_group(
            group: ResearchGroup,
            group_threads: list[DiscoveredThread],
            other_groups: list[tuple[ResearchGroup, list[DiscoveredThread]]],
        ) -> GroupResearchOutput:
            if not group_threads:
                logger.warning(
                    "No threads found for group",
                    group=group.name,
                )
                return GroupResearchOutput(
                    group_id=group.group_id,
                    group_name=group.name,
                    vertical_analyses=[],
                    synergies="",
                    shared_risks="",
                    group_thesis="",
                    web_searches_performed=[],
                    overall_confidence=0.0,
                    data_gaps=["No threads assigned to group"],
                    evidence_ids=[],
                )

            agent = VerticalAnalystAgent(self.agent_context)
            try:
                return await agent.run_group(
                    run_state,
                    company_context,
                    group,
                    group_threads,
                    use_deep_research=self.config.use_deep_research_verticals,
                    other_groups=other_groups,  # Pass other groups for co-analyst coordination!
                    discovery_output=discovery_output,  # For evidence propagation
                    review_guidance=review_notes,
                )
            finally:
                await agent.close()

        # Run both groups in parallel, passing each group info about the other
        async def run_group_with_context(idx: int) -> GroupResearchOutput:
            group, threads = all_groups_with_threads[idx]
            # Other groups = all groups except this one
            other = [g for i, g in enumerate(all_groups_with_threads) if i != idx]
            return await research_group(group, threads, other)

        group_results = await asyncio.gather(
            *[run_group_with_context(i) for i in range(len(all_groups_with_threads))],
            return_exceptions=True,
        )

        # Process results
        group_outputs: list[GroupResearchOutput] = []
        all_vertical_analyses: list[VerticalAnalysis] = []

        for i, result in enumerate(group_results):
            if isinstance(result, Exception):
                logger.error(
                    "Research group failed",
                    group=research_groups[i].name if i < len(research_groups) else "unknown",
                    error=str(result),
                )
            else:
                group_outputs.append(result)
                all_vertical_analyses.extend(result.vertical_analyses)

        logger.info(
            "Completed deep research",
            ticker=run_state.ticker,
            successful_groups=len(group_outputs),
            total_verticals_analyzed=len(all_vertical_analyses),
        )

        return group_outputs, all_vertical_analyses

    def _create_default_groups(
        self,
        discovery_output: DiscoveryOutput,
    ) -> list[ResearchGroup]:
        """Create default research groups if discovery didn't provide them.

        Splits threads into Core Business and Growth/Optionality groups.
        """
        from er.types import ThreadType, generate_id

        threads = discovery_output.research_threads
        if not threads:
            return []

        # Split into core and growth
        core_threads = []
        growth_threads = []

        for t in threads:
            if t.thread_type == ThreadType.SEGMENT:
                core_threads.append(t)
            else:
                growth_threads.append(t)

        # If all are same type, split by priority
        if not core_threads:
            mid = len(threads) // 2
            core_threads = threads[:mid]
            growth_threads = threads[mid:]
        elif not growth_threads:
            mid = len(threads) // 2
            growth_threads = core_threads[mid:]
            core_threads = core_threads[:mid]

        groups = []

        if core_threads:
            groups.append(ResearchGroup(
                group_id=generate_id("group"),
                name="Core Business",
                theme="Established business segments and primary revenue drivers",
                focus="Analyze competitive position, growth trajectory, and margin profile",
                vertical_ids=[t.thread_id for t in core_threads],
                key_questions=["What is the growth outlook?", "How sustainable is the competitive position?"],
            ))

        if growth_threads:
            groups.append(ResearchGroup(
                group_id=generate_id("group"),
                name="Growth & Optionality",
                theme="Emerging businesses, strategic bets, and optionality",
                focus="Assess growth potential, TAM, and probability of success",
                vertical_ids=[t.thread_id for t in growth_threads],
                key_questions=["What is the potential upside?", "What are the key risks?"],
            ))

        return groups

    async def _run_verification(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        group_outputs: list[GroupResearchOutput],
    ) -> VerifiedResearchPackage:
        """Stage 3.5: Verify facts against ground truth data.

        Args:
            run_state: Current run state.
            company_context: Company data with ground truth financials.
            group_outputs: Research outputs containing facts to verify.

        Returns:
            VerifiedResearchPackage with verification results.
        """
        if self._verifier is None:
            self._verifier = VerificationAgent(self.agent_context)

        return await self._verifier.run(
            run_state,
            company_context,
            group_outputs,
        )

    async def _run_integration(
        self,
        run_state: RunState,
        verified_package: VerifiedResearchPackage,
        company_name: str,
    ) -> CrossVerticalMap:
        """Stage 3.75: Find cross-vertical patterns and dependencies.

        Args:
            run_state: Current run state.
            verified_package: Verified research package from Stage 3.5.
            company_name: Company name for context.

        Returns:
            CrossVerticalMap with relationships, shared risks, and insights.
        """
        if self._integrator is None:
            self._integrator = IntegratorAgent(self.agent_context)

        return await self._integrator.run(
            run_state,
            verified_package,
            company_name=company_name,
        )

    async def _run_synthesis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
        vertical_analyses: list[VerticalAnalysis],
        verified_package: VerifiedResearchPackage | None = None,
        cross_vertical_map: CrossVerticalMap | None = None,
    ) -> tuple[SynthesisOutput, SynthesisOutput]:
        """Stage 4: Dual synthesis with Claude and GPT."""
        if self._synthesizer is None:
            self._synthesizer = SynthesizerAgent(self.agent_context)

        return await self._synthesizer.run(
            run_state,
            company_context,
            discovery_output,
            vertical_analyses,
            verified_package=verified_package,
            cross_vertical_map=cross_vertical_map,
            output_dir=self.config.output_dir,
        )

    async def _run_editorial_review(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        claude_synthesis: SynthesisOutput,
        gpt_synthesis: SynthesisOutput,
        verified_package: VerifiedResearchPackage | None = None,
    ) -> EditorialFeedback:
        """Stage 5: Editorial review by the Judge.

        The Judge compares both syntheses and produces editorial feedback
        for the winning Synthesizer to revise their report.

        Args:
            run_state: Current run state.
            company_context: Company data context.
            claude_synthesis: Claude's synthesis output.
            gpt_synthesis: GPT's synthesis output.
            verified_package: Verified research package for citation checking.

        Returns:
            EditorialFeedback with revision instructions.
        """
        if self._judge is None:
            self._judge = JudgeAgent(self.agent_context)

        return await self._judge.run(
            run_state,
            company_context,
            claude_synthesis,
            gpt_synthesis,
            verified_package=verified_package,
        )

    async def _run_revision(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        original_synthesis: SynthesisOutput,
        feedback: EditorialFeedback,
    ) -> SynthesisOutput:
        """Stage 6: Revise the winning synthesis based on editorial feedback.

        Args:
            run_state: Current run state.
            company_context: Company data context.
            original_synthesis: The winning synthesis to revise.
            feedback: Editorial feedback from the Judge.

        Returns:
            Revised SynthesisOutput.
        """
        if self._synthesizer is None:
            self._synthesizer = SynthesizerAgent(self.agent_context)

        return await self._synthesizer.revise(
            run_state,
            company_context,
            original_synthesis,
            feedback,
        )

    async def _run_resynthesis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
        vertical_analyses: list[VerticalAnalysis],
        feedback: EditorialFeedback,
        verified_package: VerifiedResearchPackage | None = None,
        cross_vertical_map: CrossVerticalMap | None = None,
    ) -> SynthesisOutput:
        """Re-synthesize after Judge rejects both reports.

        When both Claude and GPT syntheses are rejected, we re-run synthesis
        with the rejection reason as additional guidance.

        Args:
            run_state: Current run state.
            company_context: Company data context.
            discovery_output: Discovery output.
            vertical_analyses: Vertical analyses.
            feedback: Editorial feedback with rejection_reason.
            verified_package: Optional VerifiedResearchPackage from Verifier.
            cross_vertical_map: Optional CrossVerticalMap from Integrator.

        Returns:
            New SynthesisOutput from re-synthesis.
        """
        if self._synthesizer is None:
            self._synthesizer = SynthesizerAgent(self.agent_context)

        logger.info(
            "Re-running synthesis after rejection",
            ticker=run_state.ticker,
            rejection_reason=feedback.rejection_reason,
        )

        return await self._synthesizer.resynthesis(
            run_state,
            company_context,
            discovery_output,
            vertical_analyses,
            feedback,
            verified_package=verified_package,
            cross_vertical_map=cross_vertical_map,
        )

    async def _run_valuation(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        final_report: SynthesisOutput,
    ) -> tuple[ValuationWorkbook | None, PeerGroup | None]:
        """Run DCF and Reverse DCF valuation.

        Args:
            run_state: Current run state.
            company_context: Company financial data.
            final_report: Final synthesis output.

        Returns:
            Tuple of (ValuationWorkbook, PeerGroup) or (None, None) if insufficient data.
        """
        ticker = run_state.ticker
        company_name = company_context.company_name

        # Extract financial data from CompanyContext
        income_stmt = company_context.income_statement_quarterly or company_context.income_statement_annual
        balance_sheet = company_context.balance_sheet_annual
        market_data = getattr(company_context, "market_data", {}) or {}

        if not income_stmt or not balance_sheet:
            logger.info("Insufficient financial data for valuation", ticker=ticker)
            return None, None

        latest_income = income_stmt[0] if income_stmt else {}
        latest_balance = balance_sheet[0] if balance_sheet else {}

        # Get key metrics
        current_revenue = latest_income.get("revenue", 0)
        operating_income = latest_income.get("operatingIncome", 0)
        operating_margin = operating_income / current_revenue if current_revenue > 0 else 0.15

        total_debt = latest_balance.get("totalDebt", 0)
        cash = latest_balance.get("cashAndCashEquivalents", 0)
        net_debt = total_debt - cash

        shares_outstanding = (
            market_data.get("shares_outstanding")
            or market_data.get("sharesOutstanding")
            or 1e9
        )  # Default 1B shares
        current_price = market_data.get("price", 0) or 0

        if current_revenue <= 0:
            logger.info("No revenue data available for valuation", ticker=ticker)
            return None, None

        # Run DCF
        dcf_engine = DCFEngine()
        dcf_result: DCFResult | None = None
        sensitivity_data: dict[str, Any] | None = None

        try:
            # Use AssumptionBuilder to derive inputs from company data
            assumption_builder = AssumptionBuilder()
            dcf_inputs = assumption_builder.build_dcf_inputs(company_context)

            # Override current_revenue with what we calculated above
            dcf_inputs.current_revenue = current_revenue

            logger.info(
                "DCF assumptions derived",
                ticker=ticker,
                wacc=dcf_inputs.wacc,
                terminal_growth=dcf_inputs.terminal_growth,
                revenue_projections_count=len(dcf_inputs.revenue_projections),
            )

            dcf_result = dcf_engine.calculate_dcf(
                dcf_inputs,
                net_debt=net_debt,
                shares_outstanding=shares_outstanding,
            )

            # Run sensitivity analysis
            sensitivity_data = dcf_engine.sensitivity_analysis(
                dcf_inputs,
                net_debt=net_debt,
                shares_outstanding=shares_outstanding,
            )

            logger.info(
                "DCF valuation complete",
                ticker=ticker,
                intrinsic_value=dcf_result.intrinsic_value_per_share,
            )

        except Exception as e:
            logger.warning("DCF calculation failed", ticker=ticker, error=str(e))

        # Run Reverse DCF (uses same assumptions as forward DCF)
        reverse_dcf_result: ReverseDCFResult | None = None
        if current_price > 0:
            try:
                reverse_engine = ReverseDCFEngine()
                # Use WACC and terminal growth from DCF inputs if available
                reverse_wacc = dcf_inputs.wacc if dcf_inputs else 0.10
                reverse_terminal = dcf_inputs.terminal_growth if dcf_inputs else 0.025
                reverse_inputs = ReverseDCFInputs(
                    current_price=current_price,
                    shares_outstanding=shares_outstanding,
                    net_debt=net_debt,
                    current_revenue=current_revenue,
                    current_margin=operating_margin,
                    wacc=reverse_wacc,
                    terminal_growth=reverse_terminal,
                )

                reverse_dcf_result = reverse_engine.calculate_implied_growth(reverse_inputs)

                logger.info(
                    "Reverse DCF complete",
                    ticker=ticker,
                    implied_cagr=reverse_dcf_result.implied_revenue_cagr,
                )

            except Exception as e:
                logger.warning("Reverse DCF failed", ticker=ticker, error=str(e))

        # Create valuation workbook
        valuation_workbook = ValuationWorkbook(
            ticker=ticker,
            company_name=company_name,
            dcf_result=dcf_result,
            reverse_dcf_result=reverse_dcf_result,
            sensitivity_data=sensitivity_data,
        )

        # Run peer selection
        peer_group: PeerGroup | None = None
        try:
            peer_selector = PeerSelector(peer_database=create_default_peer_database())
            profile = company_context.profile or {}
            sector = profile.get("sector") or market_data.get("sector") or "Technology"
            industry = profile.get("industry") or market_data.get("industry") or "Software"
            market_cap = market_data.get("market_cap") or market_data.get("marketCap") or 0

            peer_group = peer_selector.select_peers(
                ticker=ticker,
                company_name=company_name,
                sector=sector,
                industry=industry,
                market_cap=market_cap,
                revenue=current_revenue,
                max_peers=5,
            )

            logger.info(
                "Peer selection complete",
                ticker=ticker,
                peer_count=len(peer_group.peers),
            )

        except Exception as e:
            logger.warning("Peer selection failed", ticker=ticker, error=str(e))

        # Store in WorkspaceStore
        if self.workspace_store:
            if dcf_result:
                self.workspace_store.put_artifact(
                    artifact_type="dcf_valuation",
                    producer="pipeline",
                    json_obj=dcf_result.to_dict(),
                    summary=f"DCF intrinsic value: ${dcf_result.intrinsic_value_per_share:.2f}",
                )

            if reverse_dcf_result:
                self.workspace_store.put_artifact(
                    artifact_type="reverse_dcf",
                    producer="pipeline",
                    json_obj=reverse_dcf_result.to_dict(),
                    summary=f"Implied CAGR: {reverse_dcf_result.implied_revenue_cagr:.1%}",
                )

            if peer_group:
                self.workspace_store.put_artifact(
                    artifact_type="peer_group",
                    producer="pipeline",
                    json_obj=peer_group.to_dict(),
                    summary=f"Selected {len(peer_group.peers)} peers",
                )

        return valuation_workbook, peer_group

    async def _compile_report(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        final_report: SynthesisOutput,
        verified_package: VerifiedResearchPackage | None,
        valuation_workbook: ValuationWorkbook | None,
    ) -> CompiledReport | None:
        """Compile the final research report with citations.

        Args:
            run_state: Current run state.
            company_context: Company data.
            final_report: Final synthesis output.
            verified_package: Verified research package.
            valuation_workbook: Valuation results.

        Returns:
            CompiledReport or None if compilation fails.
        """
        try:
            compiler = ReportCompiler()

            # Get verified facts for citation building
            verified_facts = verified_package.all_verified_facts if verified_package else None

            # Get current price from market data
            market_data = getattr(company_context, "market_data", {}) or {}
            current_price = market_data.get("price")

            compiled = compiler.compile(
                synthesis_text=final_report.full_report,
                ticker=run_state.ticker,
                company_name=company_context.company_name,
                verified_facts=verified_facts,
                current_price=current_price,
            )

            # Store in WorkspaceStore
            if self.workspace_store:
                self.workspace_store.put_artifact(
                    artifact_type="compiled_report",
                    producer="pipeline",
                    json_obj=compiled.to_dict(),
                    summary=f"Report: {compiled.investment_view.value} ({compiled.conviction.value})",
                )

            logger.info(
                "Report compilation complete",
                ticker=run_state.ticker,
                sections=len(compiled.sections),
                citations=len(compiled.citations),
            )

            return compiled

        except Exception as e:
            logger.warning("Report compilation failed", ticker=run_state.ticker, error=str(e))
            return None

    async def _export_excel(
        self,
        valuation_workbook: ValuationWorkbook,
        output_dir: Path,
    ) -> Path | None:
        """Export valuation to Excel workbook.

        Args:
            valuation_workbook: Valuation data to export.
            output_dir: Output directory.

        Returns:
            Path to Excel file or None if export failed.
        """
        try:
            exporter = ValuationExporter()

            # First try Excel export
            excel_path = output_dir / f"{valuation_workbook.ticker}_valuation.xlsx"
            result = exporter.export_excel(valuation_workbook, excel_path)

            if result:
                return result

            # Fall back to JSON and CSV
            json_path = output_dir / f"{valuation_workbook.ticker}_valuation.json"
            exporter.export_json(valuation_workbook, json_path)
            exporter.export_csv(valuation_workbook, output_dir)

            logger.info(
                "Valuation exported (fallback format)",
                ticker=valuation_workbook.ticker,
                json_path=str(json_path),
            )

            return json_path

        except Exception as e:
            logger.warning(
                "Excel export failed",
                ticker=valuation_workbook.ticker,
                error=str(e),
            )
            return None

    async def close(self) -> None:
        """Close all agents and resources."""
        if self._data_orchestrator:
            await self._data_orchestrator.close()
            self._data_orchestrator = None
        if self._discovery_agent:
            await self._discovery_agent.close()
            self._discovery_agent = None
        if self._external_discovery_agents:
            for agent in self._external_discovery_agents.values():
                await agent.close()
            self._external_discovery_agents = None
        if self._discovery_merger:
            await self._discovery_merger.close()
            self._discovery_merger = None
        if self._coverage_auditor:
            await self._coverage_auditor.close()
            self._coverage_auditor = None
        if self._recency_guard:
            self._recency_guard = None
        if self._verifier:
            await self._verifier.close()
            self._verifier = None
        if self._integrator:
            await self._integrator.close()
            self._integrator = None
        if self._synthesizer:
            await self._synthesizer.close()
            self._synthesizer = None
        if self._judge:
            await self._judge.close()
            self._judge = None
        # Close event store
        if self.event_store:
            await self.event_store.close()
            self.event_store = None
        # Close workspace store
        if self.workspace_store:
            self.workspace_store.close()
            self.workspace_store = None
        # Clear logging context
        set_run_id(None)
        set_phase(None)


async def run_research(
    ticker: str,
    config: PipelineConfig | None = None,
    settings: Settings | None = None,
) -> PipelineResult:
    """Convenience function to run the full pipeline.

    Args:
        ticker: Stock ticker symbol.
        config: Optional pipeline configuration.
        settings: Optional settings (loads from env if None).

    Returns:
        PipelineResult with all outputs.
    """
    pipeline = ResearchPipeline(settings=settings, config=config)
    return await pipeline.run(ticker)
