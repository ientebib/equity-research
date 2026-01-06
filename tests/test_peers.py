"""Tests for peer selection and comparable company analysis."""

import pytest
from er.peers.selector import (
    PeerSelector,
    PeerGroup,
    PeerCompany,
    PeerMatchQuality,
    create_default_peer_database,
)
from er.peers.comps import (
    CompsAnalyzer,
    CompsMetrics,
    CompsStatistics,
    ComparableAnalysis,
    create_metrics_from_financials,
)


# ============================================================================
# PeerSelector Tests
# ============================================================================


class TestPeerSelector:
    """Tests for PeerSelector."""

    def test_select_peers_same_industry(self):
        """Test peer selection prioritizes same industry."""
        database = [
            {"ticker": "AAPL", "name": "Apple", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3e12, "revenue": 400e9},
            {"ticker": "MSFT", "name": "Microsoft", "sector": "Technology", "industry": "Software", "market_cap": 2.8e12, "revenue": 220e9},
            {"ticker": "SONY", "name": "Sony", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 100e9, "revenue": 80e9},
        ]
        selector = PeerSelector(peer_database=database)

        result = selector.select_peers(
            ticker="TEST",
            company_name="Test Electronics",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=150e9,
            revenue=100e9,
        )

        assert isinstance(result, PeerGroup)
        assert result.target_ticker == "TEST"
        # SONY should be first due to same industry + closer market cap
        assert any(p.ticker == "SONY" for p in result.peers)

    def test_select_peers_excludes_self(self):
        """Test that target company is excluded from peers."""
        database = [
            {"ticker": "AAPL", "name": "Apple", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3e12},
            {"ticker": "TEST", "name": "Test Co", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 100e9},
        ]
        selector = PeerSelector(peer_database=database)

        result = selector.select_peers(
            ticker="TEST",
            company_name="Test Co",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=100e9,
        )

        assert not any(p.ticker == "TEST" for p in result.peers)

    def test_select_peers_market_cap_proximity(self):
        """Test market cap proximity scoring."""
        database = [
            {"ticker": "BIG", "name": "Big Corp", "sector": "Tech", "industry": "Software", "market_cap": 500e9},
            {"ticker": "MED", "name": "Medium Corp", "sector": "Tech", "industry": "Software", "market_cap": 100e9},
            {"ticker": "SML", "name": "Small Corp", "sector": "Tech", "industry": "Software", "market_cap": 50e9},
        ]
        selector = PeerSelector(peer_database=database)

        # Target has 80B market cap - MED (100B) should be closest
        result = selector.select_peers(
            ticker="TARGET",
            company_name="Target Corp",
            sector="Tech",
            industry="Software",
            market_cap=80e9,
        )

        # MED should score highest due to market cap proximity
        assert result.peers[0].ticker == "MED"

    def test_select_peers_requires_same_sector(self):
        """Test that different sector companies are excluded."""
        database = [
            {"ticker": "BANK", "name": "Bank Corp", "sector": "Financials", "industry": "Banking", "market_cap": 100e9},
            {"ticker": "TECH", "name": "Tech Corp", "sector": "Technology", "industry": "Software", "market_cap": 100e9},
        ]
        selector = PeerSelector(peer_database=database)

        result = selector.select_peers(
            ticker="TARGET",
            company_name="Target Tech",
            sector="Technology",
            industry="Software",
            market_cap=100e9,
        )

        # BANK should not be included (different sector)
        assert not any(p.ticker == "BANK" for p in result.peers)
        assert any(p.ticker == "TECH" for p in result.peers)

    def test_select_peers_max_peers_limit(self):
        """Test max_peers parameter limits results."""
        database = [
            {"ticker": f"PEER{i}", "name": f"Peer {i}", "sector": "Tech", "industry": "Software", "market_cap": 100e9}
            for i in range(20)
        ]
        selector = PeerSelector(peer_database=database)

        result = selector.select_peers(
            ticker="TARGET",
            company_name="Target",
            sector="Tech",
            industry="Software",
            market_cap=100e9,
            max_peers=5,
        )

        assert len(result.peers) <= 5

    def test_select_peers_match_quality(self):
        """Test match quality assignment."""
        database = [
            # Strong match: same industry, similar market cap
            {"ticker": "STRONG", "name": "Strong Match", "sector": "Tech", "industry": "Software", "market_cap": 100e9, "revenue": 50e9},
            # Moderate match: same sector, different industry
            {"ticker": "MODERATE", "name": "Moderate Match", "sector": "Tech", "industry": "Hardware", "market_cap": 100e9},
        ]
        selector = PeerSelector(peer_database=database)

        result = selector.select_peers(
            ticker="TARGET",
            company_name="Target",
            sector="Tech",
            industry="Software",
            market_cap=100e9,
            revenue=50e9,
        )

        strong_peer = next((p for p in result.peers if p.ticker == "STRONG"), None)
        assert strong_peer is not None
        assert strong_peer.match_quality == PeerMatchQuality.STRONG

    def test_get_size_bucket(self):
        """Test market cap size bucket classification."""
        selector = PeerSelector()

        assert selector.get_size_bucket(250e9) == "mega_cap"
        assert selector.get_size_bucket(50e9) == "large_cap"
        assert selector.get_size_bucket(5e9) == "mid_cap"
        assert selector.get_size_bucket(1e9) == "small_cap"
        assert selector.get_size_bucket(100e6) == "micro_cap"

    def test_add_peer_to_database(self):
        """Test adding peer to database."""
        selector = PeerSelector()
        assert len(selector.peer_database) == 0

        selector.add_peer_to_database({"ticker": "NEW", "name": "New Corp"})
        assert len(selector.peer_database) == 1

    def test_load_peer_database(self):
        """Test loading peer database."""
        selector = PeerSelector()
        companies = [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}]

        selector.load_peer_database(companies)
        assert len(selector.peer_database) == 3

    def test_create_default_peer_database(self):
        """Test default peer database creation."""
        database = create_default_peer_database()

        assert isinstance(database, list)
        assert len(database) > 0
        assert all("ticker" in company for company in database)
        assert all("sector" in company for company in database)


