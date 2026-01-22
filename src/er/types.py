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
    DERIVED = "derived"  # Summaries, EvidenceCards, computed artifacts


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


@dataclass
class TranscriptExtract:
    """Structured extraction from an earnings call transcript.

    Contains targeted excerpts and structured data extracted from transcripts,
    significantly smaller than the full transcript text.
    """

    quarter: str  # e.g., "Q3 2025"
    year: int
    quarter_num: int

    # KPI mentions with context
    kpi_mentions: list[dict[str, Any]] = field(default_factory=list)
    # {"metric": "ARR", "value": "$X", "context": "...", "change_yoy": "+15%"}

    # Guidance changes with quotes
    guidance_changes: list[dict[str, Any]] = field(default_factory=list)
    # {"metric": "Revenue", "old": "$X", "new": "$Y", "direction": "raised", "quote": "..."}

    # Analyst pushback / contentious exchanges
    heated_exchanges: list[str] = field(default_factory=list)

    # Questions management deflected or gave vague answers
    deflected_questions: list[str] = field(default_factory=list)

    # Themes mentioned 3+ times
    repeated_themes: list[str] = field(default_factory=list)

    # First-time mentions (new initiatives, products, markets)
    new_initiatives: list[str] = field(default_factory=list)

    # Key verbatim quotes (max 10 most important)
    key_quotes: list[str] = field(default_factory=list)

    # Management tone indicators
    tone_indicators: dict[str, Any] = field(default_factory=dict)
    # {"overall": "confident", "on_guidance": "cautious", "on_competition": "dismissive"}

    # Raw excerpt for fallback (truncated to ~2000 chars)
    raw_excerpt: str = ""

    def to_prompt_string(self, max_chars: int = 4000) -> str:
        """Convert to a string suitable for LLM prompts."""
        lines = [f"## Transcript Extract: {self.quarter}"]

        if self.kpi_mentions:
            lines.append("\n### Key Metrics Mentioned:")
            for kpi in self.kpi_mentions[:10]:
                lines.append(f"- {kpi.get('metric', 'N/A')}: {kpi.get('value', 'N/A')}")
                if kpi.get('change_yoy'):
                    lines.append(f"  (YoY: {kpi['change_yoy']})")

        if self.guidance_changes:
            lines.append("\n### Guidance Changes:")
            for g in self.guidance_changes[:5]:
                lines.append(f"- {g.get('metric', 'N/A')}: {g.get('direction', 'N/A')}")
                if g.get('quote'):
                    lines.append(f"  \"{g['quote'][:200]}...\"")

        if self.key_quotes:
            lines.append("\n### Key Quotes:")
            for q in self.key_quotes[:5]:
                lines.append(f"- \"{q[:300]}...\"")

        if self.repeated_themes:
            lines.append(f"\n### Repeated Themes: {', '.join(self.repeated_themes[:5])}")

        if self.new_initiatives:
            lines.append(f"\n### New Initiatives: {', '.join(self.new_initiatives[:5])}")

        if self.heated_exchanges:
            lines.append("\n### Notable Analyst Exchanges:")
            for ex in self.heated_exchanges[:3]:
                lines.append(f"- {ex[:200]}...")

        if self.deflected_questions:
            lines.append("\n### Deflected/Vague Responses:")
            for dq in self.deflected_questions[:3]:
                lines.append(f"- {dq[:200]}...")

        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n[truncated]"
        return result


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

    # Quantitative metrics (computed ratios, scores, red flags)
    # Contains: ROIC, quality scores, reinvestment rate, buyback check, red flags
    quant_metrics: dict[str, Any] = field(default_factory=dict)

    # Real-time market data from yfinance (current price, volume, etc.)
    market_data: dict[str, Any] = field(default_factory=dict)

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
            quant_metrics=data.get("quant_metrics", {}),
            market_data=data.get("market_data", {}),
            evidence_ids=tuple(data.get("evidence_ids", [])),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompanyContext":
        """Create CompanyContext from checkpoint dict.

        Handles proper datetime parsing and tuple conversion for evidence_ids.
        """
        # Parse fetched_at as datetime
        fetched_at = data.get("fetched_at")
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at)
        elif fetched_at is None:
            fetched_at = utc_now()

        # Convert evidence_ids to tuple
        evidence_ids = data.get("evidence_ids", [])
        if isinstance(evidence_ids, list):
            evidence_ids = tuple(evidence_ids)

        return cls(
            symbol=data.get("symbol", ""),
            fetched_at=fetched_at,
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
            quant_metrics=data.get("quant_metrics", {}),
            market_data=data.get("market_data", {}),
            evidence_ids=evidence_ids,
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

        # Pre-computed quantitative metrics (ROIC, quality scores, red flags)
        # Critical for discovery and synthesis agents
        if self.quant_metrics:
            payload["quant_metrics"] = self.quant_metrics

        return payload

    def to_prompt_string(self, max_tokens: int | None = None) -> str:
        """Convert to JSON string for LLM prompts.

        Args:
            max_tokens: Optional max token limit (estimated by chars/4).
                       If exceeded, will progressively reduce content.

        Returns:
            JSON string with company context.
        """
        import json
        from er.logging import get_logger
        logger = get_logger(__name__)

        payload = self.to_json_payload()
        full_text = json.dumps(payload, indent=2, default=str)

        if not max_tokens:
            return full_text

        max_chars = max_tokens * 4
        if len(full_text) <= max_chars:
            return full_text

        # Progressive truncation - remove least critical data first
        logger.warning(
            "Context exceeds max_tokens, applying progressive truncation",
            full_chars=len(full_text),
            max_chars=max_chars,
            symbol=self.symbol,
        )

        # Priority 1: Remove full transcript text (keep metadata)
        if "earnings_transcripts" in payload:
            for t in payload["earnings_transcripts"]:
                if "full_text" in t:
                    t["full_text"] = "[TRUNCATED - use transcript_extracts instead]"

        text = json.dumps(payload, indent=2, default=str)
        if len(text) <= max_chars:
            logger.info("Truncated transcripts to fit context", new_chars=len(text))
            return text

        # Priority 2: Remove older quarterly statements (keep last 4)
        if "income_statement_quarterly" in payload:
            payload["income_statement_quarterly"] = payload["income_statement_quarterly"][:4]

        text = json.dumps(payload, indent=2, default=str)
        if len(text) <= max_chars:
            return text

        # Priority 3: Remove news beyond top 5
        if "recent_news" in payload:
            payload["recent_news"] = payload["recent_news"][:5]

        text = json.dumps(payload, indent=2, default=str)
        if len(text) <= max_chars:
            return text

        # Priority 4: Remove analyst grades
        if "recent_analyst_grades" in payload:
            del payload["recent_analyst_grades"]

        text = json.dumps(payload, indent=2, default=str)
        if len(text) <= max_chars:
            return text

        # Priority 5: Remove older annual statements
        if "income_statement_annual" in payload:
            payload["income_statement_annual"] = payload["income_statement_annual"][:2]
        if "balance_sheet_annual" in payload:
            payload["balance_sheet_annual"] = payload["balance_sheet_annual"][:1]
        if "cash_flow_annual" in payload:
            payload["cash_flow_annual"] = payload["cash_flow_annual"][:1]

        text = json.dumps(payload, indent=2, default=str)
        logger.warning(
            "Aggressive truncation applied",
            final_chars=len(text),
            max_chars=max_chars,
        )
        return text

    def for_discovery(self) -> str:
        """Context view for Stage 2 Discovery.

        Includes: Full financials, news headlines, transcripts with latest quarter full text.
        Optimized for initial research thread identification.
        """
        import json

        payload = self.to_json_payload()

        # Keep latest transcript full text; truncate older transcripts for discovery
        if "earnings_transcripts" in payload:
            transcripts = payload["earnings_transcripts"]
            latest_idx = 0
            latest_dt = None
            for idx, t in enumerate(transcripts):
                dt = None
                date_str = t.get("date")
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str)
                    except ValueError:
                        dt = None
                if dt is None:
                    year = t.get("year")
                    quarter = t.get("quarter")
                    if year and quarter:
                        try:
                            dt = datetime(int(year), int(quarter) * 3, 1)
                        except (TypeError, ValueError):
                            dt = None
                if dt and (latest_dt is None or dt > latest_dt):
                    latest_dt = dt
                    latest_idx = idx

            for idx, t in enumerate(transcripts):
                if idx == latest_idx:
                    continue
                if "full_text" in t and len(t.get("full_text", "")) > 2000:
                    # Keep first 2000 chars as preview
                    t["full_text"] = t["full_text"][:2000] + "\n[...transcript continues...]"

        return json.dumps(payload, indent=2, default=str)

    def for_deep_research(self, verticals: list[str] | None = None) -> str:
        """Context view for Stage 3 Deep Research.

        Includes: Full financials, segmentation, full transcripts.
        Verticals parameter reserved for future filtering.
        """
        import json

        payload = self.to_json_payload()
        return json.dumps(payload, indent=2, default=str)

    def for_synthesis(self) -> dict[str, Any]:
        """Context view for Stage 4 Synthesis.

        Compact dict with: profile + latest quarter + key multiples + quant_metrics + market_data.
        Suitable for passing to synthesizer agent.

        Returns:
            Dict with essential synthesis context.
        """
        payload: dict[str, Any] = {
            "symbol": self.symbol,
        }

        # Profile summary
        if self.profile:
            payload["profile"] = {
                "company_name": self.profile.get("companyName"),
                "sector": self.profile.get("sector"),
                "industry": self.profile.get("industry"),
                "market_cap": self.profile.get("mktCap"),
            }

        # Only latest quarter for quick reference
        if self.income_statement_quarterly:
            stmt = self.income_statement_quarterly[0]
            payload["latest_quarter"] = {
                "date": stmt.get("date"),
                "revenue": stmt.get("revenue"),
                "net_income": stmt.get("netIncome"),
                "eps": stmt.get("eps"),
            }

        # Key multiples from price target consensus
        if self.price_target_consensus:
            payload["price_target_consensus"] = {
                "target_median": self.price_target_consensus.get("targetMedian"),
                "target_consensus": self.price_target_consensus.get("targetConsensus"),
            }

        # Quant metrics - critical for synthesis quality assessment
        if self.quant_metrics:
            payload["quant_metrics"] = self.quant_metrics

        # Real-time market data
        if self.market_data:
            payload["market_data"] = self.market_data

        return payload

    def for_verification(self) -> dict[str, Any]:
        """Context view for Verification Agent.

        Full dict with: financial statements + segment data + quant_metrics + market_data.
        Used for fact-checking numeric claims against ground truth.

        Returns:
            Dict with comprehensive financial data for verification.
        """
        payload: dict[str, Any] = {
            "symbol": self.symbol,
        }

        # Profile
        if self.profile:
            payload["profile"] = {
                "company_name": self.profile.get("companyName"),
                "sector": self.profile.get("sector"),
                "industry": self.profile.get("industry"),
                "market_cap": self.profile.get("mktCap"),
                "price": self.profile.get("price"),
            }

        # Full income statements for verification
        if self.income_statement_annual:
            payload["income_statement_annual"] = [
                {
                    "date": stmt.get("date"),
                    "period": stmt.get("period"),
                    "revenue": stmt.get("revenue"),
                    "gross_profit": stmt.get("grossProfit"),
                    "gross_profit_ratio": stmt.get("grossProfitRatio"),
                    "operating_income": stmt.get("operatingIncome"),
                    "operating_income_ratio": stmt.get("operatingIncomeRatio"),
                    "net_income": stmt.get("netIncome"),
                    "net_income_ratio": stmt.get("netIncomeRatio"),
                    "eps": stmt.get("eps"),
                    "eps_diluted": stmt.get("epsdiluted"),
                    "ebitda": stmt.get("ebitda"),
                }
                for stmt in self.income_statement_annual[:5]
            ]

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

        # Balance sheet for verification
        if self.balance_sheet_annual:
            payload["balance_sheet_annual"] = [
                {
                    "date": bs.get("date"),
                    "total_assets": bs.get("totalAssets"),
                    "total_liabilities": bs.get("totalLiabilities"),
                    "total_equity": bs.get("totalStockholdersEquity"),
                    "cash_and_equivalents": bs.get("cashAndCashEquivalents"),
                    "total_debt": bs.get("totalDebt"),
                    "net_debt": bs.get("netDebt"),
                }
                for bs in self.balance_sheet_annual[:3]
            ]

        # Cash flow for verification
        if self.cash_flow_annual:
            payload["cash_flow_annual"] = [
                {
                    "date": cf.get("date"),
                    "operating_cash_flow": cf.get("operatingCashFlow"),
                    "capital_expenditure": cf.get("capitalExpenditure"),
                    "free_cash_flow": cf.get("freeCashFlow"),
                }
                for cf in self.cash_flow_annual[:3]
            ]

        # Revenue segmentation
        if self.revenue_product_segmentation:
            payload["revenue_by_product"] = self.revenue_product_segmentation[:5]

        if self.revenue_geographic_segmentation:
            payload["revenue_by_geography"] = self.revenue_geographic_segmentation[:5]

        # Quant metrics - critical for verification
        if self.quant_metrics:
            payload["quant_metrics"] = self.quant_metrics

        # Market data
        if self.market_data:
            payload["market_data"] = self.market_data

        return payload

    def for_judge(self) -> str:
        """Context view for Stage 5 Judge.

        Key metrics only for claim validation.
        Includes: profile, key financials, price targets.
        """
        import json

        payload: dict[str, Any] = {
            "symbol": self.symbol,
        }

        # Profile
        if self.profile:
            payload["profile"] = {
                "company_name": self.profile.get("companyName"),
                "sector": self.profile.get("sector"),
                "industry": self.profile.get("industry"),
                "market_cap": self.profile.get("mktCap"),
                "price": self.profile.get("price"),
            }

        # Key financials for fact-checking
        if self.income_statement_annual:
            stmt = self.income_statement_annual[0]
            payload["latest_annual"] = {
                "date": stmt.get("date"),
                "revenue": stmt.get("revenue"),
                "gross_profit": stmt.get("grossProfit"),
                "operating_income": stmt.get("operatingIncome"),
                "net_income": stmt.get("netIncome"),
                "eps": stmt.get("eps"),
            }

        if self.income_statement_quarterly:
            stmt = self.income_statement_quarterly[0]
            payload["latest_quarter"] = {
                "date": stmt.get("date"),
                "revenue": stmt.get("revenue"),
                "net_income": stmt.get("netIncome"),
                "eps": stmt.get("eps"),
            }

        # Balance sheet summary
        if self.balance_sheet_annual:
            bs = self.balance_sheet_annual[0]
            payload["balance_sheet"] = {
                "total_assets": bs.get("totalAssets"),
                "total_debt": bs.get("totalDebt"),
                "net_debt": bs.get("netDebt"),
                "total_equity": bs.get("totalStockholdersEquity"),
            }

        # Price targets
        if self.price_target_consensus:
            payload["price_target_consensus"] = self.price_target_consensus

        # Quant metrics - critical for fact-checking claims (ROIC, buyback distortion, red flags)
        if self.quant_metrics:
            payload["quant_metrics"] = self.quant_metrics

        return json.dumps(payload, indent=2, default=str)

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
    review_guidance: str = ""  # Human guidance for this group

    # Grouping justification (new fields from fixed prompt)
    grouping_rationale: str = ""  # Why these verticals belong together
    shared_context: str = ""  # Context that applies to all verticals in group
    valuation_approach: str = ""  # "DCF" / "Mixed" / "Primarily option value"

    # Legacy field for backwards compatibility
    focus: str = ""  # What the deep research agent should focus on


