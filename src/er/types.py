"""
Core types for the equity research system.

This module defines the fundamental data structures used throughout the system:
- Enums for phases, message types, and classifications
- Frozen dataclasses for immutable data (Evidence, AgentMessage, ResearchThread)
- Mutable dataclasses for state tracking (RunState)
- Tool-related dataclasses (ToolCall, ToolResult)
- Helper functions for ID generation and timestamps
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from uuid6 import uuid7


def generate_id(prefix: str = "") -> str:
    """Generate a time-ordered unique ID using UUID7.

    Args:
        prefix: Optional prefix for the ID (e.g., "run", "msg", "ev")

    Returns:
        A unique ID string, optionally prefixed.
    """
    uid = str(uuid7())
    return f"{prefix}_{uid}" if prefix else uid


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class Phase(str, Enum):
    """Phases of the research pipeline."""

    INIT = "init"
    FETCH_DATA = "fetch_data"
    DISCOVERY = "discovery"
    DECOMPOSE = "decompose"
    RESEARCH = "research"
    SYNTHESIZE = "synthesize"
    DELIBERATE = "deliberate"
    OUTPUTS = "outputs"
    COMPLETE = "complete"
    FAILED = "failed"


class MessageType(str, Enum):
    """Types of messages exchanged between agents."""

    DISCOVERY_COMPLETE = "discovery_complete"
    DECOMPOSITION_COMPLETE = "decomposition_complete"
    RESEARCH_COMPLETE = "research_complete"
    SYNTHESIS_COMPLETE = "synthesis_complete"
    CHALLENGE = "challenge"
    DEFENSE = "defense"
    QUESTION = "question"
    ANSWER = "answer"
    ESCALATE = "escalate"
    HANDOFF = "handoff"
    VERDICT = "verdict"
    ERROR = "error"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class ToSRisk(str, Enum):
    """Terms of Service risk level for evidence sources."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceTier(str, Enum):
    """Source tier classification for evidence."""

    OFFICIAL = "official"  # Company filings, SEC, official press releases
    INSTITUTIONAL = "institutional"  # Analyst reports, rating agencies
    NEWS = "news"  # Major financial news outlets
    OTHER = "other"  # Blogs, forums, social media


@dataclass(frozen=True)
class Evidence:
    """Immutable evidence record from data fetching.

    Evidence represents a piece of information retrieved from an external source
    that can be cited in research outputs.
    """

    evidence_id: str
    source_url: str
    retrieved_at: datetime
    content_type: str  # e.g., "text/html", "application/pdf", "text/plain"
    content_hash: str  # SHA-256 hash of raw content

    snippet: str  # Extracted text content (may be truncated)
    title: str | None = None
    published_at: datetime | None = None
    author: str | None = None

    tos_risk: ToSRisk = ToSRisk.NONE
    source_tier: SourceTier = SourceTier.OTHER

    blob_path: str | None = None  # Path to raw content in blob storage

    @classmethod
    def create(
        cls,
        source_url: str,
        content_type: str,
        raw_content: bytes,
        snippet: str,
        title: str | None = None,
        published_at: datetime | None = None,
        author: str | None = None,
        tos_risk: ToSRisk = ToSRisk.NONE,
        source_tier: SourceTier = SourceTier.OTHER,
        blob_path: str | None = None,
    ) -> Evidence:
        """Factory method to create evidence with auto-generated ID and hash."""
        return cls(
            evidence_id=generate_id("ev"),
            source_url=source_url,
            retrieved_at=utc_now(),
            content_type=content_type,
            content_hash=hashlib.sha256(raw_content).hexdigest(),
            snippet=snippet,
            title=title,
            published_at=published_at,
            author=author,
            tos_risk=tos_risk,
            source_tier=source_tier,
            blob_path=blob_path,
        )


@dataclass(frozen=True)
class AgentMessage:
    """Immutable message exchanged between agents.

    Messages form the communication protocol between agents and the coordinator.
    All messages are logged to the event store for audit and replay.
    """

    message_id: str
    run_id: str
    timestamp: datetime

    from_agent: str
    to_agent: str
    message_type: MessageType

    content: str  # Natural language content
    context: dict[str, Any] = field(default_factory=dict)  # Structured data

    confidence: float | None = None  # 0.0 to 1.0
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    # Token/cost tracking
    usage: dict[str, int | float] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        run_id: str,
        from_agent: str,
        to_agent: str,
        message_type: MessageType,
        content: str,
        context: dict[str, Any] | None = None,
        confidence: float | None = None,
        evidence_ids: tuple[str, ...] | None = None,
        usage: dict[str, int | float] | None = None,
    ) -> AgentMessage:
        """Factory method to create a message with auto-generated ID and timestamp."""
        return cls(
            message_id=generate_id("msg"),
            run_id=run_id,
            timestamp=utc_now(),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            context=context or {},
            confidence=confidence,
            evidence_ids=evidence_ids or (),
            usage=usage or {},
        )


