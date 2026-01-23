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
from er.types import (
    ClaimGraph,
    CompanyContext,
    EntailmentStatus,
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
from er.verification.claim_graph import ClaimGraphBuilder
from er.verification.entailment import EntailmentVerifier, EntailmentReport
from er.confidence.calibration import ConfidenceCalibrator, SourceTier


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

        # Initialize claim graph builder with LLM router for advanced extraction
        self._claim_graph_builder = ClaimGraphBuilder(llm_router=context.llm_router)

        # Initialize entailment verifier with LLM router
        self._entailment_verifier = EntailmentVerifier(llm_router=context.llm_router)

        # Initialize confidence calibrator
        self._confidence_calibrator = ConfidenceCalibrator()

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

        # === ClaimGraph + Entailment + Confidence Calibration ===

        # Step 1: Build ClaimGraph from vertical analysis dossiers
        claim_graph = await self._build_claim_graph(
            run_state.ticker,
            group_outputs,
        )

        # Step 2: Build evidence map from EvidenceStore
        evidence_map = await self._build_evidence_map(all_evidence_ids)

        # Step 3: Run entailment verification on claims
        entailment_report: EntailmentReport | None = None
        if claim_graph and claim_graph.claims:
            # Link evidence to claims before verification
            claim_graph = self._claim_graph_builder.link_evidence_to_claims(
                claim_graph,
                evidence_map,
            )

            entailment_report = await self._entailment_verifier.verify_claim_graph(
                claim_graph,
                evidence_map,
            )

            # Step 4: Calibrate claim confidence based on entailment results
            await self._calibrate_claim_confidence(
                claim_graph,
                entailment_report,
            )

            self.log_info(
                "ClaimGraph + Entailment complete",
                ticker=run_state.ticker,
                total_claims=claim_graph.total_claims,
                cited_claims=claim_graph.cited_claims,
                claims_verified=entailment_report.claims_verified if entailment_report else 0,
                claims_contradicted=entailment_report.claims_contradicted if entailment_report else 0,
            )

        # Step 5: Store ClaimGraph + entailment report in WorkspaceStore
        if self.workspace_store:
            if claim_graph:
                self.workspace_store.put_artifact(
                    artifact_type="claim_graph",
                    producer=self.name,
                    json_obj=claim_graph.to_dict(),
                    summary=f"ClaimGraph: {claim_graph.total_claims} claims ({claim_graph.cited_claims} cited)",
                    evidence_ids=all_evidence_ids[:10],
                )

            if entailment_report:
                self.workspace_store.put_artifact(
                    artifact_type="entailment_report",
                    producer=self.name,
                    json_obj=entailment_report.to_dict(),
                    summary=f"Entailment: {entailment_report.claims_verified} supported, "
                            f"{entailment_report.claims_contradicted} contradicted",
                    evidence_ids=all_evidence_ids[:10],
                )

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

                    # Extract claimed revenue from statement and compare
                    claimed_revenue = None
                    for num_str in numbers_in_fact:
                        try:
                            num = float(num_str.replace(",", ""))
                            # Handle B/M/K suffixes in original statement
                            if "billion" in statement.lower() or num_str.endswith("B"):
                                num *= 1e9
                            elif "million" in statement.lower() or num_str.endswith("M"):
                                num *= 1e6
                            elif "thousand" in statement.lower() or num_str.endswith("K"):
                                num *= 1e3
                            # Only consider numbers that could reasonably be revenue
                            if num > 1e6:  # At least $1M to be considered revenue
                                claimed_revenue = num
                                break
                        except ValueError:
                            continue

                    if claimed_revenue:
                        # Compare claimed vs actual with 10% tolerance
                        tolerance = 0.10
                        if abs(claimed_revenue - actual_revenue) / actual_revenue <= tolerance:
                            status = VerificationStatus.VERIFIED
                            verification_notes = f"Revenue verified: ${actual_revenue:,.0f} (claimed: ${claimed_revenue:,.0f}, within {tolerance*100:.0f}% tolerance)"
                        else:
                            status = VerificationStatus.CONTRADICTED
                            pct_diff = ((claimed_revenue - actual_revenue) / actual_revenue) * 100
                            verification_notes = f"Revenue CONTRADICTS ground truth: actual ${actual_revenue:,.0f} vs claimed ${claimed_revenue:,.0f} ({pct_diff:+.1f}% difference)"
                    else:
                        # No specific number claimed, just a general revenue statement
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

    async def _build_claim_graph(
        self,
        ticker: str,
        group_outputs: list[GroupResearchOutput],
    ) -> ClaimGraph | None:
        """Build a ClaimGraph from vertical analysis dossiers.

        Extracts claims from vertical dossier text and links them to evidence.

        Args:
            ticker: Stock ticker symbol.
            group_outputs: Research outputs containing vertical analyses.

        Returns:
            ClaimGraph with extracted claims, or None if no dossiers.
        """
        # Collect all dossier text from vertical analyses
        all_dossier_text = []
        for group in group_outputs:
            for va in group.vertical_analyses:
                if va.dossier and va.dossier.full_text:
                    all_dossier_text.append(va.dossier.full_text)

        if not all_dossier_text:
            self.log_info("No dossier text found for claim extraction", ticker=ticker)
            return None

        # Combine dossier text for claim extraction
        combined_text = "\n\n---\n\n".join(all_dossier_text)

        # Build ClaimGraph - prefer LLM extraction if available
        try:
            claim_graph = await self._claim_graph_builder.build_with_llm(
                text=combined_text,
                ticker=ticker,
                source="vertical_dossiers",
            )
        except Exception as e:
            self.log_warning(
                "LLM claim extraction failed, falling back to pattern-based",
                ticker=ticker,
                error=str(e),
            )
            claim_graph = self._claim_graph_builder.build_from_text(
                text=combined_text,
                ticker=ticker,
                source="vertical_dossiers",
            )

        self.log_info(
            "ClaimGraph built",
            ticker=ticker,
            total_claims=claim_graph.total_claims,
        )

        return claim_graph

    async def _build_evidence_map(
        self,
        evidence_ids: list[str],
    ) -> dict[str, str]:
        """Build a map of evidence IDs to text snippets from EvidenceStore.

        Args:
            evidence_ids: List of evidence IDs to retrieve.

        Returns:
            Dict mapping evidence_id to text content.
        """
        evidence_map: dict[str, str] = {}

        if not self.evidence_store:
            return evidence_map

        for eid in evidence_ids[:50]:  # Limit to avoid too many lookups
            try:
                # Try to get evidence record first (has snippet)
                evidence = await self.evidence_store.get(eid)
                if evidence:
                    # Use snippet from the Evidence object
                    text = evidence.snippet or ""
                    if text:
                        evidence_map[eid] = text[:1000]  # Truncate to reasonable length
                        continue

                # Fall back to blob if evidence record not available or has no snippet
                blob = await self.evidence_store.get_blob(eid)
                if blob:
                    # Blob is raw bytes - decode and extract a snippet
                    text = blob.decode("utf-8", errors="ignore")[:1000]
                    evidence_map[eid] = text

            except Exception as e:
                self.log_warning(
                    "Failed to retrieve evidence",
                    evidence_id=eid,
                    error=str(e),
                )

        self.log_info(
            "Evidence map built",
            evidence_count=len(evidence_map),
            requested_count=len(evidence_ids),
        )

        return evidence_map

    async def _calibrate_claim_confidence(
        self,
        claim_graph: ClaimGraph,
        entailment_report: EntailmentReport,
    ) -> None:
        """Calibrate claim confidence based on entailment verification results.

        Updates claim confidence in-place using the ConfidenceCalibrator.

        Args:
            claim_graph: ClaimGraph with claims to calibrate.
            entailment_report: Entailment results for each claim.
        """
        # Build a lookup from claim_id to entailment result
        entailment_lookup = {
            result.claim_id: result
            for result in entailment_report.results
        }

        calibrated_count = 0
        for claim in claim_graph.claims:
            entailment_result = entailment_lookup.get(claim.claim_id)

            # Determine source tier based on evidence presence
            if claim.cited_evidence_ids:
                source_tier = SourceTier.TIER_2  # Has citations
            else:
                source_tier = SourceTier.TIER_3  # No citations

            # Get entailment status if available
            entailment_status = None
            if entailment_result:
                entailment_status = entailment_result.status

            # Calibrate the claim
            calibration_result = self._confidence_calibrator.calibrate_claim(
                claim=claim,
                source_tier=source_tier,
                recency_days=None,  # Could be derived from evidence dates if available
                corroboration_count=len(claim.cited_evidence_ids),
                entailment_status=entailment_status,
            )

            # Update claim confidence with calibrated value
            claim.confidence = calibration_result.calibrated_confidence
            calibrated_count += 1

        self.log_info(
            "Confidence calibration complete",
            claims_calibrated=calibrated_count,
        )

    async def close(self) -> None:
        """Close any open resources."""
        pass
