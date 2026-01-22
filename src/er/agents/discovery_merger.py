"""
Discovery Merger (Stage 2C).

Combines Internal Discovery and External Discovery outputs into a unified
DiscoveryOutput for downstream stages.

Uses a lightweight model to prioritize and deduplicate threads.
"""

from __future__ import annotations

import json
from dataclasses import field
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.agents.external_discovery import ExternalDiscoveryOutput
from er.llm.base import LLMRequest
from er.types import (
    DiscoveredThread,
    DiscoveryOutput,
    ResearchGroup,
    RunState,
    ThreadBrief,
    ThreadType,
    generate_id,
)


class DiscoveryMerger(Agent):
    """Stage 2C: Discovery Merger.

    Responsible for:
    1. Combining Internal Discovery (company data) with External Discovery (market context)
    2. Deduplicating and prioritizing research threads
    3. Identifying variant perceptions (where internal vs external differ)
    4. Assigning threads to research groups

    Uses a lightweight model (Haiku) for fast merging.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Discovery Merger.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)

    @property
    def name(self) -> str:
        return "discovery_merger"

    @property
    def role(self) -> str:
        return "Merge internal and external discovery outputs"

    def merge(
        self,
        internal: DiscoveryOutput,
        external: ExternalDiscoveryOutput | list[ExternalDiscoveryOutput],
        run_state: RunState,
    ) -> DiscoveryOutput:
        """Merge internal and external discovery outputs.

        This is a deterministic merge - no LLM call needed for simple cases.
        Uses heuristics to combine and prioritize threads.

        Args:
            internal: Output from Internal Discovery (company data focus).
            external: Output(s) from External Discovery (market context focus).
            run_state: Current run state.

        Returns:
            Merged DiscoveryOutput with all threads and groups.
        """
        external_outputs = self._normalize_external_outputs(external)
        combined_external = self._combine_external_outputs(external_outputs)

        self.log_info(
            "Merging discovery outputs",
            ticker=run_state.ticker,
            internal_threads=len(internal.research_threads),
            external_variant_perceptions=len(combined_external.variant_perceptions),
            external_suggested_threads=len(combined_external.suggested_threads),
        )

        # Start with internal threads
        merged_threads: list[DiscoveredThread] = list(internal.research_threads)

        # Convert external strategic shifts to threads (HIGHEST PRIORITY - business model changes)
        for i, shift in enumerate(combined_external.strategic_shifts):
            description = shift.get("description", f"Strategic shift {i+1}")
            shift_type = shift.get("shift_type", "unknown")

            # Check if already covered
            already_covered = any(
                description.lower() in t.description.lower() or t.description.lower() in description.lower()
                for t in merged_threads
            )

            if not already_covered and shift.get("materiality", "low") in ["high", "medium"]:
                thread = DiscoveredThread.create(
                    name=f"[SHIFT] {description[:50]}",
                    description=f"Strategic Shift ({shift_type}): {description}. Competitive implication: {shift.get('competitive_implication', '')}",
                    thread_type=ThreadType.CROSS_CUTTING,
                    priority=1,  # HIGHEST priority for strategic shifts
                    discovery_lens="external_strategic_shift",
                    is_official_segment=False,
                    value_driver_hypothesis=shift.get("competitive_implication", ""),
                    research_questions=[
                        f"What is the revenue/margin impact of this shift: {description}?",
                        f"Is this priced in? Current assessment: {shift.get('is_priced_in', 'unknown')}",
                        f"How does this change the competitive position?",
                        f"What is the addressable market for this new business?",
                    ],
                    evidence_ids=list(combined_external.evidence_ids),
                )
                merged_threads.append(thread)

        # Convert external variant perceptions to threads
        for i, vp in enumerate(combined_external.variant_perceptions):
            topic = vp.get("topic", f"Variant {i+1}")

            # Check if this variant perception is already covered by an internal thread
            already_covered = any(
                topic.lower() in t.name.lower() or t.name.lower() in topic.lower()
                for t in merged_threads
            )

            if not already_covered:
                thread = DiscoveredThread.create(
                    name=f"[VP] {topic}",
                    description=f"Variant Perception: {vp.get('variant_view', '')}. Consensus: {vp.get('consensus_view', '')}",
                    thread_type=ThreadType.CROSS_CUTTING,
                    priority=2,  # High priority for variant perceptions
                    discovery_lens="external_variant_perception",
                    is_official_segment=False,
                    value_driver_hypothesis=vp.get("variant_view", ""),
                    research_questions=[
                        f"Is the consensus view correct: {vp.get('consensus_view', '')}?",
                        f"What evidence supports the variant view: {vp.get('variant_view', '')}?",
                        f"What would trigger a re-rating: {vp.get('trigger_event', '')}?",
                    ],
                    evidence_ids=list(combined_external.evidence_ids),
                )
                merged_threads.append(thread)

        # Convert external suggested threads
        for st in combined_external.suggested_threads:
            name = st.get("name", "Unknown")

            # Check if already covered
            already_covered = any(
                name.lower() in t.name.lower() or t.name.lower() in name.lower()
                for t in merged_threads
            )

            if not already_covered:
                thread = DiscoveredThread.create(
                    name=f"[EXT] {name}",
                    description=st.get("why_it_matters", ""),
                    thread_type=ThreadType.CROSS_CUTTING,
                    priority=st.get("priority", 3),
                    discovery_lens=st.get("source_lens", "external"),
                    is_official_segment=False,
                    value_driver_hypothesis=st.get("why_it_matters", ""),
                    research_questions=st.get("research_questions", []),
                    evidence_ids=list(combined_external.evidence_ids),
                )
                merged_threads.append(thread)

        # Merge cross-cutting themes
        merged_themes = list(internal.cross_cutting_themes)
        for context_item in combined_external.critical_external_context:
            if context_item not in merged_themes:
                merged_themes.append(f"[External] {context_item}")

        # Add competitor insights as themes
        for cd in combined_external.competitor_developments[:3]:  # Top 3 competitors
            competitor = cd.get("competitor", "Unknown")
            announcement = cd.get("announcement", "")
            if announcement:
                theme = f"Competitive: {competitor} - {announcement[:100]}"
                if theme not in merged_themes:
                    merged_themes.append(theme)

        # Merge optionality candidates
        merged_optionality = list(internal.optionality_candidates)
        for vp in combined_external.variant_perceptions:
            topic = vp.get("topic", "")
            if topic and topic not in merged_optionality:
                merged_optionality.append(f"[VP] {topic}")

        # Merge data gaps
        merged_gaps = list(internal.data_gaps)
        # Add key unanswered questions from external
        analyst_sentiment = combined_external.analyst_sentiment
        if analyst_sentiment.get("key_debates"):
            for debate in analyst_sentiment["key_debates"]:
                merged_gaps.append(f"[Analyst Debate] {debate}")

        # Merge conflicting signals
        merged_conflicts = list(internal.conflicting_signals)
        # If analyst sentiment differs from internal view, flag it
        consensus = analyst_sentiment.get("consensus", "")
        if consensus:
            merged_conflicts.append(f"Analyst consensus is {consensus} - validate against internal analysis")

        # Re-create research groups with merged threads
        # Strategy: Keep internal groups but add external threads to appropriate group
        merged_groups = []

        if internal.research_groups:
            # Clone existing groups
            for group in internal.research_groups:
                new_group = ResearchGroup(
                    group_id=group.group_id,
                    name=group.name,
                    theme=group.theme,
                    vertical_ids=list(group.vertical_ids),
                    key_questions=list(group.key_questions),
                    grouping_rationale=group.grouping_rationale,
                    shared_context=group.shared_context,
                    valuation_approach=group.valuation_approach,
                    focus=group.focus,
                )
                merged_groups.append(new_group)

            # Add new threads to Group 2 (Growth & Optionality) or create new group
            external_thread_ids = [
                t.thread_id for t in merged_threads
                if t.thread_id not in [tid for g in internal.research_groups for tid in g.vertical_ids]
            ]

            if external_thread_ids:
                if len(merged_groups) >= 2:
                    # Add to second group (typically Growth & Optionality)
                    merged_groups[1].vertical_ids.extend(external_thread_ids)
                    merged_groups[1].theme += " + External Insights"
                else:
                    # Create new group for external threads
                    external_group = ResearchGroup(
                        group_id=generate_id("group"),
                        name="External & Competitive Context",
                        theme="Insights from external research - competitors, market discourse, variant perceptions",
                        vertical_ids=external_thread_ids,
                        key_questions=[
                            "What are competitors doing that affects us?",
                            "Where does consensus appear to be wrong?",
                            "What external factors could change the investment thesis?",
                        ],
                        grouping_rationale="Threads discovered through external market research",
                        shared_context="External context that may not be reflected in company data",
                        valuation_approach="Mixed",
                        focus="Validate or refute consensus views",
                    )
                    merged_groups.append(external_group)
        else:
            # No groups from internal - create default groups
            merged_groups = self._create_default_groups(merged_threads)

        # Merge evidence IDs
        merged_evidence = list(internal.evidence_ids) + list(combined_external.evidence_ids)

        # Merge ThreadBriefs from internal discovery
        merged_thread_briefs: list[ThreadBrief] = list(internal.thread_briefs)

        # Generate ThreadBriefs for externally-added threads
        for thread in merged_threads:
            # Skip if already has a brief (internal threads)
            if any(b.thread_id == thread.thread_id for b in merged_thread_briefs):
                continue

            # Generate brief for externally-sourced threads
            if "[VP]" in thread.name or "[SHIFT]" in thread.name or "[EXT]" in thread.name:
                brief = ThreadBrief(
                    thread_id=thread.thread_id,
                    rationale=thread.description,
                    hypotheses=[thread.value_driver_hypothesis] if thread.value_driver_hypothesis else [],
                    key_questions=thread.research_questions,
                    required_evidence=["External market research", "Competitor analysis"],
                    key_evidence_ids=list(combined_external.evidence_ids[:5]),
                    confidence=0.6 if "[VP]" in thread.name else 0.5,
                )
                merged_thread_briefs.append(brief)

        # Create merged output
        merged_output = DiscoveryOutput(
            official_segments=internal.official_segments,
            research_threads=merged_threads,
            research_groups=merged_groups,
            cross_cutting_themes=merged_themes,
            optionality_candidates=merged_optionality,
            data_gaps=merged_gaps,
            conflicting_signals=merged_conflicts,
            evidence_ids=merged_evidence,
            thread_briefs=merged_thread_briefs,
            searches_performed=getattr(internal, "searches_performed", []),
        )

        # Store merged ThreadBriefs in WorkspaceStore
        if self.workspace_store:
            # Store only the newly created briefs (externally-added threads)
            for brief in merged_thread_briefs:
                if brief not in internal.thread_briefs:
                    self.workspace_store.put_artifact(
                        artifact_type="thread_brief",
                        producer=self.name,
                        json_obj=brief.to_dict(),
                        summary=f"Merged ThreadBrief: {brief.rationale[:100]}...",
                        evidence_ids=brief.key_evidence_ids,
                    )

        self.log_info(
            "Merge complete",
            ticker=run_state.ticker,
            total_threads=len(merged_threads),
            total_groups=len(merged_groups),
            thread_briefs=len(merged_thread_briefs),
            variant_perceptions_added=len([t for t in merged_threads if "[VP]" in t.name]),
        )

        return merged_output

    def _normalize_external_outputs(
        self,
        external: ExternalDiscoveryOutput | list[ExternalDiscoveryOutput],
    ) -> list[ExternalDiscoveryOutput]:
        if isinstance(external, list):
            return external
        return [external]

    def _combine_external_outputs(
        self,
        externals: list[ExternalDiscoveryOutput],
    ) -> ExternalDiscoveryOutput:
        """Combine multiple external discovery outputs into one."""
        if not externals:
            return ExternalDiscoveryOutput(
                competitor_developments=[],
                industry_news=[],
                analyst_sentiment={},
                market_discourse={},
                strategic_shifts=[],
                variant_perceptions=[],
                suggested_threads=[],
                critical_external_context=[],
                searches_performed=[],
                evidence_ids=[],
                mode="combined",
            )

        def dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for item in items:
                key = json.dumps(item, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            return deduped

        def merge_list_field(field_name: str) -> list[dict[str, Any]]:
            combined: list[dict[str, Any]] = []
            for output in externals:
                combined.extend(getattr(output, field_name, []) or [])
            return dedupe_dicts(combined)

        def merge_text_list(field_name: str) -> list[str]:
            combined: list[str] = []
            for output in externals:
                combined.extend(getattr(output, field_name, []) or [])
            return list(dict.fromkeys(combined))

        def merge_analyst_sentiment() -> dict[str, Any]:
            merged: dict[str, Any] = {}
            for output in externals:
                sentiment = output.analyst_sentiment or {}
                if not sentiment:
                    continue
                if not merged:
                    merged = dict(sentiment)
                    continue
                merged_changes = merged.get("recent_changes", []) or []
                merged_changes.extend(sentiment.get("recent_changes", []) or [])
                merged["recent_changes"] = dedupe_dicts(merged_changes)
                merged_debates = merged.get("key_debates", []) or []
                for debate in sentiment.get("key_debates", []) or []:
                    if debate not in merged_debates:
                        merged_debates.append(debate)
                merged["key_debates"] = merged_debates
                for key in ["consensus", "average_rating", "bull_thesis", "bear_thesis"]:
                    if not merged.get(key) and sentiment.get(key):
                        merged[key] = sentiment.get(key)
            return merged

        def merge_market_discourse() -> dict[str, Any]:
            merged: dict[str, Any] = {}
            for output in externals:
                discourse = output.market_discourse or {}
                if not discourse:
                    continue
                if not merged:
                    merged = dict(discourse)
                    continue
                merged_stories = merged.get("major_stories", []) or []
                merged_stories.extend(discourse.get("major_stories", []) or [])
                merged["major_stories"] = dedupe_dicts(merged_stories)
                merged_controversies = merged.get("controversies", []) or []
                for item in discourse.get("controversies", []) or []:
                    if item not in merged_controversies:
                        merged_controversies.append(item)
                merged["controversies"] = merged_controversies
                if not merged.get("retail_sentiment") and discourse.get("retail_sentiment"):
                    merged["retail_sentiment"] = discourse.get("retail_sentiment")
                merged_viral = merged.get("viral_topics", []) or []
                for item in discourse.get("viral_topics", []) or []:
                    if item not in merged_viral:
                        merged_viral.append(item)
                merged["viral_topics"] = merged_viral
            return merged

        evidence_ids: list[str] = []
        searches_performed: list[dict[str, str]] = []
        analysis_date = ""
        for output in externals:
            evidence_ids.extend(output.evidence_ids or [])
            searches_performed.extend(output.searches_performed or [])
            if not analysis_date and output.analysis_date:
                analysis_date = output.analysis_date

        return ExternalDiscoveryOutput(
            competitor_developments=merge_list_field("competitor_developments"),
            industry_news=merge_list_field("industry_news"),
            analyst_sentiment=merge_analyst_sentiment(),
            market_discourse=merge_market_discourse(),
            strategic_shifts=merge_list_field("strategic_shifts"),
            variant_perceptions=merge_list_field("variant_perceptions"),
            suggested_threads=merge_list_field("suggested_threads"),
            critical_external_context=merge_text_list("critical_external_context"),
            searches_performed=searches_performed,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            analysis_date=analysis_date,
            mode="combined",
        )

    def _create_default_groups(
        self,
        threads: list[DiscoveredThread],
    ) -> list[ResearchGroup]:
        """Create default research groups if none exist.

        Splits threads into Core Business and Growth/External groups.
        """
        if not threads:
            return []

        # Split into core and growth/external
        core_threads = []
        growth_threads = []

        for t in threads:
            if t.is_official_segment or t.thread_type == ThreadType.SEGMENT:
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
                vertical_ids=[t.thread_id for t in core_threads],
                key_questions=["What is the growth outlook?", "How sustainable is the competitive position?"],
                grouping_rationale="Official segments and established businesses",
                shared_context="Core revenue and margin drivers",
                valuation_approach="DCF",
                focus="Analyze competitive position, growth trajectory, and margin profile",
            ))

        if growth_threads:
            groups.append(ResearchGroup(
                group_id=generate_id("group"),
                name="Growth, Optionality & External",
                theme="Emerging businesses, strategic bets, and external insights",
                vertical_ids=[t.thread_id for t in growth_threads],
                key_questions=["What is the potential upside?", "What are the key risks?", "Where is consensus wrong?"],
                grouping_rationale="Growth initiatives, optionality, and externally-sourced insights",
                shared_context="Future growth potential and market perception",
                valuation_approach="Mixed",
                focus="Assess growth potential, TAM, and probability of success",
            ))

        return groups

    async def run(self, run_state: RunState, **kwargs: Any) -> DiscoveryOutput:
        """Execute the merger.

        This is a wrapper around merge() to satisfy the Agent interface.
        Requires 'internal' and 'external' kwargs.

        Args:
            run_state: Current run state.
            internal: Internal discovery output.
            external: External discovery output(s).

        Returns:
            Merged DiscoveryOutput.
        """
        internal = kwargs.get("internal")
        external = kwargs.get("external")

        if internal is None or external is None:
            raise ValueError("DiscoveryMerger.run requires 'internal' and 'external' kwargs")

        return self.merge(internal, external, run_state)

    async def close(self) -> None:
        """Close any resources."""
        pass
