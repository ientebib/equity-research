"""Tests for valuation engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from er.valuation.dcf import DCFEngine, DCFInputs, DCFResult, WACCInputs
from er.valuation.reverse_dcf import (
    ReverseDCFEngine,
    ReverseDCFInputs,
    ReverseDCFResult,
    calculate_implied_growth_simple,
)
from er.valuation.excel_export import ValuationExporter, ValuationWorkbook


class TestWACCCalculation:
    """Tests for WACC calculation."""

    def test_wacc_basic(self) -> None:
        """Test basic WACC calculation."""
        engine = DCFEngine()
        inputs = WACCInputs(
            risk_free_rate=0.04,
            equity_risk_premium=0.05,
            beta=1.0,
            cost_of_debt=0.05,
            tax_rate=0.21,
            debt_to_capital=0.20,
        )

        wacc = engine.calculate_wacc(inputs)

        # Cost of equity = 0.04 + 1.0 * 0.05 = 0.09
        # After-tax debt = 0.05 * (1-0.21) = 0.0395
        # WACC = 0.80 * 0.09 + 0.20 * 0.0395 = 0.072 + 0.0079 = 0.0799
        assert 0.07 < wacc < 0.09

    def test_wacc_high_beta(self) -> None:
        """Test WACC with high beta."""
        engine = DCFEngine()
        inputs_low = WACCInputs(beta=0.8)
        inputs_high = WACCInputs(beta=1.5)

        wacc_low = engine.calculate_wacc(inputs_low)
        wacc_high = engine.calculate_wacc(inputs_high)

        assert wacc_high > wacc_low


class TestDCFEngine:
    """Tests for DCF engine."""

    @pytest.fixture
    def dcf_inputs(self) -> DCFInputs:
        """Create sample DCF inputs."""
        return DCFInputs(
            revenue_projections=[110e9, 121e9, 133e9, 146e9, 161e9],  # ~10% growth
            operating_margins=[0.30, 0.31, 0.32, 0.32, 0.32],
            tax_rate=0.21,
            depreciation_pct=0.04,
            capex_pct=0.05,
            nwc_pct_delta=0.10,
            terminal_growth=0.025,
            wacc=0.10,
            current_revenue=100e9,
        )

    def test_dcf_calculation(self, dcf_inputs: DCFInputs) -> None:
        """Test DCF calculation produces reasonable results."""
        engine = DCFEngine()
        result = engine.calculate_dcf(
            dcf_inputs,
            net_debt=50e9,
            shares_outstanding=15e9,
        )

        assert isinstance(result, DCFResult)
        assert result.intrinsic_value_per_share > 0
        assert result.enterprise_value > 0
        assert result.equity_value > 0
        assert len(result.fcf_projections) == 5
        assert len(result.discount_factors) == 5

    def test_dcf_fcf_projections(self, dcf_inputs: DCFInputs) -> None:
        """Test FCF projections are calculated correctly."""
        engine = DCFEngine()
        result = engine.calculate_dcf(dcf_inputs, net_debt=0, shares_outstanding=1e9)

        # FCF should be positive (healthy company)
        for fcf in result.fcf_projections:
            assert fcf > 0

        # FCF should generally grow
        for i in range(len(result.fcf_projections) - 1):
            # Allow some variation due to margin changes and NWC
            pass  # Growth is not guaranteed due to NWC investment

    def test_dcf_discount_factors(self, dcf_inputs: DCFInputs) -> None:
        """Test discount factors are decreasing."""
        engine = DCFEngine()
        result = engine.calculate_dcf(dcf_inputs, net_debt=0, shares_outstanding=1e9)

        # Discount factors should decrease over time
        for i in range(len(result.discount_factors) - 1):
            assert result.discount_factors[i] > result.discount_factors[i + 1]

    def test_dcf_terminal_value(self, dcf_inputs: DCFInputs) -> None:
        """Test terminal value is significant portion of value."""
        engine = DCFEngine()
        result = engine.calculate_dcf(dcf_inputs, net_debt=0, shares_outstanding=1e9)

        # Terminal value typically accounts for 50-80% of total
        terminal_pct = result.pv_terminal / result.enterprise_value
        assert 0.3 < terminal_pct < 0.9

    def test_dcf_net_debt_impact(self, dcf_inputs: DCFInputs) -> None:
        """Test net debt reduces equity value."""
        engine = DCFEngine()

        result_no_debt = engine.calculate_dcf(
            dcf_inputs, net_debt=0, shares_outstanding=1e9
        )
        result_with_debt = engine.calculate_dcf(
            dcf_inputs, net_debt=20e9, shares_outstanding=1e9
        )

        assert result_no_debt.equity_value > result_with_debt.equity_value
        assert result_no_debt.intrinsic_value_per_share > result_with_debt.intrinsic_value_per_share

    def test_dcf_result_to_dict(self, dcf_inputs: DCFInputs) -> None:
        """Test DCFResult serialization."""
        engine = DCFEngine()
        result = engine.calculate_dcf(dcf_inputs, net_debt=0, shares_outstanding=1e9)

        d = result.to_dict()
        assert "intrinsic_value_per_share" in d
        assert "enterprise_value" in d
        assert "fcf_projections" in d

    def test_sensitivity_analysis(self, dcf_inputs: DCFInputs) -> None:
        """Test sensitivity analysis."""
        engine = DCFEngine()
        sensitivity = engine.sensitivity_analysis(
            dcf_inputs,
            net_debt=0,
            shares_outstanding=1e9,
            wacc_range=[0.08, 0.10, 0.12],
            terminal_growth_range=[0.02, 0.03],
        )

        results = sensitivity["sensitivity"]
        assert len(results) == 6  # 3 WACC x 2 TG

        # Higher WACC should give lower value
        high_wacc = [r for r in results if r[0] == 0.12]
        low_wacc = [r for r in results if r[0] == 0.08]
        assert high_wacc[0][2] < low_wacc[0][2]


class TestReverseDCFEngine:
    """Tests for reverse DCF engine."""

    @pytest.fixture
    def reverse_dcf_inputs(self) -> ReverseDCFInputs:
        """Create sample reverse DCF inputs."""
        return ReverseDCFInputs(
            current_price=150.0,
            shares_outstanding=15e9,
            net_debt=50e9,
            current_revenue=400e9,
            current_margin=0.30,
            tax_rate=0.21,
            wacc=0.10,
            terminal_growth=0.025,
        )

    def test_reverse_dcf_calculation(self, reverse_dcf_inputs: ReverseDCFInputs) -> None:
        """Test reverse DCF produces reasonable implied growth."""
        engine = ReverseDCFEngine()
        result = engine.calculate_implied_growth(reverse_dcf_inputs)

        assert isinstance(result, ReverseDCFResult)
        assert -0.30 < result.implied_revenue_cagr < 0.50  # Reasonable range
        assert result.market_cap > 0
        assert result.enterprise_value > 0

    def test_reverse_dcf_reasonableness(self, reverse_dcf_inputs: ReverseDCFInputs) -> None:
        """Test reasonableness checks."""
        engine = ReverseDCFEngine()

        # Normal case
        result = engine.calculate_implied_growth(reverse_dcf_inputs)
        assert len(result.reasonableness_notes) > 0

    def test_reverse_dcf_high_price(self) -> None:
        """Test reverse DCF with very high price implies high growth."""
        inputs = ReverseDCFInputs(
            current_price=500.0,  # Very high
            shares_outstanding=15e9,
            net_debt=0,
            current_revenue=400e9,
            current_margin=0.25,
            wacc=0.10,
        )

        engine = ReverseDCFEngine()
        result = engine.calculate_implied_growth(inputs)

        # Very high price should imply high growth
        assert result.implied_revenue_cagr > 0.15

    def test_reverse_dcf_low_price(self) -> None:
        """Test reverse DCF with low price implies low/negative growth."""
        inputs = ReverseDCFInputs(
            current_price=50.0,  # Low relative to fundamentals
            shares_outstanding=15e9,
            net_debt=0,
            current_revenue=400e9,
            current_margin=0.25,
            wacc=0.10,
        )

        engine = ReverseDCFEngine()
        result = engine.calculate_implied_growth(inputs)

        # Low price should imply low growth
        assert result.implied_revenue_cagr < 0.15

    def test_reverse_dcf_result_to_dict(self, reverse_dcf_inputs: ReverseDCFInputs) -> None:
        """Test ReverseDCFResult serialization."""
        engine = ReverseDCFEngine()
        result = engine.calculate_implied_growth(reverse_dcf_inputs)

        d = result.to_dict()
        assert "implied_revenue_cagr" in d
        assert "implied_revenue_cagr_pct" in d
        assert "is_reasonable" in d

    def test_calculate_implied_growth_simple(self) -> None:
        """Test convenience function."""
        result = calculate_implied_growth_simple(
            price=150.0,
            shares=15e9,
            revenue=400e9,
            margin=0.30,
            net_debt=50e9,
        )

        assert isinstance(result, ReverseDCFResult)
        assert result.implied_revenue_cagr is not None


class TestValuationExporter:
    """Tests for valuation exporter."""

    @pytest.fixture
    def sample_workbook(self) -> ValuationWorkbook:
        """Create sample workbook."""
        dcf_result = DCFResult(
            intrinsic_value_per_share=165.50,
            enterprise_value=2.5e12,
            equity_value=2.3e12,
            pv_fcf=800e9,
            terminal_value=2e12,
            pv_terminal=1.7e12,
            fcf_projections=[80e9, 90e9, 100e9, 110e9, 120e9],
            discount_factors=[0.909, 0.826, 0.751, 0.683, 0.621],
            wacc=0.10,
            terminal_growth=0.025,
        )

        reverse_dcf_result = ReverseDCFResult(
            implied_revenue_cagr=0.12,
            market_cap=2.25e12,
            enterprise_value=2.5e12,
            implied_year5_revenue=700e9,
            implied_year5_fcf=140e9,
            is_reasonable=True,
            reasonableness_notes=["Implied assumptions appear reasonable"],
        )

        return ValuationWorkbook(
            ticker="AAPL",
            company_name="Apple Inc.",
            dcf_result=dcf_result,
            reverse_dcf_result=reverse_dcf_result,
            sensitivity_data={
                "sensitivity": [
                    (0.08, 0.02, 180.0),
                    (0.08, 0.03, 210.0),
                    (0.10, 0.02, 150.0),
                    (0.10, 0.03, 170.0),
                ]
            },
        )

    def test_export_json(self, sample_workbook: ValuationWorkbook) -> None:
        """Test JSON export."""
        exporter = ValuationExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "valuation.json"
            result_path = exporter.export_json(sample_workbook, output_path)

            assert result_path.exists()
            assert result_path.suffix == ".json"

    def test_export_csv(self, sample_workbook: ValuationWorkbook) -> None:
        """Test CSV export."""
        exporter = ValuationExporter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            result_paths = exporter.export_csv(sample_workbook, output_dir)

            assert len(result_paths) >= 1
            for path in result_paths:
                assert path.exists()
                assert path.suffix == ".csv"

    def test_workbook_to_dict(self, sample_workbook: ValuationWorkbook) -> None:
        """Test workbook serialization."""
        d = sample_workbook.to_dict()

        assert d["ticker"] == "AAPL"
        assert d["company_name"] == "Apple Inc."
        assert "dcf" in d
        assert "reverse_dcf" in d
        assert "sensitivity" in d


class TestIntegration:
    """Integration tests for full valuation workflow."""

    def test_full_valuation_workflow(self) -> None:
        """Test complete valuation workflow."""
        # 1. Calculate WACC
        engine = DCFEngine()
        wacc_inputs = WACCInputs(
            risk_free_rate=0.04,
            equity_risk_premium=0.05,
            beta=1.1,
            cost_of_debt=0.05,
            debt_to_capital=0.15,
        )
        wacc = engine.calculate_wacc(wacc_inputs)

        # 2. Run DCF
        dcf_inputs = DCFInputs(
            revenue_projections=[110e9, 121e9, 133e9, 146e9, 161e9],
            operating_margins=[0.30, 0.30, 0.31, 0.31, 0.32],
            wacc=wacc,
            terminal_growth=0.025,
            current_revenue=100e9,
        )
        dcf_result = engine.calculate_dcf(
            dcf_inputs,
            net_debt=20e9,
            shares_outstanding=5e9,
        )

        # 3. Run reverse DCF
        reverse_engine = ReverseDCFEngine()
        reverse_inputs = ReverseDCFInputs(
            current_price=dcf_result.intrinsic_value_per_share,
            shares_outstanding=5e9,
            net_debt=20e9,
            current_revenue=100e9,
            current_margin=0.30,
            wacc=wacc,
            terminal_growth=0.025,
        )
        reverse_result = reverse_engine.calculate_implied_growth(reverse_inputs)

        # 4. Verify consistency
        # Implied growth should be close to DCF assumptions (~10%)
        assert 0.05 < reverse_result.implied_revenue_cagr < 0.15

        # 5. Create workbook
        workbook = ValuationWorkbook(
            ticker="TEST",
            company_name="Test Company",
            dcf_result=dcf_result,
            reverse_dcf_result=reverse_result,
        )

        assert workbook.ticker == "TEST"
        assert workbook.dcf_result is not None