class TestPeerGroup:
    """Tests for PeerGroup dataclass."""

    def test_peer_group_to_dict(self):
        """Test PeerGroup serialization."""
        peer = PeerCompany(
            ticker="AAPL",
            name="Apple",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=3e12,
            match_quality=PeerMatchQuality.STRONG,
            match_reasons=["Same industry", "Similar market cap"],
        )
        group = PeerGroup(
            target_ticker="TEST",
            target_name="Test Corp",
            peers=[peer],
            selection_criteria={"sector": "Technology"},
        )

        result = group.to_dict()

        assert result["target_ticker"] == "TEST"
        assert result["peer_count"] == 1
        assert len(result["peers"]) == 1

    def test_get_strong_peers(self):
        """Test filtering strong peers."""
        peers = [
            PeerCompany(ticker="STRONG", name="Strong", sector="Tech", industry="Soft", market_cap=100e9, match_quality=PeerMatchQuality.STRONG),
            PeerCompany(ticker="WEAK", name="Weak", sector="Tech", industry="Hard", market_cap=100e9, match_quality=PeerMatchQuality.WEAK),
        ]
        group = PeerGroup(target_ticker="TEST", target_name="Test", peers=peers)

        strong = group.get_strong_peers()
        assert len(strong) == 1
        assert strong[0].ticker == "STRONG"

    def test_get_peer_tickers(self):
        """Test getting peer ticker list."""
        peers = [
            PeerCompany(ticker="A", name="A Corp", sector="Tech", industry="Soft", market_cap=100e9, match_quality=PeerMatchQuality.MODERATE),
            PeerCompany(ticker="B", name="B Corp", sector="Tech", industry="Soft", market_cap=100e9, match_quality=PeerMatchQuality.MODERATE),
        ]
        group = PeerGroup(target_ticker="TEST", target_name="Test", peers=peers)

        tickers = group.get_peer_tickers()
        assert tickers == ["A", "B"]


# ============================================================================
# CompsAnalyzer Tests
# ============================================================================


class TestCompsMetrics:
    """Tests for CompsMetrics dataclass."""

    def test_comps_metrics_to_dict(self):
        """Test CompsMetrics serialization."""
        metrics = CompsMetrics(
            ticker="AAPL",
            pe_ratio=25.0,
            ev_ebitda=15.0,
            revenue_growth=0.10,
        )

        result = metrics.to_dict()

        assert result["ticker"] == "AAPL"
        assert result["pe_ratio"] == 25.0
        assert result["ev_ebitda"] == 15.0
        assert result["revenue_growth"] == 0.10

    def test_create_metrics_from_financials(self):
        """Test creating metrics from financial data."""
        metrics = create_metrics_from_financials(
            ticker="TEST",
            price=100.0,
            shares=1e9,  # 1B shares
            enterprise_value=110e9,  # $110B EV
            earnings=5e9,  # $5B earnings
            revenue=50e9,  # $50B revenue
            ebitda=10e9,  # $10B EBITDA
            book_value=40e9,  # $40B book value
            revenue_growth=0.15,
            operating_margin=0.20,
        )

        # Market cap = 100 * 1B = $100B
        assert metrics.ticker == "TEST"
        assert metrics.pe_ratio == 20.0  # 100B / 5B
        assert metrics.ev_ebitda == 11.0  # 110B / 10B
        assert metrics.ev_revenue == 2.2  # 110B / 50B
        assert metrics.price_to_sales == 2.0  # 100B / 50B
        assert metrics.price_to_book == 2.5  # 100B / 40B
        assert metrics.revenue_growth == 0.15
        assert metrics.operating_margin == 0.20

    def test_create_metrics_handles_zero_denominators(self):
        """Test that zero denominators return None."""
        metrics = create_metrics_from_financials(
            ticker="TEST",
            price=100.0,
            shares=1e9,
            enterprise_value=100e9,
            earnings=0,  # Zero earnings
            revenue=0,  # Zero revenue
            ebitda=0,  # Zero EBITDA
            book_value=0,  # Zero book value
        )

        assert metrics.pe_ratio is None
        assert metrics.ev_ebitda is None
        assert metrics.ev_revenue is None
        assert metrics.price_to_sales is None
        assert metrics.price_to_book is None