@dataclass
class ThreadBrief:
    """Brief for a research thread - explains WHY it was prioritized.

    Contains rationale, hypotheses, and evidence pointers for each thread.
    Used to preserve context across stage handoffs.
    """

    thread_id: str
    rationale: str  # Why this thread was prioritized
    hypotheses: list[str]  # Key hypotheses to test
    key_questions: list[str]  # Questions to answer
    required_evidence: list[str]  # What evidence is needed
    key_evidence_ids: list[str] = field(default_factory=list)  # Supporting evidence
    recent_developments: list[str] = field(default_factory=list)  # 30/60/90-day updates
    recency_questions: list[str] = field(default_factory=list)  # Questions to expand scope
    recency_evidence_ids: list[str] = field(default_factory=list)  # Evidence IDs for recency
    confidence: float = 0.5  # 0.0-1.0 confidence in importance

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "thread_id": self.thread_id,
            "rationale": self.rationale,
            "hypotheses": self.hypotheses,
            "key_questions": self.key_questions,
            "required_evidence": self.required_evidence,
            "key_evidence_ids": self.key_evidence_ids,
            "recent_developments": self.recent_developments,
            "recency_questions": self.recency_questions,
            "recency_evidence_ids": self.recency_evidence_ids,
            "confidence": self.confidence,
        }


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

    # ThreadBriefs - preserves WHY each thread was prioritized
    thread_briefs: list[ThreadBrief] = field(default_factory=list)

    # Search metadata (internal discovery web search queries)
    searches_performed: list[dict[str, str]] = field(default_factory=list)

    # Lens outputs from Discovery subagents (competitive analysis, analyst views, etc.)
    # This preserves the raw findings so Deep Research can build on them
    lens_outputs: dict = field(default_factory=dict)

    # External threats identified by threat-analysis subagent
    # Each threat is mapped to affected verticals
    external_threats: list = field(default_factory=list)

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
            if group.name == name:
                return group
        return None


