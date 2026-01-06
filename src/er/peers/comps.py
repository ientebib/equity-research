"""
Comparable Company Analysis (Comps).

Calculates valuation multiples and relative metrics for peer comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import statistics

from er.peers.selector import PeerGroup, PeerCompany


@dataclass
class CompsMetrics:
    """Valuation metrics for a company."""

    ticker: str
    pe_ratio: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None
    price_to_sales: float | None = None
    price_to_book: float | None = None

    # Growth metrics
    revenue_growth: float | None = None
    earnings_growth: float | None = None

    # Profitability
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    roe: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "ticker": self.ticker,
            "pe_ratio": self.pe_ratio,
            "ev_ebitda": self.ev_ebitda,
            "ev_revenue": self.ev_revenue,
            "price_to_sales": self.price_to_sales,
            "price_to_book": self.price_to_book,
            "revenue_growth": self.revenue_growth,
            "earnings_growth": self.earnings_growth,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "net_margin": self.net_margin,
            "roe": self.roe,
        }


@dataclass
class CompsStatistics:
    """Statistics for a metric across peers."""

    metric_name: str
    values: list[float]
    mean: float
    median: float
    min_val: float
    max_val: float
    std_dev: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "metric_name": self.metric_name,
            "values": self.values,
            "mean": round(self.mean, 2),
            "median": round(self.median, 2),
            "min": round(self.min_val, 2),
            "max": round(self.max_val, 2),
            "std_dev": round(self.std_dev, 2),
        }


@dataclass
class ComparableAnalysis:
    """Complete comparable company analysis."""

    target_ticker: str
    target_metrics: CompsMetrics
    peer_metrics: list[CompsMetrics]
    statistics: dict[str, CompsStatistics] = field(default_factory=dict)
    implied_values: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "target_ticker": self.target_ticker,
            "target_metrics": self.target_metrics.to_dict(),
            "peer_metrics": [m.to_dict() for m in self.peer_metrics],
            "statistics": {k: v.to_dict() for k, v in self.statistics.items()},
            "implied_values": self.implied_values,
        }


class CompsAnalyzer:
    """Performs comparable company analysis.

    Calculates:
    1. Peer group statistics for multiples
    2. Implied values for target based on peer multiples
    3. Premium/discount analysis
    """

    VALUATION_METRICS = [
        "pe_ratio",
        "ev_ebitda",
        "ev_revenue",
        "price_to_sales",
        "price_to_book",
    ]

    def __init__(self) -> None:
        """Initialize the analyzer."""
        pass

    def analyze(
        self,
        target_metrics: CompsMetrics,
        peer_metrics: list[CompsMetrics],
    ) -> ComparableAnalysis:
        """Perform comparable analysis.

        Args:
            target_metrics: Metrics for target company.
            peer_metrics: Metrics for peer companies.

        Returns:
            ComparableAnalysis with statistics and implied values.
        """
        # Calculate statistics for each metric
        stats = {}
        for metric in self.VALUATION_METRICS:
            values = self._get_metric_values(peer_metrics, metric)
            if values:
                stats[metric] = self._calculate_statistics(metric, values)

        # Calculate implied values
        implied = self._calculate_implied_values(target_metrics, stats)

        return ComparableAnalysis(
            target_ticker=target_metrics.ticker,
            target_metrics=target_metrics,
            peer_metrics=peer_metrics,
            statistics=stats,
            implied_values=implied,
        )

    def _get_metric_values(
        self,
        metrics: list[CompsMetrics],
        metric_name: str,
    ) -> list[float]:
        """Get non-null values for a metric."""
        values = []
        for m in metrics:
            val = getattr(m, metric_name, None)
            if val is not None and val > 0:
                values.append(val)
        return values

    def _calculate_statistics(
        self,
        metric_name: str,
        values: list[float],
    ) -> CompsStatistics:
        """Calculate statistics for a metric."""
        if not values:
            return CompsStatistics(
                metric_name=metric_name,
                values=[],
                mean=0,
                median=0,
                min_val=0,
                max_val=0,
                std_dev=0,
            )

        return CompsStatistics(
            metric_name=metric_name,
            values=values,
            mean=statistics.mean(values),
            median=statistics.median(values),
            min_val=min(values),
            max_val=max(values),
            std_dev=statistics.stdev(values) if len(values) > 1 else 0,
        )

    def _calculate_implied_values(
        self,
        target: CompsMetrics,
        stats: dict[str, CompsStatistics],
    ) -> dict[str, float]:
        """Calculate implied values for target based on peer multiples.

        Note: This requires additional financial data like EPS, revenue per share, etc.
        Returns placeholder implied values based on available data.
        """
        implied = {}

        # These would normally calculate implied share price
        # based on peer multiples applied to target fundamentals
        # e.g., Implied Price = Peer Median P/E * Target EPS

        for metric, stat in stats.items():
            if stat.median > 0:
                implied[f"{metric}_implied_premium"] = self._calculate_premium(
                    target_multiple=getattr(target, metric, None),
                    peer_median=stat.median,
                )

        return implied

    def _calculate_premium(
        self,
        target_multiple: float | None,
        peer_median: float,
    ) -> float:
        """Calculate premium/discount vs peer median."""
        if target_multiple is None or target_multiple <= 0:
            return 0.0
        if peer_median <= 0:
            return 0.0

        return (target_multiple / peer_median - 1) * 100  # As percentage

    def calculate_peer_relative_score(
        self,
        target: CompsMetrics,
        peers: list[CompsMetrics],
    ) -> dict[str, float]:
        """Calculate relative scores vs peers.

        Higher score = more attractive valuation.
        """
        scores = {}

        # For each valuation metric, calculate percentile rank
        for metric in self.VALUATION_METRICS:
            target_val = getattr(target, metric, None)
            if target_val is None:
                continue

            peer_values = self._get_metric_values(peers, metric)
            if not peer_values:
                continue

            # For multiples, lower is more attractive
            below_count = sum(1 for v in peer_values if v > target_val)
            percentile = (below_count / len(peer_values)) * 100

            scores[metric] = percentile

        return scores


def create_metrics_from_financials(
    ticker: str,
    price: float,
    shares: float,
    enterprise_value: float,
    earnings: float,
    revenue: float,
    ebitda: float,
    book_value: float,
    revenue_growth: float = 0.0,
    operating_margin: float = 0.0,
) -> CompsMetrics:
    """Create CompsMetrics from financial data.

    Args:
        ticker: Stock ticker.
        price: Current stock price.
        shares: Shares outstanding.
        enterprise_value: Enterprise value.
        earnings: Net income.
        revenue: Total revenue.
        ebitda: EBITDA.
        book_value: Book value of equity.
        revenue_growth: Revenue growth rate.
        operating_margin: Operating margin.

    Returns:
        CompsMetrics with calculated ratios.
    """
    market_cap = price * shares

    return CompsMetrics(
        ticker=ticker,
        pe_ratio=market_cap / earnings if earnings > 0 else None,
        ev_ebitda=enterprise_value / ebitda if ebitda > 0 else None,
        ev_revenue=enterprise_value / revenue if revenue > 0 else None,
        price_to_sales=market_cap / revenue if revenue > 0 else None,
        price_to_book=market_cap / book_value if book_value > 0 else None,
        revenue_growth=revenue_growth,
        operating_margin=operating_margin,
    )
