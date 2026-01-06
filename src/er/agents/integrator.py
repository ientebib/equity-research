"""
Integrator Agent (Stage 3.75).

Runs AFTER verification but BEFORE synthesis to find cross-vertical patterns.
Identifies dependencies, synergies, and shared risks across verticals.

Model: Claude Haiku (fast, cheap pattern finding)
"""

from __future__ import annotations

import json
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.router import AgentRole
from er.types import (
    CrossVerticalInsight,
    CrossVerticalMap,
    Fact,
    FactCategory,
    GroupResearchOutput,
    Phase,
    RelationshipType,
    RunState,
    SharedRisk,
    VerifiedFact,
    VerifiedResearchPackage,
    VerticalAnalysis,
    VerticalRelationship,
)


# Prompt for cross-vertical integration
INTEGRATION_PROMPT = """You are an Integration Agent for equity research. Your job is to find cross-vertical patterns.

## COMPANY
{ticker} - {company_name}

## VERTICALS RESEARCHED
{verticals_summary}

## VERIFIED FACTS (Key facts from research)
{facts_summary}

## YOUR TASK

Analyze the verticals and facts above to identify:

1. **Dependencies**: Which verticals depend on others?
   - Example: "Cloud revenue depends on AI infrastructure investments"
   - Example: "Hardware sales drive Services attach rate"

2. **Synergies**: Which verticals reinforce each other?
   - Example: "Search data improves AI models which improve Search"
   - Example: "More users -> more data -> better ads -> more revenue -> more users"

3. **Shared Risks**: What risks affect multiple verticals?
   - Example: "Regulatory scrutiny affects Ads, Search, and Cloud"
   - Example: "Currency headwinds affect all international revenue"

4. **Foundational Verticals**: Which verticals are most critical (others depend on them)?

## OUTPUT FORMAT

Return JSON:
```json
{{
  "relationships": [
    {{
      "source_vertical": "Cloud",
      "target_vertical": "AI Infrastructure",
      "relationship_type": "dependency|synergy|competition|shared_risk|cannibalization",
      "description": "Cloud growth requires continued AI infrastructure investment",
      "strength": "high|medium|low",
      "supporting_facts": ["Cloud capex up 40% in Q3"]
    }}
  ],
  "shared_risks": [
    {{
      "risk_description": "Regulatory scrutiny on AI",
      "affected_verticals": ["Search", "Cloud", "Ads"],
      "severity": "high|medium|low",
      "probability": "high|medium|low",
      "mitigation_notes": "Diverse revenue streams provide some protection"
    }}
  ],
  "cross_vertical_insights": [
    {{
      "insight": "AI is the connective tissue across all verticals",
      "related_verticals": ["Search", "Cloud", "Ads", "AI Infrastructure"],
      "implication": "AI execution is the key swing factor for thesis",
      "confidence": 0.8
    }}
  ],
  "key_dependencies": [
    "Cloud depends on AI Infrastructure",
    "Ads revenue depends on Search market share"
  ],
  "foundational_verticals": ["Search", "AI Infrastructure"]
}}
```

Be specific. Use actual vertical names from the input. Cite facts where possible.
Output ONLY valid JSON."""