# ============== Stage 3: Vertical Analysis Output ==============


class FactCategory(str, Enum):
    """Categories for research facts."""

    FINANCIAL = "financial"  # Revenue, growth, margins from company data
    COMPETITIVE = "competitive"  # Market share, competitor moves
    DEVELOPMENT = "development"  # Recent news, product launches, deals
    RISK = "risk"  # Risk factors and uncertainties
    TAILWIND = "tailwind"  # Positive growth factors
    HEADWIND = "headwind"  # Negative growth factors
    ANALYST = "analyst"  # Analyst views and estimates
    OTHER = "other"


@dataclass
class Fact:
    """A verified fact extracted from research.

    Each fact is atomic, citable, and traceable to evidence.
    The synthesizer builds arguments from these facts.
    """

    fact_id: str
    statement: str  # The factual claim
    category: FactCategory
    evidence_id: str  # ID of supporting evidence
    source: str  # Human-readable source (e.g., "SEC 10-Q", "Bloomberg")
    evidence_ids: list[str] = field(default_factory=list)  # Optional multi-cite evidence IDs
    source_date: str | None = None  # When the source was published
    confidence: float = 0.5  # 0.0-1.0 confidence in this fact
    vertical_id: str | None = None  # Which vertical this fact relates to

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "fact_id": self.fact_id,
            "statement": self.statement,
            "category": self.category.value,
            "evidence_id": self.evidence_id,
            "evidence_ids": self.evidence_ids,
            "source": self.source,
            "source_date": self.source_date,
            "confidence": self.confidence,
            "vertical_id": self.vertical_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fact":
        """Create Fact from dict."""
        evidence_ids = data.get("evidence_ids")
        if not evidence_ids and data.get("evidence_id"):
            evidence_ids = [data.get("evidence_id")]
        return cls(
            fact_id=data["fact_id"],
            statement=data["statement"],
            category=FactCategory(data["category"]),
            evidence_id=data.get("evidence_id", ""),
            evidence_ids=evidence_ids or [],
            source=data["source"],
            source_date=data.get("source_date"),
            confidence=data.get("confidence", 0.5),
            vertical_id=data.get("vertical_id"),
        )


