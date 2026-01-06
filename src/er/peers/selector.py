"""
Peer Selection for comparable company analysis.

Provides robust peer selection based on multiple criteria:
1. Industry/sector classification
2. Market cap range
3. Business model similarity
4. Geographic exposure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PeerMatchQuality(str, Enum):
    """Quality of peer match."""

    STRONG = "strong"  # Direct competitor, similar metrics
    MODERATE = "moderate"  # Same industry, different scale
    WEAK = "weak"  # Related but different business model


@dataclass
class PeerCompany:
    """A peer company with match metadata."""

    ticker: str
    name: str
    sector: str
    industry: str
    market_cap: float
    match_quality: PeerMatchQuality
    match_reasons: list[str] = field(default_factory=list)

    # Key metrics for comparison
    revenue: float = 0.0
    operating_margin: float = 0.0
    revenue_growth: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "industry": self.industry,
            "market_cap": self.market_cap,
            "match_quality": self.match_quality.value,
            "match_reasons": self.match_reasons,
            "revenue": self.revenue,
            "operating_margin": self.operating_margin,
            "revenue_growth": self.revenue_growth,
        }


@dataclass
class PeerGroup:
    """A group of peer companies for analysis."""

    target_ticker: str
    target_name: str
    peers: list[PeerCompany]
    selection_criteria: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "target_ticker": self.target_ticker,
            "target_name": self.target_name,
            "peers": [p.to_dict() for p in self.peers],
            "selection_criteria": self.selection_criteria,
            "peer_count": len(self.peers),
        }

    def get_strong_peers(self) -> list[PeerCompany]:
        """Get only strong-match peers."""
        return [p for p in self.peers if p.match_quality == PeerMatchQuality.STRONG]

    def get_peer_tickers(self) -> list[str]:
        """Get list of peer tickers."""
        return [p.ticker for p in self.peers]


class PeerSelector:
    """Selects peer companies based on multiple criteria.

    Selection Criteria:
    1. Same sector and industry
    2. Market cap within 0.2x - 5x range
    3. Similar business model
    4. Similar growth profile
    """

    # Market cap size buckets
    SIZE_BUCKETS = {
        "mega_cap": 200e9,   # > $200B
        "large_cap": 10e9,   # $10B - $200B
        "mid_cap": 2e9,      # $2B - $10B
        "small_cap": 300e6,  # $300M - $2B
        "micro_cap": 0,      # < $300M
    }

    def __init__(
        self,
        peer_database: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the peer selector.

        Args:
            peer_database: Optional pre-loaded peer database.
        """
        self.peer_database = peer_database or []

    def select_peers(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        industry: str,
        market_cap: float,
        revenue: float = 0.0,
        max_peers: int = 10,
    ) -> PeerGroup:
        """Select peer companies for analysis.

        Args:
            ticker: Target company ticker.
            company_name: Target company name.
            sector: Target company sector.
            industry: Target company industry.
            market_cap: Target market cap.
            revenue: Target revenue (optional).
            max_peers: Maximum peers to return.

        Returns:
            PeerGroup with selected peers.
        """
        candidates = []

        for company in self.peer_database:
            if company.get("ticker") == ticker:
                continue  # Skip self

            # Score the candidate
            score, quality, reasons = self._score_candidate(
                candidate=company,
                target_sector=sector,
                target_industry=industry,
                target_market_cap=market_cap,
                target_revenue=revenue,
            )

            if score > 0:
                peer = PeerCompany(
                    ticker=company.get("ticker", ""),
                    name=company.get("name", ""),
                    sector=company.get("sector", ""),
                    industry=company.get("industry", ""),
                    market_cap=company.get("market_cap", 0),
                    match_quality=quality,
                    match_reasons=reasons,
                    revenue=company.get("revenue", 0),
                    operating_margin=company.get("operating_margin", 0),
                    revenue_growth=company.get("revenue_growth", 0),
                )
                candidates.append((score, peer))

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Take top peers
        selected_peers = [peer for _, peer in candidates[:max_peers]]

        return PeerGroup(
            target_ticker=ticker,
            target_name=company_name,
            peers=selected_peers,
            selection_criteria={
                "sector": sector,
                "industry": industry,
                "market_cap": market_cap,
                "revenue": revenue,
                "max_peers": max_peers,
            },
        )

    def _score_candidate(
        self,
        candidate: dict[str, Any],
        target_sector: str,
        target_industry: str,
        target_market_cap: float,
        target_revenue: float,
    ) -> tuple[float, PeerMatchQuality, list[str]]:
        """Score a candidate peer company.

        Returns:
            Tuple of (score, quality, reasons).
        """
        score = 0.0
        reasons = []

        # Industry match (highest weight)
        if candidate.get("industry") == target_industry:
            score += 40
            reasons.append("Same industry")
        elif candidate.get("sector") == target_sector:
            score += 20
            reasons.append("Same sector")
        else:
            return 0, PeerMatchQuality.WEAK, []  # Must be at least same sector

        # Market cap proximity
        cand_market_cap = candidate.get("market_cap", 0)
        if cand_market_cap > 0 and target_market_cap > 0:
            ratio = cand_market_cap / target_market_cap
            if 0.5 <= ratio <= 2.0:
                score += 30
                reasons.append("Similar market cap")
            elif 0.2 <= ratio <= 5.0:
                score += 15
                reasons.append("Comparable market cap")

        # Revenue proximity (if available)
        cand_revenue = candidate.get("revenue", 0)
        if cand_revenue > 0 and target_revenue > 0:
            ratio = cand_revenue / target_revenue
            if 0.5 <= ratio <= 2.0:
                score += 20
                reasons.append("Similar revenue scale")
            elif 0.2 <= ratio <= 5.0:
                score += 10
                reasons.append("Comparable revenue")

        # Determine quality
        if score >= 70:
            quality = PeerMatchQuality.STRONG
        elif score >= 40:
            quality = PeerMatchQuality.MODERATE
        else:
            quality = PeerMatchQuality.WEAK

        return score, quality, reasons

    def get_size_bucket(self, market_cap: float) -> str:
        """Get market cap size bucket."""
        for bucket, threshold in self.SIZE_BUCKETS.items():
            if market_cap >= threshold:
                return bucket
        return "micro_cap"

    def add_peer_to_database(self, company: dict[str, Any]) -> None:
        """Add a company to the peer database."""
        self.peer_database.append(company)

    def load_peer_database(self, companies: list[dict[str, Any]]) -> None:
        """Load a peer database."""
        self.peer_database = companies


def create_default_peer_database() -> list[dict[str, Any]]:
    """Create a default peer database with major companies."""
    return [
        # Tech - Consumer Electronics
        {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3e12, "revenue": 400e9},
        {"ticker": "MSFT", "name": "Microsoft Corp", "sector": "Technology", "industry": "Software", "market_cap": 2.8e12, "revenue": 220e9},
        {"ticker": "GOOGL", "name": "Alphabet Inc.", "sector": "Technology", "industry": "Internet Services", "market_cap": 1.8e12, "revenue": 300e9},
        {"ticker": "AMZN", "name": "Amazon.com Inc.", "sector": "Technology", "industry": "E-Commerce", "market_cap": 1.6e12, "revenue": 550e9},
        {"ticker": "META", "name": "Meta Platforms", "sector": "Technology", "industry": "Internet Services", "market_cap": 900e9, "revenue": 120e9},
        {"ticker": "NVDA", "name": "NVIDIA Corp", "sector": "Technology", "industry": "Semiconductors", "market_cap": 1.2e12, "revenue": 60e9},
        # Add more as needed
    ]
