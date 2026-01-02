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
        stage: int,
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
from er.agents.external_discovery import ExternalDiscoveryAgent
from er.agents.discovery_merger import DiscoveryMerger
from er.agents.judge import JudgeAgent
from er.agents.synthesizer import SynthesizerAgent
from er.agents.vertical_analyst import VerticalAnalystAgent
from er.budget import BudgetTracker
from er.config import Settings
from er.evidence.store import EvidenceStore
from er.llm.router import LLMRouter
from er.logging import get_logger
from er.types import (
    CompanyContext,
    DiscoveryOutput,
    EditorialFeedback,
    GroupResearchOutput,
    Phase,
    ResearchGroup,
    RunState,
    SynthesisOutput,
    VerticalAnalysis,
)

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

    # Stage 3: Verticals
    max_parallel_verticals: int = 5
    use_deep_research_verticals: bool = True
    max_verticals: int | None = None  # None = use all discovered

    # Stage 4, 5, 6: Synthesis, Editorial Review, Revision
    # (no config needed - always uses extended thinking)

    # Budget
    max_budget_usd: float | None = None  # None = no limit


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
    """6-stage equity research pipeline coordinator."""

    # Stage definitions for progress tracking
    STAGES = {
        1: "Data Collection",
        2: "Discovery",
        3: "Deep Research",
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

        # Create agent context
        self.agent_context = AgentContext(
            settings=self.settings,
            llm_router=self.llm_router,
            evidence_store=self.evidence_store,
            budget_tracker=self.budget_tracker,
        )

        # Initialize agents
        self._data_orchestrator: DataOrchestratorAgent | None = None
        self._discovery_agent: DiscoveryAgent | None = None
        self._external_discovery_agent: ExternalDiscoveryAgent | None = None
        self._discovery_merger: DiscoveryMerger | None = None
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
        return CompanyContext(**data)

    def _load_discovery_output(self) -> DiscoveryOutput | None:
        """Load DiscoveryOutput from checkpoint."""
        data = self._load_checkpoint("stage2_discovery")
        if not data:
            return None

        # Convert nested dicts to proper types
        from er.types import DiscoveredThread, ResearchGroup, ThreadType

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

        return DiscoveryOutput(
            official_segments=data.get("official_segments", []),
            research_threads=threads,
            research_groups=groups,
            cross_cutting_themes=data.get("cross_cutting_themes", []),
            optionality_candidates=data.get("optionality_candidates", []),
            data_gaps=data.get("data_gaps", []),
            conflicting_signals=data.get("conflicting_signals", []),
            evidence_ids=data.get("evidence_ids", []),
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
            # Convert vertical analyses within each group
            vas = []
            for v in g.get("vertical_analyses", []):
                vas.append(VerticalAnalysis(**v))
            g["vertical_analyses"] = vas
            groups.append(GroupResearchOutput(**g))

        # Convert standalone vertical analyses
        verticals = [VerticalAnalysis(**v) for v in vertical_data]

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

    def _get_completed_stages(self) -> set[int]:
        """Determine which stages have completed checkpoints."""
        if not self.config.resume_from_run_dir:
            return set()

        completed = set()
        stage_files = {
            1: "stage1_company_context.json",
            2: "stage2_discovery.json",
            3: "stage3_verticals.json",  # Need both stage3 files
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

    def _emit_progress(
        self,
        stage: int,
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

        try:
            # ============== STAGE 1: Data Orchestrator ==============
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
                self._emit_progress(1, "complete", f"Loaded {company_context.company_name}")

            # ============== STAGE 2: Discovery ==============
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
                self._emit_progress(2, "complete", f"Found {len(discovery_output.research_threads)} research verticals")

            # ============== STAGE 3: Deep Research (2 Parallel Groups) ==============
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
                self._emit_progress(3, "complete", f"Completed {len(vertical_analyses)} vertical analyses")

            # ============== STAGE 4: Dual Synthesis (Parallel) ==============
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
                )
                self._save_stage_output("stage4_claude_synthesis", claude_synthesis)
                self._save_stage_output("stage4_gpt_synthesis", gpt_synthesis)
                self._emit_progress(4, "complete", f"Claude: {claude_synthesis.investment_view} | GPT: {gpt_synthesis.investment_view}")

            # ============== STAGE 5: Editorial Review ==============
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
                self._emit_progress(5, "complete", f"Winner: {editorial_feedback.preferred_synthesis.upper()} ({editorial_feedback.claude_score:.1f} vs {editorial_feedback.gpt_score:.1f})")

            # ============== STAGE 6: Revision ==============
            # Stage 6 always runs (it's the final output)
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

        # Initialize External Discovery agent
        if self._external_discovery_agent is None:
            self._external_discovery_agent = ExternalDiscoveryAgent(self.agent_context)

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
        external_task = asyncio.create_task(
            self._external_discovery_agent.run(
                run_state,
                company_context,
            )
        )

        # Wait for both with proper error handling
        internal_output = None
        external_output = None

        try:
            internal_output, external_output = await asyncio.gather(
                internal_task,
                external_task,
                return_exceptions=True,
            )

            # Handle exceptions
            if isinstance(internal_output, Exception):
                logger.error("Internal discovery failed", error=str(internal_output))
                raise internal_output

            if isinstance(external_output, Exception):
                logger.warning("External discovery failed, using internal only", error=str(external_output))
                # Fall back to internal only
                return internal_output

        except Exception as e:
            # If internal failed, we can't continue
            logger.error("Discovery failed", error=str(e))
            raise

        # Save individual outputs for debugging
        self._save_stage_output("stage2_internal_discovery", internal_output)
        self._save_stage_output("stage2_external_discovery", external_output)

        # Merge the outputs
        merged_output = self._discovery_merger.merge(
            internal_output,
            external_output,
            run_state,
        )

        logger.info(
            "Discovery merge complete",
            ticker=run_state.ticker,
            internal_threads=len(internal_output.research_threads),
            external_variant_perceptions=len(external_output.variant_perceptions),
            external_strategic_shifts=len(external_output.strategic_shifts),
            merged_threads=len(merged_output.research_threads),
        )

        return merged_output

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

        # Run research groups in parallel (2 groups max)
        async def research_group(group: ResearchGroup) -> GroupResearchOutput:
            # Get threads for this group
            threads = discovery_output.get_threads_for_group(group)

            if not threads:
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
                    threads,
                    use_deep_research=self.config.use_deep_research_verticals,
                )
            finally:
                await agent.close()

        # Run both groups in parallel
        group_results = await asyncio.gather(
            *[research_group(g) for g in research_groups[:2]],  # Max 2 groups
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

    async def _run_synthesis(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        discovery_output: DiscoveryOutput,
        vertical_analyses: list[VerticalAnalysis],
    ) -> tuple[SynthesisOutput, SynthesisOutput]:
        """Stage 4: Dual synthesis with Claude and GPT."""
        if self._synthesizer is None:
            self._synthesizer = SynthesizerAgent(self.agent_context)

        return await self._synthesizer.run(
            run_state,
            company_context,
            discovery_output,
            vertical_analyses,
            output_dir=self.config.output_dir,
        )

    async def _run_editorial_review(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        claude_synthesis: SynthesisOutput,
        gpt_synthesis: SynthesisOutput,
    ) -> EditorialFeedback:
        """Stage 5: Editorial review by the Judge.

        The Judge compares both syntheses and produces editorial feedback
        for the winning Synthesizer to revise their report.

        Args:
            run_state: Current run state.
            company_context: Company data context.
            claude_synthesis: Claude's synthesis output.
            gpt_synthesis: GPT's synthesis output.

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

    async def close(self) -> None:
        """Close all agents and resources."""
        if self._data_orchestrator:
            await self._data_orchestrator.close()
            self._data_orchestrator = None
        if self._discovery_agent:
            await self._discovery_agent.close()
            self._discovery_agent = None
        if self._external_discovery_agent:
            await self._external_discovery_agent.close()
            self._external_discovery_agent = None
        if self._discovery_merger:
            await self._discovery_merger.close()
            self._discovery_merger = None
        if self._synthesizer:
            await self._synthesizer.close()
            self._synthesizer = None
        if self._judge:
            await self._judge.close()
            self._judge = None


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