class IntegratorAgent(Agent):
    """Stage 3.75: Integrator Agent.

    Responsible for:
    1. Finding cross-vertical dependencies
    2. Identifying synergies and reinforcing dynamics
    3. Mapping shared risks across verticals
    4. Determining foundational verticals
    5. Outputting CrossVerticalMap for synthesis

    Uses LLM to find patterns across verticals.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Integrator Agent.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)

    @property
    def name(self) -> str:
        return "integrator"

    @property
    def role(self) -> str:
        return "Find cross-vertical patterns and dependencies"

    async def run(
        self,
        run_state: RunState,
        verified_package: VerifiedResearchPackage,
        company_name: str = "",
        **kwargs: Any,
    ) -> CrossVerticalMap:
        """Execute Stage 3.75: Integration.

        Args:
            run_state: Current run state.
            verified_package: Output from verification agent.
            company_name: Company name for context.

        Returns:
            CrossVerticalMap with cross-vertical patterns.
        """
        self.log_info(
            "Starting integration",
            ticker=run_state.ticker,
            verticals=len(verified_package.verification_results),
        )

        run_state.phase = Phase.VERTICALS

        # Build summaries for prompt
        verticals_summary = self._build_verticals_summary(verified_package)
        facts_summary = self._build_facts_summary(verified_package)

        # Build prompt
        prompt = INTEGRATION_PROMPT.format(
            ticker=run_state.ticker,
            company_name=company_name or run_state.ticker,
            verticals_summary=verticals_summary,
            facts_summary=facts_summary,
        )

        # Call LLM for pattern finding
        response = await self.llm_router.call(
            role=AgentRole.OUTPUT,  # Use cheap model
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        # Parse response
        cross_map = self._parse_response(
            response.get("content", ""),
            run_state.ticker,
            verified_package.evidence_ids,
        )

        # Store in WorkspaceStore
        if self.workspace_store:
            self.workspace_store.put_artifact(
                artifact_type="cross_vertical_map",
                producer=self.name,
                json_obj=cross_map.to_dict(),
                summary=f"Found {len(cross_map.relationships)} relationships, {len(cross_map.shared_risks)} shared risks",
                evidence_ids=cross_map.evidence_ids[:10],
            )

        self.log_info(
            "Integration complete",
            ticker=run_state.ticker,
            relationships=len(cross_map.relationships),
            shared_risks=len(cross_map.shared_risks),
            insights=len(cross_map.cross_vertical_insights),
        )

        return cross_map

    def _build_verticals_summary(self, package: VerifiedResearchPackage) -> str:
        """Build summary of verticals for prompt."""
        lines = []
        for vr in package.verification_results:
            lines.append(f"- **{vr.vertical_name}**: {vr.verified_count} verified facts, {vr.contradicted_count} contradictions")
        return "\n".join(lines) if lines else "(No verticals found)"

    def _build_facts_summary(self, package: VerifiedResearchPackage) -> str:
        """Build summary of key facts for prompt."""
        lines = []

        # Group facts by vertical
        for vr in package.verification_results:
            vertical_facts = []
            for vf in vr.verified_facts[:5]:  # Limit to 5 facts per vertical
                status_icon = {
                    "verified": "+",
                    "contradicted": "!",
                    "partial": "~",
                    "unverifiable": "?"
                }.get(vf.status.value, "?")
                vertical_facts.append(f"  [{status_icon}] {vf.original_fact.statement[:100]}...")

            if vertical_facts:
                lines.append(f"\n**{vr.vertical_name}**:")
                lines.extend(vertical_facts)

        return "\n".join(lines) if lines else "(No facts to summarize)"

    def _parse_response(
        self,
        content: str,
        ticker: str,
        evidence_ids: list[str],
    ) -> CrossVerticalMap:
        """Parse LLM response into CrossVerticalMap.

        Args:
            content: Raw LLM response.
            ticker: Company ticker.
            evidence_ids: Evidence IDs from research.

        Returns:
            Parsed CrossVerticalMap.
        """
        try:
            # Extract JSON
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            else:
                start = content.find("{")
                end = content.rfind("}") + 1
                json_str = content[start:end]

            data = json.loads(json_str)

        except (json.JSONDecodeError, ValueError) as e:
            self.log_warning(f"Failed to parse integration response: {e}")
            return CrossVerticalMap(
                ticker=ticker,
                relationships=[],
                shared_risks=[],
                cross_vertical_insights=[],
                key_dependencies=[],
                foundational_verticals=[],
                evidence_ids=evidence_ids,
            )

        # Parse relationships
        relationships = []
        for r in data.get("relationships", []):
            try:
                rel_type = RelationshipType(r.get("relationship_type", "dependency"))
            except ValueError:
                rel_type = RelationshipType.DEPENDENCY

            relationships.append(VerticalRelationship(
                source_vertical=r.get("source_vertical", ""),
                target_vertical=r.get("target_vertical", ""),
                relationship_type=rel_type,
                description=r.get("description", ""),
                strength=r.get("strength", "medium"),
                supporting_facts=r.get("supporting_facts", []),
            ))

        # Parse shared risks
        shared_risks = []
        for sr in data.get("shared_risks", []):
            shared_risks.append(SharedRisk(
                risk_description=sr.get("risk_description", ""),
                affected_verticals=sr.get("affected_verticals", []),
                severity=sr.get("severity", "medium"),
                probability=sr.get("probability", "medium"),
                mitigation_notes=sr.get("mitigation_notes"),
            ))

        # Parse cross-vertical insights
        insights = []
        for cvi in data.get("cross_vertical_insights", []):
            insights.append(CrossVerticalInsight(
                insight=cvi.get("insight", ""),
                related_verticals=cvi.get("related_verticals", []),
                implication=cvi.get("implication", ""),
                confidence=cvi.get("confidence", 0.5),
            ))

        return CrossVerticalMap(
            ticker=ticker,
            relationships=relationships,
            shared_risks=shared_risks,
            cross_vertical_insights=insights,
            key_dependencies=data.get("key_dependencies", []),
            foundational_verticals=data.get("foundational_verticals", []),
            evidence_ids=evidence_ids,
        )

    async def close(self) -> None:
        """Close any open resources."""
        pass
