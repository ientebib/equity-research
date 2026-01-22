"""
Report Compiler for Equity Research Reports.

Compiles synthesized research into structured, evidence-linked reports
with proper citations and formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from er.types import (
    Claim,
    ClaimType,
    VerifiedFact,
    VerificationStatus,
)


class ReportSection(str, Enum):
    """Standard report sections."""

    EXECUTIVE_SUMMARY = "executive_summary"
    COMPANY_OVERVIEW = "company_overview"
    SEGMENT_ANALYSIS = "segment_analysis"
    CROSS_VERTICAL = "cross_vertical_dynamics"
    COMPETITIVE = "competitive_position"
    FINANCIALS = "financial_analysis"
    VALUATION = "valuation"
    RISKS = "risks"
    CATALYSTS = "catalysts"
    RECOMMENDATION = "recommendation"
    APPENDIX = "appendix"


class InvestmentView(str, Enum):
    """Investment recommendation."""

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class Conviction(str, Enum):
    """Conviction level."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass
class Citation:
    """A citation linking a claim to evidence."""

    citation_id: str  # e.g., "[1]"
    source_type: str  # e.g., "10-K", "Transcript", "News"
    source_date: str  # e.g., "2024-Q3"
    source_url: str | None = None
    excerpt: str = ""  # Relevant excerpt from source

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "citation_id": self.citation_id,
            "source_type": self.source_type,
            "source_date": self.source_date,
            "source_url": self.source_url,
            "excerpt": self.excerpt,
        }


@dataclass
class ReportClaim:
    """A claim in the report with evidence support."""

    text: str
    claim_type: ClaimType
    section: ReportSection
    citations: list[Citation] = field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIABLE
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "text": self.text,
            "claim_type": self.claim_type.value,
            "section": self.section.value,
            "citations": [c.to_dict() for c in self.citations],
            "verification_status": self.verification_status.value,
            "confidence": self.confidence,
        }


@dataclass
class SectionContent:
    """Content for a report section."""

    section: ReportSection
    title: str
    content: str
    claims: list[ReportClaim] = field(default_factory=list)
    word_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "section": self.section.value,
            "title": self.title,
            "content": self.content,
            "claims": [c.to_dict() for c in self.claims],
            "word_count": self.word_count,
        }


@dataclass
class CompiledReport:
    """A fully compiled equity research report."""

    ticker: str
    company_name: str
    generated_at: datetime
    investment_view: InvestmentView
    conviction: Conviction
    target_price: float | None = None
    current_price: float | None = None
    sections: list[SectionContent] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    total_claims: int = 0
    verified_claims: int = 0
    total_word_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "generated_at": self.generated_at.isoformat(),
            "investment_view": self.investment_view.value,
            "conviction": self.conviction.value,
            "target_price": self.target_price,
            "current_price": self.current_price,
            "sections": [s.to_dict() for s in self.sections],
            "citations": [c.to_dict() for c in self.citations],
            "total_claims": self.total_claims,
            "verified_claims": self.verified_claims,
            "total_word_count": self.total_word_count,
            "verification_rate": (
                self.verified_claims / self.total_claims
                if self.total_claims > 0
                else 0.0
            ),
        }

    def get_section(self, section: ReportSection) -> SectionContent | None:
        """Get a specific section by type."""
        for s in self.sections:
            if s.section == section:
                return s
        return None

    def to_markdown(self) -> str:
        """Export report as markdown."""
        lines = [
            f"# {self.ticker} Equity Research Report",
            f"*{self.company_name}*",
            f"",
            f"**Investment View:** {self.investment_view.value}",
            f"**Conviction:** {self.conviction.value}",
        ]

        if self.target_price:
            lines.append(f"**Target Price:** ${self.target_price:.2f}")
        if self.current_price:
            lines.append(f"**Current Price:** ${self.current_price:.2f}")

        lines.append(f"**Generated:** {self.generated_at.strftime('%Y-%m-%d')}")
        lines.append("")

        for section in self.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            lines.append(section.content)
            lines.append("")

        # Add citations appendix
        if self.citations:
            lines.append("## Sources")
            lines.append("")
            for citation in self.citations:
                source_info = f"{citation.source_type} ({citation.source_date})"
                if citation.source_url:
                    lines.append(
                        f"{citation.citation_id} [{source_info}]({citation.source_url})"
                    )
                else:
                    lines.append(f"{citation.citation_id} {source_info}")
            lines.append("")

        return "\n".join(lines)