@dataclass
class VerticalDossier:
    """Structured research output for a single vertical.

    Contains:
    - Extracted facts with evidence IDs
    - Analysis narrative
    - Metadata for synthesis
    """

    dossier_id: str
    thread_id: str
    vertical_name: str

    # Structured facts extracted from research
    facts: list[Fact]

    # Narrative analysis (prose from Deep Research)
    analysis_narrative: str

    # Metadata
    research_questions_answered: list[str]
    unanswered_questions: list[str]
    data_gaps: list[str]

    # Quality metrics
    source_count: int = 0
    recent_source_count: int = 0  # Sources from last 60 days
    confidence: float = 0.5

    # Evidence tracking
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "dossier_id": self.dossier_id,
            "thread_id": self.thread_id,
            "vertical_name": self.vertical_name,
            "facts": [f.to_dict() for f in self.facts],
            "analysis_narrative": self.analysis_narrative,
            "research_questions_answered": self.research_questions_answered,
            "unanswered_questions": self.unanswered_questions,
            "data_gaps": self.data_gaps,
            "source_count": self.source_count,
            "recent_source_count": self.recent_source_count,
            "confidence": self.confidence,
            "evidence_ids": self.evidence_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerticalDossier":
        """Create VerticalDossier from dict."""
        return cls(
            dossier_id=data["dossier_id"],
            thread_id=data["thread_id"],
            vertical_name=data["vertical_name"],
            facts=[Fact.from_dict(f) for f in data.get("facts", [])],
            analysis_narrative=data["analysis_narrative"],
            research_questions_answered=data.get("research_questions_answered", []),
            unanswered_questions=data.get("unanswered_questions", []),
            data_gaps=data.get("data_gaps", []),
            source_count=data.get("source_count", 0),
            recent_source_count=data.get("recent_source_count", 0),
            confidence=data.get("confidence", 0.5),
            evidence_ids=data.get("evidence_ids", []),
        )

    def get_facts_by_category(self, category: FactCategory) -> list[Fact]:
        """Get facts filtered by category."""
        return [f for f in self.facts if f.category == category]

    def get_high_confidence_facts(self, threshold: float = 0.7) -> list[Fact]:
        """Get facts above confidence threshold."""
        return [f for f in self.facts if f.confidence >= threshold]


@dataclass
class VerticalAnalysis:
    """Output from a Vertical Analyst agent.

    Deep analysis of a single research thread/vertical.
    Contains prose from Deep Research and structured facts.
    """

    thread_id: str
    vertical_name: str
    business_understanding: str  # The prose research report
    evidence_ids: list[str] = field(default_factory=list)
    overall_confidence: float = 0.0

    # Structured output (Phase 6)
    facts: list[Fact] = field(default_factory=list)
    dossier: VerticalDossier | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "thread_id": self.thread_id,
            "vertical_name": self.vertical_name,
            "business_understanding": self.business_understanding,
            "evidence_ids": self.evidence_ids,
            "overall_confidence": self.overall_confidence,
            "facts": [f.to_dict() for f in self.facts],
            "dossier": self.dossier.to_dict() if self.dossier else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerticalAnalysis":
        """Create VerticalAnalysis from checkpoint dict.

        Properly reconstructs nested Fact and VerticalDossier objects.
        """
        # Reconstruct facts
        facts = []
        for f in data.get("facts", []):
            if isinstance(f, dict):
                facts.append(Fact.from_dict(f))
            elif isinstance(f, Fact):
                facts.append(f)

        # Reconstruct dossier
        dossier_data = data.get("dossier")
        dossier = None
        if dossier_data and isinstance(dossier_data, dict):
            dossier = VerticalDossier.from_dict(dossier_data)
        elif isinstance(dossier_data, VerticalDossier):
            dossier = dossier_data

        return cls(
            thread_id=data.get("thread_id", ""),
            vertical_name=data.get("vertical_name", ""),
            business_understanding=data.get("business_understanding", ""),
            evidence_ids=data.get("evidence_ids", []),
            overall_confidence=data.get("overall_confidence", 0.0),
            facts=facts,
            dossier=dossier,
        )


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


