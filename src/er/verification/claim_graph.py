"""
ClaimGraph Builder for structured claim extraction.

Extracts claims from analysis text and links them to supporting facts and evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from er.types import (
    Claim,
    ClaimGraph,
    ClaimType,
    generate_id,
)


@dataclass
class ExtractedFact:
    """A fact extracted from analysis text."""

    fact_id: str
    text: str
    source_claim_id: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5


# Mapping from domain categories to ClaimTypes
DOMAIN_CATEGORY_PATTERNS = {
    "financial": [
        r"revenue\s+(will|should|is expected to|grew|increased|decreased)",
        r"margin\s+(will|should|improved|declined)",
        r"earnings\s+(will|should|beat|miss)",
        r"(growth|decline)\s+of\s+\d+%",
        r"(\$[\d.]+[MB]|\d+%)\s+(revenue|growth|margin|profit)",
    ],
    "strategic": [
        r"(competitive|market)\s+(position|advantage|share)",
        r"(moat|barriers\s+to\s+entry)",
        r"(strategic|acquisition|expansion)\s+(initiative|plan|opportunity)",
        r"management\s+(execution|strategy|vision)",
    ],
    "risk": [
        r"(risk|threat|concern)\s+(of|that|from)",
        r"(regulatory|legal|litigation)\s+(risk|issue|concern)",
        r"(supply\s+chain|operational)\s+(risk|disruption)",
        r"(downside|vulnerability|exposure)",
    ],
    "valuation": [
        r"(undervalued|overvalued|fair\s+value)",
        r"(price\s+target|target\s+price)\s+of",
        r"trading\s+(at|below|above)\s+\d+x",
        r"(multiple|valuation)\s+(compression|expansion)",
        r"(intrinsic|fair)\s+value",
    ],
    "catalyst": [
        r"(catalyst|driver)\s+(for|of)",
        r"(upcoming|near-term)\s+(event|announcement|release)",
        r"(earnings|product|event)\s+in\s+(Q[1-4]|[A-Z][a-z]+ \d{4})",
        r"(potential|expected)\s+(announcement|launch|approval)",
    ],
}


class ClaimGraphBuilder:
    """Builds a ClaimGraph from analysis text.

    Extracts:
    1. Claims (investment assertions)
    2. Facts supporting each claim
    3. Evidence backing each fact
    """

    def __init__(self, llm_router: Any = None) -> None:
        """Initialize the ClaimGraphBuilder.

        Args:
            llm_router: Optional LLM router for advanced extraction.
        """
        self.llm_router = llm_router

    def build_from_text(
        self,
        text: str,
        ticker: str = "",
        source: str = "analysis",
    ) -> ClaimGraph:
        """Build a ClaimGraph from analysis text.

        Args:
            text: Analysis text to extract claims from.
            ticker: Stock ticker symbol.
            source: Source of the text (e.g., "synthesis", "vertical_dossiers").

        Returns:
            ClaimGraph with extracted claims.
        """
        claims = self._extract_claims(text)

        return ClaimGraph(
            ticker=ticker,
            source=source,
            claims=claims,
            total_claims=len(claims),
            cited_claims=sum(1 for c in claims if c.cited_evidence_ids),
            uncited_claims=sum(1 for c in claims if not c.cited_evidence_ids),
        )

    def _extract_claims(self, text: str) -> list[Claim]:
        """Extract claims from text using pattern matching."""
        claims: list[Claim] = []
        sentences = self._split_sentences(text)

        for sentence in sentences:
            claim_type, category = self._detect_claim_type(sentence)
            if claim_type:
                # Check if we should create a claim
                if self._is_significant_claim(sentence):
                    claim = Claim(
                        claim_id=generate_id("clm"),
                        text=sentence.strip(),
                        claim_type=claim_type,
                        section=category,  # Use category as section
                        cited_evidence_ids=[],
                        linked_fact_ids=[],
                        confidence=self._estimate_confidence(sentence),
                    )
                    claims.append(claim)

        return claims

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _detect_claim_type(self, sentence: str) -> tuple[ClaimType | None, str]:
        """Detect the type of claim in a sentence.

        Returns:
            Tuple of (ClaimType, category_name).
        """
        sentence_lower = sentence.lower()

        # Map domain categories to ClaimTypes
        category_to_type = {
            "financial": ClaimType.FACT,
            "strategic": ClaimType.INFERENCE,
            "risk": ClaimType.INFERENCE,
            "valuation": ClaimType.OPINION,
            "catalyst": ClaimType.FORECAST,
        }

        for category, patterns in DOMAIN_CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, sentence_lower):
                    return category_to_type.get(category, ClaimType.FACT), category

        # Check for forward-looking language
        forecast_indicators = [
            "will", "expected to", "forecast", "projected", "anticipate",
            "outlook", "guidance",
        ]
        if any(ind in sentence_lower for ind in forecast_indicators):
            return ClaimType.FORECAST, "forecast"

        return None, ""

    def _is_significant_claim(self, sentence: str) -> bool:
        """Check if sentence is a significant investment claim."""
        # Must be longer than a minimum length
        if len(sentence) < 30:
            return False

        # Should not be a question
        if sentence.strip().endswith("?"):
            return False

        # Should contain some substantive content
        substantive_words = {
            "revenue", "growth", "margin", "earnings", "profit", "competitive",
            "market", "risk", "valuation", "target", "catalyst", "opportunity",
            "advantage", "moat", "position", "strategy", "execution",
        }

        sentence_lower = sentence.lower()
        return any(word in sentence_lower for word in substantive_words)

    def _estimate_confidence(self, sentence: str) -> float:
        """Estimate confidence level based on language."""
        sentence_lower = sentence.lower()

        # High confidence indicators
        high_confidence = ["will", "is", "are", "has", "have", "demonstrates", "shows"]
        # Medium confidence indicators
        medium_confidence = ["likely", "expect", "should", "appears", "indicates"]
        # Low confidence indicators
        low_confidence = ["may", "might", "could", "possibly", "potential"]

        for word in low_confidence:
            if word in sentence_lower:
                return 0.4

        for word in medium_confidence:
            if word in sentence_lower:
                return 0.6

        for word in high_confidence:
            if word in sentence_lower:
                return 0.8

        return 0.5

    async def build_with_llm(
        self,
        text: str,
        ticker: str = "",
        source: str = "analysis",
    ) -> ClaimGraph:
        """Build ClaimGraph using LLM for better extraction.

        Args:
            text: Analysis text to extract claims from.
            ticker: Stock ticker symbol.
            source: Source of the text.

        Returns:
            ClaimGraph with LLM-extracted claims.
        """
        if not self.llm_router:
            return self.build_from_text(text, ticker, source)

        prompt = self._build_extraction_prompt(text)

        try:
            from er.llm.router import AgentRole

            response = await self.llm_router.call(
                role=AgentRole.WORKHORSE,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            content = response.get("content", "")
            claims = self._parse_llm_claims(content)

            return ClaimGraph(
                ticker=ticker,
                source=source,
                claims=claims,
                total_claims=len(claims),
                cited_claims=sum(1 for c in claims if c.cited_evidence_ids),
                uncited_claims=sum(1 for c in claims if not c.cited_evidence_ids),
            )

        except Exception:
            # Fallback to pattern-based extraction
            return self.build_from_text(text, ticker, source)

    def _build_extraction_prompt(self, text: str) -> str:
        """Build prompt for LLM-based claim extraction."""
        return f"""Extract investment claims from this analysis text.