class ReportCompiler:
    """Compiles research synthesis into structured reports.

    Features:
    1. Section extraction from raw synthesis
    2. Claim extraction and typing
    3. Citation linking to evidence
    4. Verification status propagation
    """

    SECTION_PATTERNS = {
        ReportSection.EXECUTIVE_SUMMARY: r"(?i)##?\s*executive\s+summary",
        ReportSection.COMPANY_OVERVIEW: r"(?i)##?\s*company\s+overview",
        ReportSection.SEGMENT_ANALYSIS: r"(?i)##?\s*segment\s+analysis",
        ReportSection.CROSS_VERTICAL: r"(?i)##?\s*cross[- ]vertical",
        ReportSection.COMPETITIVE: r"(?i)##?\s*competitive\s+position",
        ReportSection.FINANCIALS: r"(?i)##?\s*financial\s+analysis",
        ReportSection.VALUATION: r"(?i)##?\s*valuation",
        ReportSection.RISKS: r"(?i)##?\s*risks?",
        ReportSection.CATALYSTS: r"(?i)##?\s*catalysts?",
        ReportSection.RECOMMENDATION: r"(?i)##?\s*recommendation",
    }

    VIEW_PATTERNS = {
        InvestmentView.BUY: r"(?i)\b(buy|bullish|overweight)\b",
        InvestmentView.SELL: r"(?i)\b(sell|bearish|underweight)\b",
        InvestmentView.HOLD: r"(?i)\b(hold|neutral|equal[\s-]?weight)\b",
    }

    CONVICTION_PATTERNS = {
        Conviction.HIGH: r"(?i)\b(high\s+(conviction|confidence)|(conviction|confidence)[:\s]+high)\b",
        Conviction.LOW: r"(?i)\b(low\s+(conviction|confidence)|(conviction|confidence)[:\s]+low)\b",
        Conviction.MEDIUM: r"(?i)\b((medium|moderate)\s+(conviction|confidence)|(conviction|confidence)[:\s]+(medium|moderate))\b",
    }

    def __init__(self) -> None:
        """Initialize the compiler."""
        self._citation_counter = 0

    def compile(
        self,
        synthesis_text: str,
        ticker: str,
        company_name: str,
        verified_facts: list[VerifiedFact] | None = None,
        claims: list[Claim] | None = None,
        current_price: float | None = None,
    ) -> CompiledReport:
        """Compile synthesis into a structured report.

        Args:
            synthesis_text: Raw synthesis output from LLM.
            ticker: Stock ticker.
            company_name: Company name.
            verified_facts: Optional list of verified facts for citation.
            claims: Optional list of extracted claims.
            current_price: Current stock price.

        Returns:
            CompiledReport with structured sections.
        """
        from er.types import utc_now

        # Reset citation counter
        self._citation_counter = 0

        # Extract investment view and conviction
        view = self._extract_investment_view(synthesis_text)
        conviction = self._extract_conviction(synthesis_text)
        target_price = self._extract_target_price(synthesis_text)

        # Extract sections
        sections = self._extract_sections(synthesis_text)

        # Build citation index from verified facts
        citations: list[Citation] = []
        if verified_facts:
            citations = self._build_citations(verified_facts)

        # Extract and classify claims
        report_claims: list[ReportClaim] = []
        if claims:
            report_claims = self._convert_claims(claims, sections, citations)

        # Calculate totals
        total_word_count = sum(s.word_count for s in sections)
        total_claims = len(report_claims)
        verified_claims = sum(
            1
            for c in report_claims
            if c.verification_status
            in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED)
        )

        return CompiledReport(
            ticker=ticker,
            company_name=company_name,
            generated_at=utc_now(),
            investment_view=view,
            conviction=conviction,
            target_price=target_price,
            current_price=current_price,
            sections=sections,
            citations=citations,
            total_claims=total_claims,
            verified_claims=verified_claims,
            total_word_count=total_word_count,
        )

    def _extract_investment_view(self, text: str) -> InvestmentView:
        """Extract investment view from text."""
        # Check executive summary first
        exec_match = re.search(
            r"(?i)executive\s+summary.*?(?=##|\Z)", text, re.DOTALL
        )
        search_text = exec_match.group(0) if exec_match else text[:2000]

        for view, pattern in self.VIEW_PATTERNS.items():
            if re.search(pattern, search_text):
                return view

        return InvestmentView.HOLD  # Default

    def _extract_conviction(self, text: str) -> Conviction:
        """Extract conviction level from text."""
        exec_match = re.search(
            r"(?i)executive\s+summary.*?(?=##|\Z)", text, re.DOTALL
        )
        search_text = exec_match.group(0) if exec_match else text[:2000]

        for conv, pattern in self.CONVICTION_PATTERNS.items():
            if re.search(pattern, search_text):
                return conv

        return Conviction.MEDIUM  # Default

    def _extract_target_price(self, text: str) -> float | None:
        """Extract target price from text."""
        patterns = [
            r"(?i)target\s+price[:\s]+(?:of\s+)?\$?([\d,.]+)",
            r"(?i)target\s+price\s+of\s+\$?([\d,.]+)",
            r"(?i)price\s+target[:\s]+(?:of\s+)?\$?([\d,.]+)",
            r"(?i)price\s+target\s+of\s+\$?([\d,.]+)",
            r"(?i)\$?([\d,.]+)\s+price\s+target",
            r"(?i)PT[:\s]+\$?([\d,.]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue

        return None

    def _extract_sections(self, text: str) -> list[SectionContent]:
        """Extract sections from synthesis text."""
        sections: list[SectionContent] = []

        # Find all section boundaries
        section_positions: list[tuple[int, ReportSection, str]] = []

        for section_type, pattern in self.SECTION_PATTERNS.items():
            for match in re.finditer(pattern, text):
                # Get the full heading line
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                if line_end == -1:
                    line_end = len(text)
                heading = text[line_start:line_end].strip()
                section_positions.append((match.start(), section_type, heading))

        # Sort by position
        section_positions.sort(key=lambda x: x[0])

        # Extract content between sections
        for i, (pos, section_type, heading) in enumerate(section_positions):
            # Find end of section (start of next section or end of text)
            if i + 1 < len(section_positions):
                end_pos = section_positions[i + 1][0]
            else:
                end_pos = len(text)

            # Extract content (skip the heading line)
            content_start = text.find("\n", pos)
            if content_start == -1:
                content_start = pos
            content = text[content_start:end_pos].strip()

            # Clean heading
            title = re.sub(r"^#+\s*", "", heading).strip()

            sections.append(
                SectionContent(
                    section=section_type,
                    title=title,
                    content=content,
                    word_count=len(content.split()),
                )
            )

        return sections

    def _build_citations(self, verified_facts: list[VerifiedFact]) -> list[Citation]:
        """Build citations from verified facts."""
        citations: list[Citation] = []

        for fact in verified_facts:
            self._citation_counter += 1
            citation_id = f"[{self._citation_counter}]"

            # Extract source info from the original_fact inside VerifiedFact
            original = fact.original_fact
            source_type = original.source or "Unknown"
            # source_date is already a string in Fact, not a datetime
            source_date = original.source_date or ""

            citations.append(
                Citation(
                    citation_id=citation_id,
                    source_type=source_type,
                    source_date=source_date,
                    source_url=None,  # Fact doesn't have source_url field
                    excerpt=original.statement[:200] if original.statement else "",
                )
            )

        return citations

    def _convert_claims(
        self,
        claims: list[Claim],
        sections: list[SectionContent],
        citations: list[Citation],
    ) -> list[ReportClaim]:
        """Convert Claim objects to ReportClaim with section assignment."""
        report_claims: list[ReportClaim] = []

        for claim in claims:
            # Find which section this claim belongs to
            section = self._find_claim_section(claim.text, sections)

            # Find relevant citations (by matching text similarity)
            relevant_citations = self._find_relevant_citations(claim.text, citations)

            report_claims.append(
                ReportClaim(
                    text=claim.text,
                    claim_type=claim.claim_type,
                    section=section,
                    citations=relevant_citations,
                    verification_status=claim.verification_status,
                    confidence=claim.confidence,
                )
            )

        return report_claims

    def _find_claim_section(
        self, claim_text: str, sections: list[SectionContent]
    ) -> ReportSection:
        """Find which section a claim belongs to."""
        claim_lower = claim_text.lower()

        for section in sections:
            if claim_lower in section.content.lower():
                return section.section

        # Default based on claim content keywords
        if any(
            kw in claim_lower
            for kw in ["revenue", "margin", "earnings", "profit", "cash flow"]
        ):
            return ReportSection.FINANCIALS
        if any(kw in claim_lower for kw in ["risk", "threat", "concern", "uncertainty"]):
            return ReportSection.RISKS
        if any(kw in claim_lower for kw in ["catalyst", "trigger", "driver"]):
            return ReportSection.CATALYSTS
        if any(kw in claim_lower for kw in ["valuation", "multiple", "dcf", "pe ratio"]):
            return ReportSection.VALUATION

        return ReportSection.SEGMENT_ANALYSIS  # Default

    def _find_relevant_citations(
        self, claim_text: str, citations: list[Citation]
    ) -> list[Citation]:
        """Find citations relevant to a claim."""
        relevant: list[Citation] = []
        claim_words = set(claim_text.lower().split())

        for citation in citations:
            if not citation.excerpt:
                continue

            excerpt_words = set(citation.excerpt.lower().split())
            overlap = len(claim_words & excerpt_words)

            # If significant word overlap, consider relevant
            if overlap >= 3 or overlap / len(claim_words) > 0.3:
                relevant.append(citation)

        return relevant[:3]  # Limit to 3 most relevant
