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
    VERTICALS = "verticals"  # Deep research on research groups
    FACT_CHECK = "fact_check"  # Verification before synthesis
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

    def to_json_payload(self) -> dict[str, Any]:
        """Convert to clean JSON payload for LLM prompts.

        Returns structured JSON that's unambiguous for the LLM to parse.
        Includes FULL transcripts, not truncated.

        Returns:
            Dict ready for json.dumps() in prompts.
        """
        import json

        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "fetched_at": self.fetched_at.isoformat(),
        }

        # Profile - clean subset of useful fields
        if self.profile:
            payload["profile"] = {
                "company_name": self.profile.get("companyName"),
                "sector": self.profile.get("sector"),
                "industry": self.profile.get("industry"),
                "description": self.profile.get("description"),
                "ceo": self.profile.get("ceo"),
                "employees": self.profile.get("fullTimeEmployees"),
                "market_cap": self.profile.get("mktCap"),
                "price": self.profile.get("price"),
                "beta": self.profile.get("beta"),
                "exchange": self.profile.get("exchange"),
                "country": self.profile.get("country"),
                "website": self.profile.get("website"),
            }

        # Income statements - full data, most recent first
        if self.income_statement_annual:
            payload["income_statement_annual"] = [
                {
                    "date": stmt.get("date"),
                    "period": stmt.get("period"),
                    "revenue": stmt.get("revenue"),
                    "cost_of_revenue": stmt.get("costOfRevenue"),
                    "gross_profit": stmt.get("grossProfit"),
                    "gross_profit_ratio": stmt.get("grossProfitRatio"),
                    "operating_expenses": stmt.get("operatingExpenses"),
                    "operating_income": stmt.get("operatingIncome"),
                    "operating_income_ratio": stmt.get("operatingIncomeRatio"),
                    "net_income": stmt.get("netIncome"),
                    "net_income_ratio": stmt.get("netIncomeRatio"),
                    "eps": stmt.get("eps"),
                    "eps_diluted": stmt.get("epsdiluted"),
                    "ebitda": stmt.get("ebitda"),
                    "research_and_development": stmt.get("researchAndDevelopmentExpenses"),
                    "selling_general_admin": stmt.get("sellingGeneralAndAdministrativeExpenses"),
                }
                for stmt in self.income_statement_annual[:5]
            ]

        # Quarterly income - last 8 quarters
        if self.income_statement_quarterly:
            payload["income_statement_quarterly"] = [
                {
                    "date": stmt.get("date"),
                    "period": stmt.get("period"),
                    "revenue": stmt.get("revenue"),
                    "gross_profit": stmt.get("grossProfit"),
                    "operating_income": stmt.get("operatingIncome"),
                    "net_income": stmt.get("netIncome"),
                    "eps": stmt.get("eps"),
                }
                for stmt in self.income_statement_quarterly[:8]
            ]

        # Balance sheet
        if self.balance_sheet_annual:
            payload["balance_sheet_annual"] = [
                {
                    "date": bs.get("date"),
                    "total_assets": bs.get("totalAssets"),
                    "total_liabilities": bs.get("totalLiabilities"),
                    "total_equity": bs.get("totalStockholdersEquity"),
                    "cash_and_equivalents": bs.get("cashAndCashEquivalents"),
                    "short_term_investments": bs.get("shortTermInvestments"),
                    "total_debt": bs.get("totalDebt"),
                    "net_debt": bs.get("netDebt"),
                }
                for bs in self.balance_sheet_annual[:3]
            ]

        # Cash flow
        if self.cash_flow_annual:
            payload["cash_flow_annual"] = [
                {
                    "date": cf.get("date"),
                    "operating_cash_flow": cf.get("operatingCashFlow"),
                    "capital_expenditure": cf.get("capitalExpenditure"),
                    "free_cash_flow": cf.get("freeCashFlow"),
                    "dividends_paid": cf.get("dividendsPaid"),
                    "stock_repurchased": cf.get("commonStockRepurchased"),
                    "acquisitions": cf.get("acquisitionsNet"),
                }
                for cf in self.cash_flow_annual[:3]
            ]

        # Revenue segmentation - FULL data
        if self.revenue_product_segmentation:
            payload["revenue_by_product"] = self.revenue_product_segmentation[:5]

        if self.revenue_geographic_segmentation:
            payload["revenue_by_geography"] = self.revenue_geographic_segmentation[:5]

        # Transcripts - FULL TEXT, not truncated
        if self.transcripts:
            payload["earnings_transcripts"] = [
                {
                    "quarter": t.get("quarter"),
                    "year": t.get("year"),
                    "date": t.get("date"),
                    "source": t.get("source", "unknown"),
                    "full_text": t.get("text") or t.get("content", ""),  # Support both keys
                }
                for t in self.transcripts[:4]
            ]

        # News - headlines with dates
        if self.news:
            payload["recent_news"] = [
                {
                    "date": n.get("publishedDate", "")[:10],
                    "title": n.get("title"),
                    "source": n.get("site"),
                    "url": n.get("url"),
                }
                for n in self.news[:15]
            ]

        # Analyst data
        if self.analyst_estimates:
            payload["analyst_estimates"] = [
                {
                    "date": e.get("date"),
                    "estimated_revenue_avg": e.get("estimatedRevenueAvg"),
                    "estimated_revenue_low": e.get("estimatedRevenueLow"),
                    "estimated_revenue_high": e.get("estimatedRevenueHigh"),
                    "estimated_eps_avg": e.get("estimatedEpsAvg"),
                    "number_analysts_revenue": e.get("numberAnalystEstimatedRevenue"),
                    "number_analysts_eps": e.get("numberAnalystsEstimatedEps"),
                }
                for e in self.analyst_estimates[:4]
            ]

        if self.price_target_consensus:
            payload["price_target_consensus"] = {
                "target_high": self.price_target_consensus.get("targetHigh"),
                "target_low": self.price_target_consensus.get("targetLow"),
                "target_median": self.price_target_consensus.get("targetMedian"),
                "target_consensus": self.price_target_consensus.get("targetConsensus"),
            }

        if self.analyst_grades:
            payload["recent_analyst_grades"] = [
                {
                    "date": g.get("date"),
                    "analyst": g.get("gradingCompany"),
                    "new_grade": g.get("newGrade"),
                    "previous_grade": g.get("previousGrade"),
                }
                for g in self.analyst_grades[:10]
            ]

        return payload

    def to_prompt_string(self, max_tokens: int | None = None) -> str:
        """Convert to JSON string for LLM prompts.

        Args:
            max_tokens: Optional max token limit (estimated by chars/4).
                       Note: Transcripts are NOT truncated regardless of this.

        Returns:
            JSON string with all company context.
        """
        import json

        payload = self.to_json_payload()
        full_text = json.dumps(payload, indent=2, default=str)

        # Truncate if needed (but warn - transcripts should not be truncated)
        if max_tokens:
            max_chars = max_tokens * 4
            if len(full_text) > max_chars:
                # Don't truncate - just log warning and return full
                # Truncating JSON mid-way would break parsing
                pass

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
class ResearchGroup:
    """A group of related verticals for parallel deep research.

    Discovery outputs 2 groups for parallel processing:
    - Group 1: Core Business (established segments)
    - Group 2: Growth & Optionality (emerging/strategic bets)

    Groups should be coherent: verticals in a group share business model,
    valuation method, or research synergies.
    """

    group_id: str
    name: str  # e.g., "Advertising & Core Platforms", "Cloud, AI & Strategic Bets"
    theme: str  # What unifies these verticals

    # Verticals in this group
    vertical_ids: list[str]  # References to DiscoveredThread.thread_id

    # Research guidance
    key_questions: list[str]

    # Grouping justification (new fields from fixed prompt)
    grouping_rationale: str = ""  # Why these verticals belong together
    shared_context: str = ""  # Context that applies to all verticals in group
    valuation_approach: str = ""  # "DCF" / "Mixed" / "Primarily option value"

    # Legacy field for backwards compatibility
    focus: str = ""  # What the deep research agent should focus on