@dataclass
class RunState:
    """Mutable state for a research run.

    Tracks progress through phases, budget consumption, and accumulated outputs.
    Modified in place as the run progresses.
    """

    run_id: str
    ticker: str
    phase: Phase
    started_at: datetime

    # Budget tracking
    budget_remaining_usd: float
    tokens_used: int = 0
    cost_usd: float = 0.0

    # Phase outputs (populated as phases complete)
    market_data: dict[str, Any] = field(default_factory=dict)
    filings_metadata: dict[str, Any] = field(default_factory=dict)
    discovery_output: dict[str, Any] = field(default_factory=dict)
    decomposition_output: dict[str, Any] = field(default_factory=dict)
    research_outputs: dict[str, Any] = field(default_factory=dict)
    synthesis_output: dict[str, Any] = field(default_factory=dict)
    deliberation_log: list[dict[str, Any]] = field(default_factory=list)
    final_verdict: dict[str, Any] = field(default_factory=dict)

    # Errors and warnings
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Artifacts (output files)
    artifacts: dict[str, str] = field(default_factory=dict)  # name -> path

    @classmethod
    def create(cls, ticker: str, budget_usd: float) -> RunState:
        """Factory method to create initial run state."""
        return cls(
            run_id=generate_id("run"),
            ticker=ticker.upper(),
            phase=Phase.INIT,
            started_at=utc_now(),
            budget_remaining_usd=budget_usd,
        )

    def record_cost(self, tokens: int, cost_usd: float) -> None:
        """Record token usage and cost for this run.

        Args:
            tokens: Number of tokens used.
            cost_usd: Cost in USD.
        """
        self.tokens_used += tokens
        self.cost_usd += cost_usd
        self.budget_remaining_usd -= cost_usd

    @property
    def budget_exceeded(self) -> bool:
        """Check if the budget has been exceeded."""
        return self.budget_remaining_usd < 0


@dataclass(frozen=True)
class ResearchThread:
    """A research thread representing a focused area of investigation.

    Created during decomposition to divide the research into manageable,
    specialized threads that can be worked on in parallel.
    """

    thread_id: str
    name: str  # Short name (e.g., "Cloud Revenue Growth")
    description: str  # Detailed description of what to investigate

    discovery_lens: str  # Perspective from discovery (e.g., "growth_drivers")
    is_official_segment: bool  # Whether this maps to an official business segment
    official_segment_name: str | None  # Name from 10-K if official

    research_questions: tuple[str, ...]  # Specific questions to answer
    required_data: tuple[str, ...]  # Data sources needed

    suggested_valuation_method: str | None  # e.g., "DCF", "comps", "sum_of_parts"
    priority: int = 1  # 1 = highest priority

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        discovery_lens: str,
        research_questions: list[str],
        required_data: list[str],
        is_official_segment: bool = False,
        official_segment_name: str | None = None,
        suggested_valuation_method: str | None = None,
        priority: int = 1,
    ) -> ResearchThread:
        """Factory method to create a research thread."""
        return cls(
            thread_id=generate_id("thread"),
            name=name,
            description=description,
            discovery_lens=discovery_lens,
            is_official_segment=is_official_segment,
            official_segment_name=official_segment_name,
            research_questions=tuple(research_questions),
            required_data=tuple(required_data),
            suggested_valuation_method=suggested_valuation_method,
            priority=priority,
        )


@dataclass(frozen=True)
class ToolCall:
    """A tool call request from an agent."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    timestamp: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, tool_name: str, arguments: dict[str, Any]) -> ToolCall:
        """Factory method to create a tool call."""
        return cls(
            call_id=generate_id("call"),
            tool_name=tool_name,
            arguments=arguments,
            timestamp=utc_now(),
        )


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool call."""

    call_id: str  # References the ToolCall
    success: bool
    result: Any  # The actual result data
    error: str | None = None
    timestamp: datetime = field(default_factory=utc_now)

    @classmethod
    def success_result(cls, call_id: str, result: Any) -> ToolResult:
        """Create a successful tool result."""
        return cls(
            call_id=call_id,
            success=True,
            result=result,
            timestamp=utc_now(),
        )

    @classmethod
    def error_result(cls, call_id: str, error: str) -> ToolResult:
        """Create an error tool result."""
        return cls(
            call_id=call_id,
            success=False,
            result=None,
            error=error,
            timestamp=utc_now(),
        )


