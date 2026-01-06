"""
Entailment Verifier for claim verification.

Uses NLI-style checking to determine if evidence supports claims.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from er.types import (
    Claim,
    ClaimGraph,
    EntailmentStatus,
)


@dataclass
class EntailmentResult:
    """Result of verifying a single claim against evidence."""

    claim_id: str
    status: EntailmentStatus
    confidence: float
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "reasoning": self.reasoning,
        }


@dataclass
class EntailmentReport:
    """Report of verifying all claims in a ClaimGraph."""

    claim_graph: ClaimGraph
    results: list[EntailmentResult]
    overall_confidence: float
    claims_verified: int
    claims_contradicted: int
    claims_unverified: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "claim_graph": self.claim_graph.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "overall_confidence": self.overall_confidence,
            "claims_verified": self.claims_verified,
            "claims_contradicted": self.claims_contradicted,
            "claims_unverified": self.claims_unverified,
        }


class EntailmentVerifier:
    """Verifies claims against evidence using NLI-style entailment.

    Determines if evidence:
    - SUPPORTED: Evidence backs the claim
    - WEAK: Some support but not conclusive
    - UNSUPPORTED: Evidence doesn't address the claim
    - CONTRADICTED: Evidence refutes the claim
    """

    def __init__(self, llm_router: Any = None) -> None:
        """Initialize the EntailmentVerifier.

        Args:
            llm_router: LLM router for entailment checking.
        """
        self.llm_router = llm_router

    async def verify_claim(
        self,
        claim: Claim,
        evidence_texts: list[str],
    ) -> EntailmentResult:
        """Verify a single claim against evidence.

        Args:
            claim: The claim to verify.
            evidence_texts: List of evidence text snippets.

        Returns:
            EntailmentResult with verification outcome.
        """
        if not evidence_texts:
            return EntailmentResult(
                claim_id=claim.claim_id,
                status=EntailmentStatus.UNSUPPORTED,
                confidence=0.0,
                supporting_evidence=[],
                contradicting_evidence=[],
                reasoning="No evidence provided for verification.",
            )

        if self.llm_router:
            return await self._verify_with_llm(claim, evidence_texts)
        else:
            return self._verify_with_heuristics(claim, evidence_texts)

    async def verify_claim_graph(
        self,
        claim_graph: ClaimGraph,
        evidence_map: dict[str, str],
    ) -> EntailmentReport:
        """Verify all claims in a ClaimGraph.

        Args:
            claim_graph: ClaimGraph with claims to verify.
            evidence_map: Mapping of evidence_id -> evidence_text.

        Returns:
            EntailmentReport with all verification results.
        """
        results: list[EntailmentResult] = []
        verified_count = 0
        contradicted_count = 0
        unverified_count = 0

        for claim in claim_graph.claims:
            # Get evidence texts from claim's cited_evidence_ids
            evidence_texts = [
                evidence_map[eid]
                for eid in claim.cited_evidence_ids
                if eid in evidence_map
            ]

            # If no cited evidence, try all available evidence
            if not evidence_texts:
                evidence_texts = list(evidence_map.values())[:5]

            result = await self.verify_claim(claim, evidence_texts)
            results.append(result)

            if result.status == EntailmentStatus.SUPPORTED:
                verified_count += 1
            elif result.status == EntailmentStatus.CONTRADICTED:
                contradicted_count += 1
            else:
                unverified_count += 1

        # Calculate overall confidence
        total = len(results)
        if total > 0:
            verified_ratio = verified_count / total
            contradicted_ratio = contradicted_count / total
            overall_confidence = verified_ratio - (0.5 * contradicted_ratio)
        else:
            overall_confidence = 0.0

        return EntailmentReport(
            claim_graph=claim_graph,
            results=results,
            overall_confidence=max(0.0, min(1.0, overall_confidence)),
            claims_verified=verified_count,
            claims_contradicted=contradicted_count,
            claims_unverified=unverified_count,
        )

    async def _verify_with_llm(
        self,
        claim: Claim,
        evidence_texts: list[str],
    ) -> EntailmentResult:
        """Verify claim using LLM-based NLI."""
        from er.llm.router import AgentRole

        # Combine evidence for context
        evidence_combined = "\n\n".join([
            f"Evidence {i+1}: {text[:1000]}"
            for i, text in enumerate(evidence_texts[:5])
        ])

        prompt = f"""You are verifying whether evidence supports or contradicts an investment claim.

CLAIM:
{claim.text}

EVIDENCE:
{evidence_combined}

Analyze whether the evidence:
1. SUPPORTED - evidence provides backing for the assertion
2. WEAK - some support but not conclusive
3. UNSUPPORTED - evidence doesn't address the claim
4. CONTRADICTED - evidence refutes or disproves the assertion