@dataclass
class DiscoveryOutput:
    """Output from the Discovery Agent.

    Contains all discovered value drivers, organized by type.
    """

    # Official segments from 10-K/filings
    official_segments: list[str]

    # All discovered research threads (superset of official)
    research_threads: list[DiscoveredThread]

    # Research groups for parallel deep research (2 groups)
    research_groups: list[ResearchGroup] = field(default_factory=list)

    # Cross-cutting themes (e.g., "AI monetization across all segments")
    cross_cutting_themes: list[str] = field(default_factory=list)

    # Strategic optionality candidates (e.g., Waymo)
    optionality_candidates: list[str] = field(default_factory=list)

    # Gaps and uncertainties
    data_gaps: list[str] = field(default_factory=list)
    conflicting_signals: list[str] = field(default_factory=list)

    # Evidence
    evidence_ids: list[str] = field(default_factory=list)

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

    def get_threads_for_group(self, group: ResearchGroup) -> list[DiscoveredThread]:
        """Get all threads belonging to a research group."""
        return [t for t in self.research_threads if t.thread_id in group.vertical_ids]

    def get_group_by_name(self, name: str) -> ResearchGroup | None:
        """Get a research group by name."""
        for group in self.research_groups:
            return group if group.name == name else None
        return None


# ============== Stage 3: Vertical Analysis Output ==============