# ============== Stage 1: Company Context ==============

@dataclass
class CompanyContext:
    """Full context about a company gathered from FMP API.

    This is the primary data structure passed to ALL agents in the pipeline.
    Contains ~20-25K tokens of structured financial and business data.

    Attributes:
        symbol: Stock ticker symbol.
        fetched_at: When the data was fetched.
        profile: Company profile info (name, sector, industry, description).
        financials: Financial statements summary.
        segments: Revenue breakdown by product and geography.
        transcripts: Recent earnings call transcripts.
        news: Recent news articles.
        analyst_data: Analyst estimates, ratings, price targets.
        evidence_ids: List of evidence IDs for all fetched data.
    """

    symbol: str
    fetched_at: datetime

    # Company profile
    profile: dict[str, Any] = field(default_factory=dict)

    # Financial statements (summarized)
    income_statement_annual: list[dict[str, Any]] = field(default_factory=list)
    income_statement_quarterly: list[dict[str, Any]] = field(default_factory=list)
    balance_sheet_annual: list[dict[str, Any]] = field(default_factory=list)
    cash_flow_annual: list[dict[str, Any]] = field(default_factory=list)

    # Revenue segmentation
    revenue_product_segmentation: list[dict[str, Any]] = field(default_factory=list)
    revenue_geographic_segmentation: list[dict[str, Any]] = field(default_factory=list)

    # Earnings transcripts
    transcripts: list[dict[str, Any]] = field(default_factory=list)

    # News
    news: list[dict[str, Any]] = field(default_factory=list)

    # Analyst data
    analyst_estimates: list[dict[str, Any]] = field(default_factory=list)
    price_target_summary: dict[str, Any] = field(default_factory=dict)
    price_target_consensus: dict[str, Any] = field(default_factory=dict)
    analyst_grades: list[dict[str, Any]] = field(default_factory=list)

    # Evidence tracking
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_fmp_data(cls, data: dict[str, Any]) -> CompanyContext:
        """Create CompanyContext from FMPClient.get_full_context() output."""
        return cls(
            symbol=data.get("symbol", ""),
            fetched_at=datetime.fromisoformat(data["fetched_at"]) if "fetched_at" in data else utc_now(),
            profile=data.get("profile", {}),
            income_statement_annual=data.get("income_statement_annual", []),
            income_statement_quarterly=data.get("income_statement_quarterly", []),
            balance_sheet_annual=data.get("balance_sheet_annual", []),
            cash_flow_annual=data.get("cash_flow_annual", []),
            revenue_product_segmentation=data.get("revenue_product_segmentation", []),
            revenue_geographic_segmentation=data.get("revenue_geographic_segmentation", []),
            transcripts=data.get("transcripts", []),
            news=data.get("news", []),
            analyst_estimates=data.get("analyst_estimates", []),
            price_target_summary=data.get("price_target_summary", {}),
            price_target_consensus=data.get("price_target_consensus", {}),
            analyst_grades=data.get("analyst_grades", []),
            evidence_ids=tuple(data.get("evidence_ids", [])),
        )

    def to_prompt_string(self, max_tokens: int | None = None) -> str:
        """Convert to string format suitable for LLM prompts.

        Args:
            max_tokens: Optional max token limit (estimated by chars/4).

        Returns:
            Formatted string with all company context.
        """
        sections = []

        # Profile
        if self.profile:
            p = self.profile
            sections.append(f"""## Company Profile
- Name: {p.get('companyName', 'N/A')}
- Ticker: {self.symbol}
- Sector: {p.get('sector', 'N/A')}
- Industry: {p.get('industry', 'N/A')}
- Market Cap: ${p.get('mktCap', 0):,.0f}
- Description: {p.get('description', 'N/A')[:500]}...""")

        # Latest financials
        if self.income_statement_annual:
            latest = self.income_statement_annual[0]
            sections.append(f"""## Latest Annual Financials ({latest.get('date', 'N/A')})
- Revenue: ${latest.get('revenue', 0):,.0f}
- Gross Profit: ${latest.get('grossProfit', 0):,.0f}
- Operating Income: ${latest.get('operatingIncome', 0):,.0f}
- Net Income: ${latest.get('netIncome', 0):,.0f}
- EPS: ${latest.get('eps', 0):.2f}""")

        # Revenue segments
        if self.revenue_product_segmentation:
            seg_lines = []
            for seg in self.revenue_product_segmentation[:10]:
                for key, val in seg.items():
                    if key != "date" and isinstance(val, (int, float)):
                        seg_lines.append(f"- {key}: ${val:,.0f}")
            if seg_lines:
                sections.append(f"""## Revenue by Product/Segment
{chr(10).join(seg_lines[:15])}""")

        # Transcripts (summaries only)
        if self.transcripts:
            transcript_summaries = []
            for t in self.transcripts[:4]:
                q = t.get("quarter", "?")
                y = t.get("year", "?")
                content = t.get("content", "")[:1000]
                transcript_summaries.append(f"### Q{q} {y}\n{content}...")
            sections.append(f"""## Recent Earnings Call Transcripts
{chr(10).join(transcript_summaries)}""")

        # News headlines
        if self.news:
            headlines = [f"- [{n.get('publishedDate', 'N/A')[:10]}] {n.get('title', 'N/A')}" for n in self.news[:10]]
            sections.append(f"""## Recent News
{chr(10).join(headlines)}""")

        # Analyst data
        if self.price_target_consensus:
            ptc = self.price_target_consensus
            sections.append(f"""## Analyst Consensus
- Target High: ${ptc.get('targetHigh', 0):.2f}
- Target Low: ${ptc.get('targetLow', 0):.2f}
- Target Median: ${ptc.get('targetMedian', 0):.2f}
- Target Consensus: ${ptc.get('targetConsensus', 0):.2f}""")

        full_text = "\n\n".join(sections)

        # Truncate if needed
        if max_tokens:
            max_chars = max_tokens * 4  # Rough estimate
            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + "\n\n[TRUNCATED]"

        return full_text

    @property
    def company_name(self) -> str:
        """Get company name from profile."""
        return self.profile.get("companyName", self.symbol)

    @property
    def latest_revenue(self) -> float:
        """Get latest annual revenue."""
        if self.income_statement_annual:
            return self.income_statement_annual[0].get("revenue", 0)
        return 0

    @property
    def latest_net_income(self) -> float:
        """Get latest annual net income."""
        if self.income_statement_annual:
            return self.income_statement_annual[0].get("netIncome", 0)
        return 0