For each claim identify:
1. The claim text (the specific assertion being made)
2. The claim type: FACT, INFERENCE, FORECAST, or OPINION
3. Section category: financial, strategic, risk, valuation, or catalyst
4. Confidence level (0.0-1.0) based on the certainty of language

Text to analyze:
{text[:4000]}

Return JSON in this format:
{{
  "claims": [
    {{
      "text": "claim text here",
      "claim_type": "FACT",
      "section": "financial",
      "confidence": 0.7
    }}
  ]
}}

Extract only substantive investment claims, not background facts.
Output ONLY valid JSON."""

    def _parse_llm_claims(self, content: str) -> list[Claim]:
        """Parse claims from LLM response."""
        claims = []

        # Clean up response
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
            claim_list = parsed.get("claims", [])

            for item in claim_list:
                claim_type_str = item.get("claim_type", "FACT").upper()
                claim_type = getattr(ClaimType, claim_type_str, ClaimType.FACT)

                claim = Claim(
                    claim_id=generate_id("clm"),
                    text=item.get("text", ""),
                    claim_type=claim_type,
                    section=item.get("section", ""),
                    cited_evidence_ids=[],
                    linked_fact_ids=[],
                    confidence=float(item.get("confidence", 0.5)),
                )
                claims.append(claim)

        except (json.JSONDecodeError, AttributeError, KeyError):
            pass

        return claims

    def link_facts_to_claims(
        self,
        claim_graph: ClaimGraph,
        facts: list[dict[str, Any]],
    ) -> ClaimGraph:
        """Link extracted facts to claims based on semantic similarity.

        Args:
            claim_graph: Existing claim graph.
            facts: List of fact dicts with 'text' and 'fact_id' keys.

        Returns:
            Updated ClaimGraph with linked facts.
        """
        # Simple keyword-based linking
        for claim in claim_graph.claims:
            claim_keywords = set(self._tokenize(claim.text))

            for fact in facts:
                fact_keywords = set(self._tokenize(fact.get("text", "")))

                # If significant overlap, link the fact
                overlap = len(claim_keywords & fact_keywords)
                if overlap >= 3:  # At least 3 common keywords
                    fact_id = fact.get("fact_id", generate_id("fact"))
                    if fact_id not in claim.linked_fact_ids:
                        claim.linked_fact_ids.append(fact_id)

        # Update counts
        claim_graph.cited_claims = sum(1 for c in claim_graph.claims if c.cited_evidence_ids)
        claim_graph.uncited_claims = sum(1 for c in claim_graph.claims if not c.cited_evidence_ids)

        return claim_graph

    def link_evidence_to_claims(
        self,
        claim_graph: ClaimGraph,
        evidence_texts: dict[str, str],
    ) -> ClaimGraph:
        """Link evidence to claims based on keyword overlap.

        Args:
            claim_graph: Existing claim graph.
            evidence_texts: Dict of evidence_id -> evidence_text.

        Returns:
            Updated ClaimGraph with linked evidence.
        """
        for claim in claim_graph.claims:
            claim_keywords = set(self._tokenize(claim.text))

            for ev_id, ev_text in evidence_texts.items():
                ev_keywords = set(self._tokenize(ev_text))

                # If significant overlap, link the evidence
                overlap = len(claim_keywords & ev_keywords)
                if overlap >= 3:
                    if ev_id not in claim.cited_evidence_ids:
                        claim.cited_evidence_ids.append(ev_id)

        # Update counts
        claim_graph.cited_claims = sum(1 for c in claim_graph.claims if c.cited_evidence_ids)
        claim_graph.uncited_claims = sum(1 for c in claim_graph.claims if not c.cited_evidence_ids)

        return claim_graph

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text for keyword matching."""
        text = text.lower()
        tokens = re.findall(r'\b[a-z]+\b', text)
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'this', 'that', 'these', 'those', 'it', 'its', 'their', 'our',
        }
        return [t for t in tokens if t not in stopwords and len(t) > 2]