class TestCompsAnalyzer:
    """Tests for CompsAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return CompsAnalyzer()

    @pytest.fixture
    def sample_metrics(self):
        """Create sample peer metrics."""
        return [
            CompsMetrics(ticker="PEER1", pe_ratio=20.0, ev_ebitda=12.0, operating_margin=0.25),
            CompsMetrics(ticker="PEER2", pe_ratio=25.0, ev_ebitda=14.0, operating_margin=0.22),
            CompsMetrics(ticker="PEER3", pe_ratio=22.0, ev_ebitda=13.0, operating_margin=0.28),
            CompsMetrics(ticker="PEER4", pe_ratio=18.0, ev_ebitda=11.0, operating_margin=0.20),
        ]

    def test_analyze_calculates_statistics(self, analyzer, sample_metrics):
        """Test that analyze calculates peer statistics."""
        target = CompsMetrics(ticker="TARGET", pe_ratio=23.0, ev_ebitda=13.5)

        result = analyzer.analyze(target, sample_metrics)

        assert isinstance(result, ComparableAnalysis)
        assert result.target_ticker == "TARGET"
        assert "pe_ratio" in result.statistics
        assert "ev_ebitda" in result.statistics

    def test_statistics_mean_and_median(self, analyzer, sample_metrics):
        """Test mean and median calculations."""
        target = CompsMetrics(ticker="TARGET", pe_ratio=23.0)

        result = analyzer.analyze(target, sample_metrics)
        pe_stats = result.statistics["pe_ratio"]

        # P/E values: 20, 25, 22, 18
        # Mean: (20 + 25 + 22 + 18) / 4 = 21.25
        # Median: (20, 18, 22, 25) sorted = 18, 20, 22, 25 -> (20+22)/2 = 21
        assert pe_stats.mean == 21.25
        assert pe_stats.median == 21.0
        assert pe_stats.min_val == 18.0
        assert pe_stats.max_val == 25.0

    def test_implied_premium_calculation(self, analyzer, sample_metrics):
        """Test implied premium/discount calculation."""
        # Target P/E of 25.5 vs peer median of 21 = 21.4% premium
        target = CompsMetrics(ticker="TARGET", pe_ratio=25.5, ev_ebitda=15.0)

        result = analyzer.analyze(target, sample_metrics)

        # Check premium calculation exists
        assert "pe_ratio_implied_premium" in result.implied_values

    def test_analyze_handles_missing_metrics(self, analyzer):
        """Test analysis with missing metric values."""
        peers = [
            CompsMetrics(ticker="PEER1", pe_ratio=20.0),  # Only P/E
            CompsMetrics(ticker="PEER2", pe_ratio=25.0),
        ]
        target = CompsMetrics(ticker="TARGET", pe_ratio=22.0)

        result = analyzer.analyze(target, peers)

        # Should still calculate P/E stats
        assert "pe_ratio" in result.statistics
        # EV/EBITDA should not have stats (no values)
        assert "ev_ebitda" not in result.statistics

    def test_peer_relative_score(self, analyzer, sample_metrics):
        """Test peer relative score calculation."""
        target = CompsMetrics(ticker="TARGET", pe_ratio=19.0, ev_ebitda=11.5)

        scores = analyzer.calculate_peer_relative_score(target, sample_metrics)

        # Target P/E of 19 is lower than most peers (18, 20, 22, 25)
        # Only 18 is below 19, so target is cheaper than 3 of 4 peers = 75th percentile
        assert "pe_ratio" in scores
        assert scores["pe_ratio"] == 75.0  # 3/4 peers have higher P/E

    def test_comparable_analysis_to_dict(self, analyzer, sample_metrics):
        """Test ComparableAnalysis serialization."""
        target = CompsMetrics(ticker="TARGET", pe_ratio=22.0)

        result = analyzer.analyze(target, sample_metrics)
        result_dict = result.to_dict()

        assert result_dict["target_ticker"] == "TARGET"
        assert "target_metrics" in result_dict
        assert "peer_metrics" in result_dict
        assert "statistics" in result_dict

    def test_comps_statistics_to_dict(self):
        """Test CompsStatistics serialization."""
        stats = CompsStatistics(
            metric_name="pe_ratio",
            values=[18.0, 20.0, 22.0, 25.0],
            mean=21.25,
            median=21.0,
            min_val=18.0,
            max_val=25.0,
            std_dev=2.5,
        )

        result = stats.to_dict()

        assert result["metric_name"] == "pe_ratio"
        assert result["mean"] == 21.25
        assert result["median"] == 21.0

    def test_empty_peer_list(self, analyzer):
        """Test analysis with empty peer list."""
        target = CompsMetrics(ticker="TARGET", pe_ratio=22.0)

        result = analyzer.analyze(target, [])

        assert result.target_ticker == "TARGET"
        assert len(result.peer_metrics) == 0
        assert len(result.statistics) == 0