# ============== Stage 3.5: Verification Output ==============


class VerificationStatus(str, Enum):
    """Status of a fact after verification."""

    VERIFIED = "verified"  # Fact matches ground truth data
    CONTRADICTED = "contradicted"  # Fact contradicts ground truth data
    UNVERIFIABLE = "unverifiable"  # Cannot verify against available data
    PARTIAL = "partial"  # Partially verified (some aspects match, some don't)


@dataclass
class VerifiedFact:
    """A fact that has been through verification.

    Extends the original Fact with verification status and notes.
    """

    original_fact: Fact
    status: VerificationStatus
    verification_notes: str  # Explanation of verification result
    ground_truth_source: str | None = None  # What data was used to verify
    confidence_adjustment: float = 0.0  # Adjustment to original confidence

    @property
    def adjusted_confidence(self) -> float:
        """Get confidence after adjustment."""
        base = self.original_fact.confidence
        return max(0.0, min(1.0, base + self.confidence_adjustment))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "original_fact": self.original_fact.to_dict(),
            "status": self.status.value,
            "verification_notes": self.verification_notes,
            "ground_truth_source": self.ground_truth_source,
            "confidence_adjustment": self.confidence_adjustment,
            "adjusted_confidence": self.adjusted_confidence,
        }


@dataclass
class VerificationResult:
    """Result of verifying facts for a single vertical."""

    vertical_name: str
    thread_id: str
    verified_facts: list[VerifiedFact]

    # Summary stats
    verified_count: int = 0
    contradicted_count: int = 0
    unverifiable_count: int = 0

    # Critical issues found
    critical_contradictions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "vertical_name": self.vertical_name,
            "thread_id": self.thread_id,
            "verified_facts": [vf.to_dict() for vf in self.verified_facts],
            "verified_count": self.verified_count,
            "contradicted_count": self.contradicted_count,
            "unverifiable_count": self.unverifiable_count,
            "critical_contradictions": self.critical_contradictions,
        }


@dataclass
class VerifiedResearchPackage:
    """Output from the Verification Agent.

    Contains all research with verification status.
    This is the input to the Synthesizer.
    """

    ticker: str
    verification_results: list[VerificationResult]

    # All verified facts across verticals (for easy access)
    all_verified_facts: list[VerifiedFact] = field(default_factory=list)

    # Summary
    total_facts: int = 0
    verified_count: int = 0
    contradicted_count: int = 0
    unverifiable_count: int = 0

    # Critical issues (facts that contradict ground truth)
    critical_issues: list[str] = field(default_factory=list)

    # Original research (passed through)
    group_outputs: list[GroupResearchOutput] = field(default_factory=list)

    # Evidence
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "verification_results": [vr.to_dict() for vr in self.verification_results],
            "total_facts": self.total_facts,
            "verified_count": self.verified_count,
            "contradicted_count": self.contradicted_count,
            "unverifiable_count": self.unverifiable_count,
            "critical_issues": self.critical_issues,
            "evidence_ids": self.evidence_ids,
        }

    def get_verified_facts(self, min_confidence: float = 0.5) -> list[VerifiedFact]:
        """Get only verified facts above confidence threshold."""
        return [
            vf for vf in self.all_verified_facts
            if vf.status == VerificationStatus.VERIFIED
            and vf.adjusted_confidence >= min_confidence
        ]

    def get_contradicted_facts(self) -> list[VerifiedFact]:
        """Get all contradicted facts."""
        return [
            vf for vf in self.all_verified_facts
            if vf.status == VerificationStatus.CONTRADICTED
        ]


# ============== Stage 3.75: Integration Output ==============


class RelationshipType(str, Enum):
    """Type of relationship between verticals."""

    DEPENDENCY = "dependency"  # A depends on B
    SYNERGY = "synergy"  # A and B reinforce each other
    COMPETITION = "competition"  # A and B compete for resources
    SHARED_RISK = "shared_risk"  # A and B share same risk exposure
    CANNIBALIZATION = "cannibalization"  # A growth hurts B


@dataclass
class VerticalRelationship:
    """A relationship between two verticals."""

    source_vertical: str  # Vertical ID or name
    target_vertical: str  # Vertical ID or name
    relationship_type: RelationshipType
    description: str
    strength: str  # "high", "medium", "low"
    supporting_facts: list[str]  # Fact IDs or statements

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "source_vertical": self.source_vertical,
            "target_vertical": self.target_vertical,
            "relationship_type": self.relationship_type.value,
            "description": self.description,
            "strength": self.strength,
            "supporting_facts": self.supporting_facts,
        }


@dataclass
class SharedRisk:
    """A risk that affects multiple verticals."""

    risk_description: str
    affected_verticals: list[str]
    severity: str  # "high", "medium", "low"
    probability: str  # "high", "medium", "low"
    mitigation_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "risk_description": self.risk_description,
            "affected_verticals": self.affected_verticals,
            "severity": self.severity,
            "probability": self.probability,
            "mitigation_notes": self.mitigation_notes,
        }


@dataclass
class CrossVerticalInsight:
    """An insight that emerges from cross-vertical analysis."""

    insight: str
    related_verticals: list[str]
    implication: str  # What this means for the investment thesis
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "insight": self.insight,
            "related_verticals": self.related_verticals,
            "implication": self.implication,
            "confidence": self.confidence,
        }