# ============== Stage 2: Discovery Output ==============

class ThreadType(str, Enum):
    """Type of research thread."""

    SEGMENT = "segment"  # Official business segment
    OPTIONALITY = "optionality"  # Strategic option (e.g., Waymo)
    CROSS_CUTTING = "cross_cutting"  # Theme across segments (e.g., AI)


@dataclass(frozen=True)
class DiscoveredThread:
    """A research thread discovered during the Discovery phase.

    Represents a value driver that may or may not be an official segment.
    """

    thread_id: str
    name: str
    description: str

    thread_type: ThreadType
    priority: int  # 1 = highest

    # Discovery metadata
    discovery_lens: str  # Which of the 7 lenses found this
    is_official_segment: bool
    official_segment_name: str | None = None

    # Research guidance
    value_driver_hypothesis: str = ""
    research_questions: tuple[str, ...] = field(default_factory=tuple)

    # Evidence
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        thread_type: ThreadType,
        priority: int,
        discovery_lens: str,
        is_official_segment: bool = False,
        official_segment_name: str | None = None,
        value_driver_hypothesis: str = "",
        research_questions: list[str] | None = None,
        evidence_ids: list[str] | None = None,
    ) -> DiscoveredThread:
        """Factory method to create a discovered thread."""
        return cls(
            thread_id=generate_id("thread"),
            name=name,
            description=description,
            thread_type=thread_type,
            priority=priority,
            discovery_lens=discovery_lens,
            is_official_segment=is_official_segment,
            official_segment_name=official_segment_name,
            value_driver_hypothesis=value_driver_hypothesis,
            research_questions=tuple(research_questions or []),
            evidence_ids=tuple(evidence_ids or []),
        )