@dataclass
class VerticalAnalysis:
    """Output from a Vertical Analyst agent.

    Deep analysis of a single research thread/vertical.
    Contains prose from Deep Research.
    """

    thread_id: str
    vertical_name: str
    business_understanding: str  # The prose research report
    evidence_ids: list[str] = field(default_factory=list)
    overall_confidence: float = 0.0


@dataclass
class GroupResearchOutput:
    """Output from Deep Research for a group of verticals.

    Contains analyses for all verticals in a research group,
    plus cross-vertical insights specific to that group.
    """

    group_id: str
    group_name: str

    # Individual vertical analyses within this group
    vertical_analyses: list[VerticalAnalysis]

    # Cross-vertical insights for this group
    synergies: str  # How verticals in this group interact
    shared_risks: str  # Risks affecting multiple verticals
    group_thesis: str  # Overall view on this research group

    # Research quality
    web_searches_performed: list[dict[str, str]]  # query -> finding
    overall_confidence: float
    data_gaps: list[str]

    # Evidence
    evidence_ids: list[str]


# ============== Stage 4: Synthesis Output ==============

@dataclass
class SynthesisOutput:
    """Output from a Synthesizer agent.

    Contains the full prose equity research report.
    """

    full_report: str = ""  # The complete equity research report (markdown prose)
    investment_view: str = "HOLD"  # "BUY", "HOLD", "SELL"
    conviction: str = "medium"  # "high", "medium", "low"
    overall_confidence: float = 0.5  # 0.0 to 1.0
    thesis_summary: str = ""  # 1-2 sentence summary
    synthesizer_model: str = ""  # "claude" or "gpt"
    evidence_ids: list[str] = field(default_factory=list)
    synthesis_timestamp: datetime = field(default_factory=utc_now)


# ============== Stage 5: Judge Output ==============

@dataclass
class Inconsistency:
    """An inconsistency found between two syntheses."""

    topic: str
    claude_view: str
    gpt_view: str
    resolution: str
    winner: str = "neither"  # "claude", "gpt", or "neither"
    ground_truth_says: str = ""


@dataclass
class Challenge:
    """A challenge issued by the Judge requiring a response.

    Challenges are routed to appropriate agents for resolution.
    """

    challenge_id: str
    target: str  # "discovery", "research_group_1", "research_group_2", "synthesis"
    severity: str  # "critical", "high", "medium"
    issue: str  # What's wrong
    question: str  # Specific question that must be answered
    required_evidence: str  # What evidence would resolve this
    impact_if_unresolved: str  # Why this matters