@dataclass
class CrossVerticalMap:
    """Output from the Integrator Agent.

    Maps relationships, dependencies, and shared risks across verticals.
    This helps the synthesizer build a coherent narrative.
    """

    ticker: str

    # Relationships between verticals
    relationships: list[VerticalRelationship]

    # Risks that span multiple verticals
    shared_risks: list[SharedRisk]

    # High-level insights from cross-vertical analysis
    cross_vertical_insights: list[CrossVerticalInsight]

    # Key dependencies to highlight in synthesis
    key_dependencies: list[str]

    # Verticals that are foundational (others depend on them)
    foundational_verticals: list[str]

    # Evidence
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "relationships": [r.to_dict() for r in self.relationships],
            "shared_risks": [sr.to_dict() for sr in self.shared_risks],
            "cross_vertical_insights": [cvi.to_dict() for cvi in self.cross_vertical_insights],
            "key_dependencies": self.key_dependencies,
            "foundational_verticals": self.foundational_verticals,
            "evidence_ids": self.evidence_ids,
        }

    def get_relationships_for_vertical(self, vertical: str) -> list[VerticalRelationship]:
        """Get all relationships involving a specific vertical."""
        return [
            r for r in self.relationships
            if r.source_vertical == vertical or r.target_vertical == vertical
        ]

    def get_risks_for_vertical(self, vertical: str) -> list[SharedRisk]:
        """Get all shared risks affecting a specific vertical."""
        return [
            sr for sr in self.shared_risks
            if vertical in sr.affected_verticals
        ]


# ============== Stage 3.9: Valuation Pack (Optional) ==============


@dataclass
class ComparableCompany:
    """A comparable company for valuation purposes."""

    ticker: str
    name: str
    market_cap: float | None = None
    pe_ratio: float | None = None
    ev_revenue: float | None = None
    ev_ebitda: float | None = None
    revenue_growth: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "market_cap": self.market_cap,
            "pe_ratio": self.pe_ratio,
            "ev_revenue": self.ev_revenue,
            "ev_ebitda": self.ev_ebitda,
            "revenue_growth": self.revenue_growth,
            "notes": self.notes,
        }


@dataclass
class HistoricalValuation:
    """Historical valuation range for the company."""

    metric: str  # "P/E", "EV/Revenue", "EV/EBITDA"
    current: float | None = None
    historical_low: float | None = None
    historical_high: float | None = None
    historical_avg: float | None = None
    percentile: float | None = None  # Where current sits vs history (0-100)
    period: str = "5Y"  # Time period for history

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "metric": self.metric,
            "current": self.current,
            "historical_low": self.historical_low,
            "historical_high": self.historical_high,
            "historical_avg": self.historical_avg,
            "percentile": self.percentile,
            "period": self.period,
        }


@dataclass
class ValuationPack:
    """Optional valuation data pack for synthesis.

    Contains:
    - Comparable companies with multiples
    - Historical valuation ranges
    - Relative valuation assessment
    """

    ticker: str

    # Comparable companies
    comparables: list[ComparableCompany]

    # Historical valuation ranges
    historical_valuations: list[HistoricalValuation]

    # Summary metrics
    peer_median_pe: float | None = None
    peer_median_ev_revenue: float | None = None
    premium_discount_to_peers: float | None = None  # % premium (+) or discount (-)

    # Commentary
    valuation_summary: str = ""
    key_valuation_debates: list[str] = field(default_factory=list)

    # Evidence
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "comparables": [c.to_dict() for c in self.comparables],
            "historical_valuations": [hv.to_dict() for hv in self.historical_valuations],
            "peer_median_pe": self.peer_median_pe,
            "peer_median_ev_revenue": self.peer_median_ev_revenue,
            "premium_discount_to_peers": self.premium_discount_to_peers,
            "valuation_summary": self.valuation_summary,
            "key_valuation_debates": self.key_valuation_debates,
            "evidence_ids": self.evidence_ids,
        }


# ============== Stage 4: Synthesis Output ==============