@dataclass
class DiscoveryOutput:
    """Output from the Discovery Agent.

    Contains all discovered value drivers, organized by type.
    """

    # Official segments from 10-K/filings
    official_segments: list[str]

    # All discovered research threads (superset of official)
    research_threads: list[DiscoveredThread]

    # Cross-cutting themes (e.g., "AI monetization across all segments")
    cross_cutting_themes: list[str]

    # Strategic optionality candidates (e.g., Waymo)
    optionality_candidates: list[str]

    # Gaps and uncertainties
    data_gaps: list[str]
    conflicting_signals: list[str]

    # Evidence
    evidence_ids: list[str]

    # Discovery metadata
    discovery_timestamp: datetime = field(default_factory=utc_now)

    def get_threads_by_type(self, thread_type: ThreadType) -> list[DiscoveredThread]:
        """Get threads of a specific type."""
        return [t for t in self.research_threads if t.thread_type == thread_type]

    def get_threads_by_priority(self, max_priority: int = 5) -> list[DiscoveredThread]:
        """Get threads up to a priority level, sorted by priority."""
        return sorted(
            [t for t in self.research_threads if t.priority <= max_priority],
            key=lambda t: t.priority,
        )


# ============== Stage 3: Vertical Analysis Output ==============

@dataclass
class ThesisCase:
    """Bull or bear case for a vertical."""

    narrative: str
    key_assumptions: list[str]
    catalysts: list[str]
    probability: float  # 0.0 to 1.0
    evidence_ids: list[str]


@dataclass
class Risk:
    """A risk identified in analysis."""

    description: str
    probability: str  # "low", "medium", "high"
    impact: str  # "low", "medium", "high"
    mitigation: str | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class VerticalAnalysis:
    """Output from a Vertical Analyst agent.

    Deep analysis of a single research thread/vertical.
    """

    thread_id: str
    vertical_name: str

    # Analysis content
    business_understanding: str
    competitive_position: str
    growth_drivers: list[str]
    key_risks: list[Risk]

    # Investment cases
    bull_case: ThesisCase
    bear_case: ThesisCase

    # Confidence
    overall_confidence: float  # 0.0 to 1.0
    confidence_drivers: list[str]

    # Gaps
    unanswered_questions: list[str]
    data_gaps: list[str]

    # Evidence
    evidence_ids: list[str]


# ============== Stage 4: Synthesis Output ==============

@dataclass
class Scenario:
    """A valuation scenario (bull/base/bear)."""

    name: str  # "bull", "base", "bear"
    probability: float
    narrative: str
    key_assumptions: list[str]


@dataclass
class KeyDebate:
    """A key debate point in the investment thesis."""

    topic: str
    bull_view: str
    bear_view: str
    our_view: str
    resolution_catalyst: str | None = None
    evidence_supporting_bull: list[str] = field(default_factory=list)
    evidence_supporting_bear: list[str] = field(default_factory=list)


@dataclass
class RiskFactor:
    """A risk factor for the investment."""

    description: str
    probability: str  # "low", "medium", "high"
    impact: str  # "low", "medium", "high"
    category: str  # "competitive", "regulatory", "execution", "macro", etc.
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class SynthesisOutput:
    """Output from a Synthesizer agent.

    Combines all vertical analyses into unified investment thesis.
    V1: No DCF, qualitative analysis only.
    """

    # Investment view
    investment_view: str  # "BUY", "HOLD", "SELL"
    conviction: str  # "high", "medium", "low"
    thesis_summary: str

    # Scenarios (qualitative)
    scenarios: dict[str, Scenario]  # "bull", "base", "bear"

    # Key debates
    key_debates: list[KeyDebate]

    # Risks
    risk_factors: list[RiskFactor]

    # Confidence
    overall_confidence: float
    evidence_gaps: list[str]

    # Evidence
    evidence_ids: list[str]

    # Metadata
    synthesizer_model: str  # "claude" or "gpt"
    synthesis_timestamp: datetime = field(default_factory=utc_now)


# ============== Stage 5: Judge Output ==============

@dataclass
class Inconsistency:
    """An inconsistency found between two syntheses."""

    topic: str
    claude_view: str
    gpt_view: str
    severity: str  # "minor", "moderate", "major"
    resolution: str


@dataclass
class JudgeVerdict:
    """Final verdict from the Judge agent.

    Compares Claude and GPT syntheses, produces final unified output.
    """

    # Comparison results
    agreements: list[str]
    inconsistencies: list[Inconsistency]

    # Preference
    preferred_synthesis: str  # "claude", "gpt", or "merged"
    preference_reasoning: str

    # Final output
    final_investment_view: str  # "BUY", "HOLD", "SELL"
    final_conviction: str  # "high", "medium", "low"
    final_thesis: str
    final_confidence: float

    # Key conclusions
    key_risks: list[str]
    key_catalysts: list[str]
    key_uncertainties: list[str]

    # Evidence
    evidence_ids: list[str]

    # Metadata
    judge_timestamp: datetime = field(default_factory=utc_now)