Return JSON:
{{
  "status": "SUPPORTED" | "WEAK" | "UNSUPPORTED" | "CONTRADICTED",
  "confidence": 0.0-1.0,
  "supporting_evidence_indices": [0, 1, ...],
  "contradicting_evidence_indices": [2, ...],
  "reasoning": "Brief explanation"
}}

Output ONLY valid JSON."""

        try:
            response = await self.llm_router.call(
                role=AgentRole.WORKHORSE,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            content = response.get("content", "")
            return self._parse_llm_result(claim.claim_id, content, evidence_texts)

        except Exception as e:
            return EntailmentResult(
                claim_id=claim.claim_id,
                status=EntailmentStatus.UNSUPPORTED,
                confidence=0.0,
                supporting_evidence=[],
                contradicting_evidence=[],
                reasoning=f"Verification failed: {e}",
            )

    def _parse_llm_result(
        self,
        claim_id: str,
        content: str,
        evidence_texts: list[str],
    ) -> EntailmentResult:
        """Parse LLM entailment result."""
        # Clean up JSON
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()

        try:
            parsed = json.loads(content)

            status_str = parsed.get("status", "UNSUPPORTED").upper()
            status = getattr(EntailmentStatus, status_str, EntailmentStatus.UNSUPPORTED)

            supporting_indices = parsed.get("supporting_evidence_indices", [])
            contradicting_indices = parsed.get("contradicting_evidence_indices", [])

            supporting = [
                evidence_texts[i][:200]
                for i in supporting_indices
                if i < len(evidence_texts)
            ]
            contradicting = [
                evidence_texts[i][:200]
                for i in contradicting_indices
                if i < len(evidence_texts)
            ]

            return EntailmentResult(
                claim_id=claim_id,
                status=status,
                confidence=float(parsed.get("confidence", 0.5)),
                supporting_evidence=supporting,
                contradicting_evidence=contradicting,
                reasoning=parsed.get("reasoning", ""),
            )

        except (json.JSONDecodeError, AttributeError, KeyError):
            return EntailmentResult(
                claim_id=claim_id,
                status=EntailmentStatus.UNSUPPORTED,
                confidence=0.0,
                supporting_evidence=[],
                contradicting_evidence=[],
                reasoning="Failed to parse verification result.",
            )

    def _verify_with_heuristics(
        self,
        claim: Claim,
        evidence_texts: list[str],
    ) -> EntailmentResult:
        """Verify claim using keyword-based heuristics.

        Fallback when LLM is not available.
        """
        claim_keywords = self._extract_keywords(claim.text)
        supporting: list[str] = []
        contradicting: list[str] = []

        for evidence in evidence_texts:
            evidence_lower = evidence.lower()

            # Check for keyword overlap
            overlap_count = sum(1 for kw in claim_keywords if kw in evidence_lower)

            if overlap_count >= 3:
                # Check for contradiction indicators
                contradiction_words = [
                    "however", "but", "although", "despite", "contrary",
                    "declined", "fell", "missed", "below expectations",
                ]
                has_contradiction = any(
                    word in evidence_lower for word in contradiction_words
                )

                if has_contradiction:
                    contradicting.append(evidence[:200])
                else:
                    supporting.append(evidence[:200])

        # Determine status
        if supporting and not contradicting:
            status = EntailmentStatus.SUPPORTED
            confidence = min(0.8, 0.3 + 0.1 * len(supporting))
        elif contradicting and not supporting:
            status = EntailmentStatus.CONTRADICTED
            confidence = min(0.8, 0.3 + 0.1 * len(contradicting))
        elif supporting and contradicting:
            status = EntailmentStatus.WEAK
            confidence = 0.4
        else:
            status = EntailmentStatus.UNSUPPORTED
            confidence = 0.3

        return EntailmentResult(
            claim_id=claim.claim_id,
            status=status,
            confidence=confidence,
            supporting_evidence=supporting[:3],
            contradicting_evidence=contradicting[:3],
            reasoning="Verified using keyword-based heuristics.",
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract significant keywords from text."""
        import re

        text_lower = text.lower()
        words = re.findall(r'\b[a-z]+\b', text_lower)

        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'this', 'that', 'these', 'those', 'it', 'its', 'their', 'our', 'will',
            'should', 'would', 'could', 'may', 'might', 'has', 'have', 'had',
        }

        return [w for w in words if w not in stopwords and len(w) > 3]


def verify_claims_batch(
    claims: list[Claim],
    evidence_texts: list[str],
) -> list[EntailmentResult]:
    """Synchronously verify a batch of claims (heuristics only).

    Convenience function for testing and simple use cases.

    Args:
        claims: List of claims to verify.
        evidence_texts: Evidence to check against.

    Returns:
        List of EntailmentResults.
    """
    verifier = EntailmentVerifier()
    results = []

    for claim in claims:
        result = verifier._verify_with_heuristics(claim, evidence_texts)
        results.append(result)

    return results