@dataclass
class Scenario:
    """Investment scenario (bull/base/bear case).

    Used in synthesis and judge outputs for probability-weighted outcomes.
    """

    probability: float  # 0.0 to 1.0
    headline: str  # Short description of the scenario
    description: str = ""  # Detailed description
    key_assumptions: list[str] = field(default_factory=list)
    target_price: float | None = None  # Optional price target for this scenario

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "probability": self.probability,
            "headline": self.headline,
            "description": self.description,
            "key_assumptions": self.key_assumptions,
            "target_price": self.target_price,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        """Create from dict."""
        return cls(
            probability=data.get("probability", 0.0),
            headline=data.get("headline", ""),
            description=data.get("description", ""),
            key_assumptions=data.get("key_assumptions", []),
            target_price=data.get("target_price"),
        )


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

    Can also reject both syntheses if quality is unacceptable.
    """

    # Which synthesis was chosen (or "reject_both")
    preferred_synthesis: str  # "claude" | "gpt" | "reject_both"
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

    # Rejection reason (only set if preferred_synthesis == "reject_both")
    # Placed at end because it has a default value
    rejection_reason: str | None = None


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


# =============================================================================
# Coverage & Recency Types (Institutional-Grade Hardening)
# =============================================================================


class CoverageCategory(str, Enum):
    """Categories for coverage auditing."""

    RECENT_DEVELOPMENTS = "recent_developments"  # <= 90 days
    COMPETITIVE_MOVES = "competitive_moves"
    PRODUCT_ROADMAP = "product_roadmap"
    REGULATORY_LITIGATION = "regulatory_litigation"
    CAPITAL_ALLOCATION = "capital_allocation"  # buybacks, M&A
    SEGMENT_ECONOMICS = "segment_economics"
    AI_INFRASTRUCTURE = "ai_infrastructure"  # for relevant companies
    MANAGEMENT_TONE = "management_tone"  # transcript contradictions


class CoverageStatus(str, Enum):
    """Status of coverage for a category."""

    PASS = "pass"
    MARGINAL = "marginal"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class CoverageCategoryResult:
    """Result of coverage check for a single category."""

    category: CoverageCategory
    required_min_cards: int
    found_cards: int
    queries_run: list[str]
    top_evidence_ids: list[str]
    status: CoverageStatus
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "category": self.category.value,
            "required_min_cards": self.required_min_cards,
            "found_cards": self.found_cards,
            "queries_run": self.queries_run,
            "top_evidence_ids": self.top_evidence_ids,
            "status": self.status.value,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoverageCategoryResult":
        """Create from dict."""
        return cls(
            category=CoverageCategory(data["category"]),
            required_min_cards=data["required_min_cards"],
            found_cards=data["found_cards"],
            queries_run=data["queries_run"],
            top_evidence_ids=data["top_evidence_ids"],
            status=CoverageStatus(data["status"]),
            notes=data.get("notes", ""),
        )


@dataclass
class CoverageScorecard:
    """Overall coverage scorecard for a research run."""

    ticker: str
    as_of_date: str
    recency_days: int
    results: list[CoverageCategoryResult]
    overall_status: CoverageStatus
    pass_rate: float = 0.0
    total_evidence_cards: int = 0
    total_queries_run: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "recency_days": self.recency_days,
            "results": [r.to_dict() for r in self.results],
            "overall_status": self.overall_status.value,
            "pass_rate": self.pass_rate,
            "total_evidence_cards": self.total_evidence_cards,
            "total_queries_run": self.total_queries_run,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoverageScorecard":
        """Create from dict."""
        return cls(
            ticker=data["ticker"],
            as_of_date=data["as_of_date"],
            recency_days=data["recency_days"],
            results=[CoverageCategoryResult.from_dict(r) for r in data["results"]],
            overall_status=CoverageStatus(data["overall_status"]),
            pass_rate=data.get("pass_rate", 0.0),
            total_evidence_cards=data.get("total_evidence_cards", 0),
            total_queries_run=data.get("total_queries_run", 0),
        )


@dataclass
class CoverageAction:
    """Record of a coverage gap-filling action."""

    category: CoverageCategory
    query: str
    urls_fetched: list[str]
    evidence_ids: list[str]
    success: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "category": self.category.value,
            "query": self.query,
            "urls_fetched": self.urls_fetched,
            "evidence_ids": self.evidence_ids,
            "success": self.success,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoverageAction":
        """Create from dict."""
        return cls(
            category=CoverageCategory(data["category"]),
            query=data["query"],
            urls_fetched=data["urls_fetched"],
            evidence_ids=data["evidence_ids"],
            success=data["success"],
            notes=data.get("notes", ""),
        )


@dataclass
class RecencyFinding:
    """A finding from recency guard checking outdated priors."""

    hypothesis: str  # What might be outdated
    query: str  # Query used to check
    finding: str  # What was found
    status: str  # "confirmed", "denied", "inconclusive"
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "hypothesis": self.hypothesis,
            "query": self.query,
            "finding": self.finding,
            "status": self.status,
            "evidence_ids": self.evidence_ids,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecencyFinding":
        """Create from dict."""
        return cls(
            hypothesis=data["hypothesis"],
            query=data["query"],
            finding=data["finding"],
            status=data["status"],
            evidence_ids=data.get("evidence_ids", []),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class RecencyGuardOutput:
    """Output from the RecencyGuard agent."""

    ticker: str
    as_of_date: str
    outdated_priors_checked: list[str]
    findings: list[RecencyFinding]
    forced_queries: list[str]
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "outdated_priors_checked": self.outdated_priors_checked,
            "findings": [f.to_dict() for f in self.findings],
            "forced_queries": self.forced_queries,
            "evidence_ids": self.evidence_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecencyGuardOutput":
        """Create from dict."""
        return cls(
            ticker=data["ticker"],
            as_of_date=data["as_of_date"],
            outdated_priors_checked=data["outdated_priors_checked"],
            findings=[RecencyFinding.from_dict(f) for f in data["findings"]],
            forced_queries=data["forced_queries"],
            evidence_ids=data.get("evidence_ids", []),
        )


# =============================================================================
# ClaimGraph + Entailment Types
# =============================================================================


class ClaimType(str, Enum):
    """Types of claims in a report."""

    FACT = "fact"  # Verifiable statement
    INFERENCE = "inference"  # Derived conclusion
    FORECAST = "forecast"  # Forward-looking prediction
    OPINION = "opinion"  # Subjective assessment


class EntailmentStatus(str, Enum):
    """Whether evidence supports a claim."""

    SUPPORTED = "supported"
    WEAK = "weak"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


@dataclass
class Claim:
    """A claim extracted from a report or dossier."""

    claim_id: str
    text: str
    claim_type: ClaimType
    section: str  # Where in the report this appears
    cited_evidence_ids: list[str] = field(default_factory=list)
    linked_fact_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "claim_type": self.claim_type.value,
            "section": self.section,
            "cited_evidence_ids": self.cited_evidence_ids,
            "linked_fact_ids": self.linked_fact_ids,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        """Create from dict."""
        return cls(
            claim_id=data["claim_id"],
            text=data["text"],
            claim_type=ClaimType(data["claim_type"]),
            section=data["section"],
            cited_evidence_ids=data.get("cited_evidence_ids", []),
            linked_fact_ids=data.get("linked_fact_ids", []),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class ClaimGraph:
    """Graph of claims with links to facts and evidence."""

    ticker: str
    source: str  # "vertical_dossiers" or "synthesis"
    claims: list[Claim]
    total_claims: int = 0
    cited_claims: int = 0
    uncited_claims: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "source": self.source,
            "claims": [c.to_dict() for c in self.claims],
            "total_claims": self.total_claims,
            "cited_claims": self.cited_claims,
            "uncited_claims": self.uncited_claims,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaimGraph":
        """Create from dict."""
        return cls(
            ticker=data["ticker"],
            source=data["source"],
            claims=[Claim.from_dict(c) for c in data["claims"]],
            total_claims=data.get("total_claims", 0),
            cited_claims=data.get("cited_claims", 0),
            uncited_claims=data.get("uncited_claims", 0),
        )


@dataclass
class EntailmentResult:
    """Result of entailment check for a single claim."""

    claim_id: str
    status: EntailmentStatus
    rationale: str
    evidence_snippets: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "rationale": self.rationale,
            "evidence_snippets": self.evidence_snippets,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntailmentResult":
        """Create from dict."""
        return cls(
            claim_id=data["claim_id"],
            status=EntailmentStatus(data["status"]),
            rationale=data["rationale"],
            evidence_snippets=data.get("evidence_snippets", []),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class EntailmentReport:
    """Full entailment verification report."""

    ticker: str
    total_claims: int
    supported_count: int
    weak_count: int
    unsupported_count: int
    contradicted_count: int
    results: list[EntailmentResult]
    overall_score: float = 0.0  # 0-1 score

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "total_claims": self.total_claims,
            "supported_count": self.supported_count,
            "weak_count": self.weak_count,
            "unsupported_count": self.unsupported_count,
            "contradicted_count": self.contradicted_count,
            "results": [r.to_dict() for r in self.results],
            "overall_score": self.overall_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntailmentReport":
        """Create from dict."""
        return cls(
            ticker=data["ticker"],
            total_claims=data["total_claims"],
            supported_count=data["supported_count"],
            weak_count=data["weak_count"],
            unsupported_count=data["unsupported_count"],
            contradicted_count=data["contradicted_count"],
            results=[EntailmentResult.from_dict(r) for r in data["results"]],
            overall_score=data.get("overall_score", 0.0),
        )


# =============================================================================
# Transcript/Filing Index Types
# =============================================================================


@dataclass
class TextExcerpt:
    """An excerpt from a transcript or filing."""

    excerpt_id: str
    source_evidence_id: str
    source_type: str  # "transcript" or "filing"
    text: str
    start_offset: int
    end_offset: int
    metadata: dict[str, Any] = field(default_factory=dict)  # date, speaker, section, etc.
    relevance_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "excerpt_id": self.excerpt_id,
            "source_evidence_id": self.source_evidence_id,
            "source_type": self.source_type,
            "text": self.text,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "metadata": self.metadata,
            "relevance_score": self.relevance_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextExcerpt":
        """Create from dict."""
        return cls(
            excerpt_id=data["excerpt_id"],
            source_evidence_id=data["source_evidence_id"],
            source_type=data["source_type"],
            text=data["text"],
            start_offset=data["start_offset"],
            end_offset=data["end_offset"],
            metadata=data.get("metadata", {}),
            relevance_score=data.get("relevance_score", 0.0),
        )


# =============================================================================
# Valuation Types
# =============================================================================


@dataclass
class ProjectionInputs:
    """Inputs for financial projections."""

    ticker: str
    base_year: int
    projection_years: int
    revenue_growth_rates: list[float]
    gross_margin: float
    operating_margin: float
    tax_rate: float
    capex_to_revenue: float
    nwc_to_revenue: float
    depreciation_to_capex: float
    terminal_growth: float
    assumptions_source: str = ""  # Where these came from

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "base_year": self.base_year,
            "projection_years": self.projection_years,
            "revenue_growth_rates": self.revenue_growth_rates,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "tax_rate": self.tax_rate,
            "capex_to_revenue": self.capex_to_revenue,
            "nwc_to_revenue": self.nwc_to_revenue,
            "depreciation_to_capex": self.depreciation_to_capex,
            "terminal_growth": self.terminal_growth,
            "assumptions_source": self.assumptions_source,
        }


@dataclass
class WACCInputs:
    """Inputs for WACC calculation."""

    risk_free_rate: float
    equity_risk_premium: float
    beta: float
    cost_of_debt: float
    tax_rate: float
    debt_to_capital: float
    size_premium: float = 0.0
    industry_adjustment: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "risk_free_rate": self.risk_free_rate,
            "equity_risk_premium": self.equity_risk_premium,
            "beta": self.beta,
            "cost_of_debt": self.cost_of_debt,
            "tax_rate": self.tax_rate,
            "debt_to_capital": self.debt_to_capital,
            "size_premium": self.size_premium,
            "industry_adjustment": self.industry_adjustment,
        }


@dataclass
class DCFResult:
    """Result of DCF valuation."""

    enterprise_value: float
    equity_value: float
    per_share_value: float
    wacc: float
    terminal_value: float
    pv_fcf: float
    pv_terminal: float
    shares_outstanding: float
    net_debt: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "enterprise_value": self.enterprise_value,
            "equity_value": self.equity_value,
            "per_share_value": self.per_share_value,
            "wacc": self.wacc,
            "terminal_value": self.terminal_value,
            "pv_fcf": self.pv_fcf,
            "pv_terminal": self.pv_terminal,
            "shares_outstanding": self.shares_outstanding,
            "net_debt": self.net_debt,
        }


@dataclass
class ReverseDCFResult:
    """Result of reverse DCF (what's priced in)."""

    current_price: float
    implied_growth_rate: float
    implied_terminal_growth: float
    implied_margin: float
    sensitivity_to_growth: float
    sensitivity_to_margin: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "current_price": self.current_price,
            "implied_growth_rate": self.implied_growth_rate,
            "implied_terminal_growth": self.implied_terminal_growth,
            "implied_margin": self.implied_margin,
            "sensitivity_to_growth": self.sensitivity_to_growth,
            "sensitivity_to_margin": self.sensitivity_to_margin,
        }


@dataclass
class ValuationSummary:
    """Summary of valuation analysis."""

    ticker: str
    as_of_date: str
    current_price: float
    dcf_value: float
    dcf_upside: float  # % upside/downside
    reverse_dcf: ReverseDCFResult | None
    sensitivity_range: tuple[float, float]  # low, high
    comps_median: float | None
    comps_range: tuple[float, float] | None
    sotp_value: float | None
    key_assumptions: list[str]
    key_sensitivities: list[str]
    valuation_view: str  # "undervalued", "fairly_valued", "overvalued"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "current_price": self.current_price,
            "dcf_value": self.dcf_value,
            "dcf_upside": self.dcf_upside,
            "reverse_dcf": self.reverse_dcf.to_dict() if self.reverse_dcf else None,
            "sensitivity_range": list(self.sensitivity_range),
            "comps_median": self.comps_median,
            "comps_range": list(self.comps_range) if self.comps_range else None,
            "sotp_value": self.sotp_value,
            "key_assumptions": self.key_assumptions,
            "key_sensitivities": self.key_sensitivities,
            "valuation_view": self.valuation_view,
        }
