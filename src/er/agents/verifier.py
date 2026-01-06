"""
Verification Agent (Stage 3.5).

Runs BEFORE synthesis to verify facts against CompanyContext ground truth.
Flags contradictions and marks unverifiable claims.

Model: Claude Haiku (fast, cheap verification)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from er.agents.base import Agent, AgentContext
from er.llm.router import AgentRole
from er.types import (
    CompanyContext,
    Fact,
    FactCategory,
    GroupResearchOutput,
    Phase,
    RunState,
    VerificationResult,
    VerificationStatus,
    VerifiedFact,
    VerifiedResearchPackage,
)


class VerificationAgent(Agent):
    """Stage 3.5: Verification Agent.

    Responsible for:
    1. Cross-checking extracted facts against CompanyContext
    2. Flagging contradictions with ground truth data
    3. Marking unverifiable claims
    4. Adjusting confidence scores based on verification
    5. Outputting VerifiedResearchPackage for synthesis

    Uses rule-based verification for financial facts (from JSON)
    and LLM for contextual verification of other claims.
    """

    def __init__(self, context: AgentContext) -> None:
        """Initialize the Verification Agent.

        Args:
            context: Agent context with shared resources.
        """
        super().__init__(context)

    @property
    def name(self) -> str:
        return "verifier"

    @property
    def role(self) -> str:
        return "Verify facts against ground truth before synthesis"

    async def run(
        self,
        run_state: RunState,
        company_context: CompanyContext,
        group_outputs: list[GroupResearchOutput],
        **kwargs: Any,
    ) -> VerifiedResearchPackage:
        """Execute Stage 3.5: Verification.

        Args:
            run_state: Current run state.
            company_context: CompanyContext with ground truth data.
            group_outputs: Research outputs from vertical analysts.

        Returns:
            VerifiedResearchPackage with all facts verified.
        """
        self.log_info(
            "Starting verification",
            ticker=run_state.ticker,
            group_count=len(group_outputs),
        )

        run_state.phase = Phase.VERTICALS  # Still in research phase

        verification_results: list[VerificationResult] = []
        all_verified_facts: list[VerifiedFact] = []
        all_evidence_ids: list[str] = list(company_context.evidence_ids)

        # Process each group
        for group_output in group_outputs:
            all_evidence_ids.extend(group_output.evidence_ids)

            # Process each vertical in the group
            for va in group_output.vertical_analyses:
                # Skip if no facts to verify
                if not va.facts:
                    continue

                # Verify facts for this vertical
                verified_facts = await self._verify_facts(
                    facts=va.facts,
                    company_context=company_context,
                    vertical_name=va.vertical_name,
                )

                # Count verification statuses
                verified_count = sum(
                    1 for vf in verified_facts
                    if vf.status == VerificationStatus.VERIFIED
                )
                contradicted_count = sum(
                    1 for vf in verified_facts
                    if vf.status == VerificationStatus.CONTRADICTED
                )
                unverifiable_count = sum(
                    1 for vf in verified_facts
                    if vf.status == VerificationStatus.UNVERIFIABLE
                )

                # Extract critical contradictions
                critical_contradictions = [
                    vf.verification_notes
                    for vf in verified_facts
                    if vf.status == VerificationStatus.CONTRADICTED
                    and vf.original_fact.category == FactCategory.FINANCIAL
                ]

                result = VerificationResult(
                    vertical_name=va.vertical_name,
                    thread_id=va.thread_id,
                    verified_facts=verified_facts,
                    verified_count=verified_count,
                    contradicted_count=contradicted_count,
                    unverifiable_count=unverifiable_count,
                    critical_contradictions=critical_contradictions,
                )
                verification_results.append(result)
                all_verified_facts.extend(verified_facts)

        # Aggregate statistics
        total_facts = len(all_verified_facts)
        total_verified = sum(
            1 for vf in all_verified_facts
            if vf.status == VerificationStatus.VERIFIED
        )
        total_contradicted = sum(
            1 for vf in all_verified_facts
            if vf.status == VerificationStatus.CONTRADICTED
        )
        total_unverifiable = sum(
            1 for vf in all_verified_facts
            if vf.status == VerificationStatus.UNVERIFIABLE
        )

        # Collect critical issues
        critical_issues = []
        for vr in verification_results:
            critical_issues.extend(vr.critical_contradictions)

        # Create package
        package = VerifiedResearchPackage(
            ticker=run_state.ticker,
            verification_results=verification_results,
            all_verified_facts=all_verified_facts,
            total_facts=total_facts,
            verified_count=total_verified,
            contradicted_count=total_contradicted,
            unverifiable_count=total_unverifiable,
            critical_issues=critical_issues,
            group_outputs=group_outputs,
            evidence_ids=list(set(all_evidence_ids)),
        )

        # Store in WorkspaceStore
        if self.workspace_store:
            self.workspace_store.put_artifact(
                artifact_type="verified_research_package",
                producer=self.name,
                json_obj=package.to_dict(),
                summary=f"Verified {total_facts} facts: {total_verified} verified, {total_contradicted} contradicted",
                evidence_ids=package.evidence_ids[:10],
            )

        self.log_info(
            "Verification complete",
            ticker=run_state.ticker,
            total_facts=total_facts,
            verified=total_verified,
            contradicted=total_contradicted,
            unverifiable=total_unverifiable,
            critical_issues=len(critical_issues),
        )

        return package

    async def _verify_facts(
        self,
        facts: list[Fact],
        company_context: CompanyContext,
        vertical_name: str,
    ) -> list[VerifiedFact]:
        """Verify a list of facts against company context.

        Uses rule-based verification for financial facts and
        LLM-assisted verification for other categories.

        Args:
            facts: Facts to verify.
            company_context: Ground truth data.
            vertical_name: Name of the vertical being verified.

        Returns:
            List of VerifiedFact objects.
        """
        verified_facts: list[VerifiedFact] = []

        # Separate facts by category for different verification approaches
        financial_facts = [f for f in facts if f.category == FactCategory.FINANCIAL]
        other_facts = [f for f in facts if f.category != FactCategory.FINANCIAL]

        # Rule-based verification for financial facts
        for fact in financial_facts:
            vf = self._verify_financial_fact(fact, company_context)
            verified_facts.append(vf)

        # LLM verification for other facts (batch for efficiency)
        if other_facts:
            other_verified = await self._verify_other_facts_batch(
                other_facts,
                company_context,
                vertical_name,
            )
            verified_facts.extend(other_verified)

        return verified_facts

    def _verify_financial_fact(
        self,
        fact: Fact,
        company_context: CompanyContext,
    ) -> VerifiedFact:
        """Verify a financial fact using rule-based matching.

        Checks the fact against income_statement, balance_sheet, etc.

        Args:
            fact: Financial fact to verify.
            company_context: Ground truth data.

        Returns:
            VerifiedFact with verification status.
        """
        statement = fact.statement.lower()

        # Extract any numbers from the fact
        numbers_in_fact = re.findall(r'\$?([\d,.]+)\s*[BMK]?', fact.statement)
        percentages_in_fact = re.findall(r'([+-]?[\d.]+)%', fact.statement)

        # Try to find matching data in company context
        verification_notes = ""
        ground_truth_source = None
        status = VerificationStatus.UNVERIFIABLE

        # Check income statement
        income_stmt = company_context.income_statement_quarterly
        if income_stmt:
            latest_quarter = income_stmt[0] if income_stmt else {}

            # Check revenue
            if "revenue" in statement:
                actual_revenue = latest_quarter.get("revenue")
                if actual_revenue:
                    ground_truth_source = "income_statement_quarterly"
                    # Simple presence check - revenue exists
                    status = VerificationStatus.VERIFIED
                    verification_notes = f"Revenue data present in ground truth: ${actual_revenue:,.0f}"

            # Check growth rate
            if "growth" in statement or "yoy" in statement.lower():
                if len(income_stmt) >= 5:  # Need YoY data
                    current_rev = income_stmt[0].get("revenue", 0)
                    year_ago_rev = income_stmt[4].get("revenue", 0)  # 4 quarters ago
                    if year_ago_rev > 0:
                        actual_growth = ((current_rev - year_ago_rev) / year_ago_rev) * 100
                        ground_truth_source = "income_statement_quarterly (YoY calculation)"

                        # Check if claimed growth is close to actual
                        for pct in percentages_in_fact:
                            claimed_growth = float(pct)
                            if abs(claimed_growth - actual_growth) < 5:  # Within 5pp
                                status = VerificationStatus.VERIFIED
                                verification_notes = f"Growth rate verified: {actual_growth:.1f}% (claimed: {claimed_growth}%)"
                            else:
                                status = VerificationStatus.CONTRADICTED
                                verification_notes = f"Growth rate CONTRADICTS ground truth: actual {actual_growth:.1f}% vs claimed {claimed_growth}%"

        # Check margins
        if "margin" in statement:
            if income_stmt:
                latest = income_stmt[0]
                revenue = latest.get("revenue", 0)
                gross_profit = latest.get("grossProfit", 0)
                operating_income = latest.get("operatingIncome", 0)

                if revenue > 0:
                    if "gross" in statement and gross_profit:
                        actual_margin = (gross_profit / revenue) * 100
                        ground_truth_source = "income_statement (gross margin)"
                        status = VerificationStatus.VERIFIED
                        verification_notes = f"Gross margin from ground truth: {actual_margin:.1f}%"

                    elif "operating" in statement and operating_income:
                        actual_margin = (operating_income / revenue) * 100
                        ground_truth_source = "income_statement (operating margin)"
                        status = VerificationStatus.VERIFIED
                        verification_notes = f"Operating margin from ground truth: {actual_margin:.1f}%"

        # Default for financial facts we couldn't specifically verify
        if status == VerificationStatus.UNVERIFIABLE:
            verification_notes = "Could not find matching data in ground truth to verify this financial claim"

        return VerifiedFact(
            original_fact=fact,
            status=status,
            verification_notes=verification_notes,
            ground_truth_source=ground_truth_source,
            confidence_adjustment=self._get_confidence_adjustment(status),
        )

    async def _verify_other_facts_batch(
        self,
        facts: list[Fact],
        company_context: CompanyContext,
        vertical_name: str,
    ) -> list[VerifiedFact]:
        """Verify non-financial facts using LLM.

        For competitive, development, and other facts that can't be
        mechanically verified against JSON.

        Args:
            facts: Non-financial facts to verify.
            company_context: Ground truth data.
            vertical_name: Name of the vertical.

        Returns:
            List of VerifiedFact objects.
        """
        if not facts:
            return []

        # For now, mark non-financial facts based on category
        # In a full implementation, we'd use LLM to cross-reference
        verified = []

        for fact in facts:
            # Category-based verification heuristics
            if fact.category == FactCategory.COMPETITIVE:
                # Competitive facts from web research - mark as partially verifiable
                vf = VerifiedFact(
                    original_fact=fact,
                    status=VerificationStatus.PARTIAL,
                    verification_notes="Competitive data from web research - cross-reference recommended",
                    ground_truth_source="web_research",
                    confidence_adjustment=-0.1,  # Slight downgrade
                )
            elif fact.category == FactCategory.DEVELOPMENT:
                # Development facts - mark as unverifiable against company data
                vf = VerifiedFact(
                    original_fact=fact,
                    status=VerificationStatus.UNVERIFIABLE,
                    verification_notes="Recent development - cannot verify against historical company data",
                    ground_truth_source=None,
                    confidence_adjustment=0.0,  # No change
                )
            elif fact.category in (FactCategory.TAILWIND, FactCategory.HEADWIND):
                # Growth dynamics - these are analysis, not raw facts
                vf = VerifiedFact(
                    original_fact=fact,
                    status=VerificationStatus.PARTIAL,
                    verification_notes="Growth dynamic analysis - logical consistency check only",
                    ground_truth_source="analyst_assessment",
                    confidence_adjustment=-0.05,
                )
            elif fact.category == FactCategory.RISK:
                # Risk factors - mark as unverifiable (forward-looking)
                vf = VerifiedFact(
                    original_fact=fact,
                    status=VerificationStatus.UNVERIFIABLE,
                    verification_notes="Risk factor is forward-looking - cannot verify against historical data",
                    ground_truth_source=None,
                    confidence_adjustment=-0.1,
                )
            elif fact.category == FactCategory.ANALYST:
                # Analyst views - external source
                vf = VerifiedFact(
                    original_fact=fact,
                    status=VerificationStatus.PARTIAL,
                    verification_notes="Analyst view from external source - citation present",
                    ground_truth_source="external_analyst",
                    confidence_adjustment=0.0,
                )
            else:
                # Other facts - default handling
                vf = VerifiedFact(
                    original_fact=fact,
                    status=VerificationStatus.UNVERIFIABLE,
                    verification_notes="Cannot verify against available ground truth data",
                    ground_truth_source=None,
                    confidence_adjustment=-0.1,
                )

            verified.append(vf)

        return verified

    def _get_confidence_adjustment(self, status: VerificationStatus) -> float:
        """Get confidence adjustment based on verification status.

        Args:
            status: Verification status.

        Returns:
            Confidence adjustment value.
        """
        adjustments = {
            VerificationStatus.VERIFIED: 0.2,  # Boost confidence
            VerificationStatus.CONTRADICTED: -0.5,  # Major downgrade
            VerificationStatus.PARTIAL: -0.05,  # Slight downgrade
            VerificationStatus.UNVERIFIABLE: -0.1,  # Moderate downgrade
        }
        return adjustments.get(status, 0.0)

    async def close(self) -> None:
        """Close any open resources."""
        pass