@dataclass
class Agreement:
    """An agreement between Claude and GPT syntheses."""

    topic: str
    both_say: str
    confidence: str  # "high", "medium", "low"


@dataclass
class Disagreement:
    """A disagreement between Claude and GPT syntheses."""

    topic: str
    claude_says: str
    gpt_says: str
    ground_truth_says: str
    who_is_right: str  # "claude", "gpt", "neither", "unclear"
    resolution: str


@dataclass
class DiscoveryCompleteness:
    """Assessment of discovery completeness."""

    is_complete: bool
    missing_verticals: list[str]
    reasoning: str


@dataclass
class InsightToIncorporate:
    """An insight from the losing synthesis to incorporate."""

    section: str  # Which section of the other report
    what_to_incorporate: str  # The quoted text to add
    why: str  # Why this improves the report
    how_to_integrate: str  # Specific suggestion


@dataclass
class ErrorToFix:
    """An error in the chosen synthesis to fix."""

    location: str  # Where in the report
    error: str  # What's wrong
    correction: str  # How to fix it


@dataclass
class GapToAddress:
    """A gap in the chosen synthesis to address."""

    missing: str  # What's missing
    why_important: str  # Why it matters
    suggestion: str  # How to address it


@dataclass
class EditorialFeedback:
    """Editorial feedback from Judge to Synthesizer.

    The Judge picks a winner and provides specific, actionable feedback
    for that Synthesizer to revise their report.
    """

    # Which synthesis was chosen
    preferred_synthesis: str  # "claude" or "gpt"
    preference_reasoning: str

    # Quality assessment
    claude_score: float
    gpt_score: float
    key_differentiators: list[str]

    # What to incorporate from the losing report
    incorporate_from_other: list[InsightToIncorporate]

    # Errors to fix in the chosen report
    errors_to_fix: list[ErrorToFix]

    # Gaps to address
    gaps_to_address: list[GapToAddress]

    # Detailed revision instructions (3-5 paragraphs)
    revision_instructions: str

    # Confidence adjustment
    current_confidence: float
    recommended_confidence: float
    confidence_reasoning: str

    # Meta assessment
    analysis_quality: str  # "high", "medium", "low"
    key_strengths: list[str]
    key_weaknesses: list[str]


@dataclass
class JudgeVerdict:
    """Final verdict from the Judge agent.

    Now supports deliberation loop with status: "accept" or "challenge".
    """

    # Deliberation status
    status: str  # "accept" or "challenge"
    challenge_round: int = 1

    # Comparison results (both accept and challenge)
    agreements: list[Agreement] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)

    # Challenge-specific (status == "challenge")
    challenges: list[Challenge] = field(default_factory=list)
    discovery_completeness: DiscoveryCompleteness | None = None
    preliminary_lean: dict[str, Any] | None = None  # direction, confidence, blocker

    # Accept-specific (status == "accept")
    resolution_of_disagreements: list[dict[str, str]] = field(default_factory=list)
    preferred_synthesis: str = "merged"  # "claude", "gpt", or "merged"
    preference_reasoning: str = ""

    # Final output (status == "accept")
    final_investment_view: str = "HOLD"  # "BUY", "HOLD", "SELL"
    final_conviction: str = "medium"  # "high", "medium", "low"
    final_thesis: str = ""
    final_confidence: float = 0.5

    # Scenarios (status == "accept")
    scenarios: dict[str, Scenario] = field(default_factory=dict)

    # Key conclusions (status == "accept")
    key_risks: list[dict[str, str]] = field(default_factory=list)
    key_catalysts: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    confidence_reasoning: str = ""

    # Legacy fields for backwards compatibility
    inconsistencies: list[Inconsistency] = field(default_factory=list)
    key_uncertainties: list[str] = field(default_factory=list)

    # Evidence
    evidence_ids: list[str] = field(default_factory=list)

    # Metadata
    judge_timestamp: datetime = field(default_factory=utc_now)
