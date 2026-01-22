"""
Utility functions for GOOGL equity research data analysis
"""

import json
from typing import Dict, Any, List, Tuple
from datetime import datetime
from pathlib import Path

from fmp_research_fetcher import FMPResearchFetcher


class GOOGLResearchAnalyzer:
    """Analyze and process GOOGL research data"""

    def __init__(self, research_data: Dict[str, Any]):
        """Initialize with fetched research data"""
        self.data = research_data
        self.profile = research_data.get('company_profile', {})
        self.income = research_data.get('income_statement', [])
        self.balance = research_data.get('balance_sheet', {})
        self.ratios = research_data.get('financial_ratios', {})
        self.metrics = research_data.get('key_metrics', {})
        self.estimates = research_data.get('analyst_estimates', [])
        self.segments = research_data.get('business_segments', [])

    def get_summary(self) -> Dict[str, Any]:
        """Get high-level summary of GOOGL"""
        return {
            'company': self.profile.get('name'),
            'symbol': self.profile.get('symbol'),
            'sector': self.profile.get('sector'),
            'industry': self.profile.get('industry'),
            'market_cap': self._format_number(self.profile.get('market_cap')),
            'stock_price': self.profile.get('stock_price'),
            'employees': self.profile.get('employee_count'),
            'ceo': self.profile.get('ceo'),
            'website': self.profile.get('website')
        }

    def get_valuation_summary(self) -> Dict[str, Any]:
        """Summarize valuation metrics"""
        summary = {
            'pe_ratio': self.ratios.get('pe_ratio'),
            'ev_to_ebitda': self.metrics.get('ev_to_ebitda'),
            'price_to_sales': self.ratios.get('price_to_sales'),
            'price_to_book': self.ratios.get('price_to_book'),
            'ev_to_revenue': self.metrics.get('ev_to_revenue'),
            'market_cap': self._format_number(self.metrics.get('market_cap')),
            'enterprise_value': self._format_number(self.metrics.get('enterprise_value'))
        }

        # Add assessment
        pe = self.ratios.get('pe_ratio')
        if pe:
            if pe < 20:
                assessment = "Undervalued (low P/E)"
            elif pe < 35:
                assessment = "Fairly valued"
            else:
                assessment = "Premium valuation (high P/E)"
            summary['assessment'] = assessment

        return summary

    def get_profitability_summary(self) -> Dict[str, Any]:
        """Summarize profitability metrics"""
        latest = self.income[0] if self.income else {}

        return {
            'gross_margin': f"{latest.get('gross_margin_percent', 0) * 100:.1f}%",
            'operating_margin': f"{latest.get('operating_margin_percent', 0) * 100:.1f}%",
            'net_margin': f"{latest.get('net_margin_percent', 0) * 100:.1f}%",
            'roe': f"{self.ratios.get('roe', 0) * 100:.1f}%",
            'roa': f"{self.ratios.get('roa', 0) * 100:.1f}%",
            'roic': f"{self.ratios.get('roic', 0) * 100:.1f}%",
            'eps': f"${latest.get('eps', 0):.2f}"
        }

    def get_financial_health_summary(self) -> Dict[str, Any]:
        """Summarize financial health metrics"""
        total_debt = self.balance.get('total_debt', 0) or 0
        cash = self.balance.get('cash_and_equivalents', 0) or 0
        net_debt = total_debt - cash

        return {
            'total_assets': self._format_number(self.balance.get('total_assets')),
            'total_debt': self._format_number(total_debt),
            'cash': self._format_number(cash),
            'net_debt': self._format_number(net_debt),
            'total_equity': self._format_number(self.balance.get('total_equity')),
            'current_ratio': f"{self.ratios.get('current_ratio', 0):.2f}",
            'quick_ratio': f"{self.ratios.get('quick_ratio', 0):.2f}",
            'debt_to_equity': f"{self.ratios.get('debt_to_equity', 0):.2f}",
            'net_debt_to_ebitda': self._calculate_net_debt_to_ebitda()
        }

    def get_growth_metrics(self) -> Dict[str, Any]:
        """Calculate growth metrics"""
        growth = {}

        if len(self.income) >= 2:
            # Revenue growth
            latest_rev = self.income[0].get('revenue') or 0
            prior_rev = self.income[1].get('revenue') or 0
            if prior_rev:
                rev_growth = ((latest_rev - prior_rev) / prior_rev) * 100
                growth['revenue_growth_yoy_percent'] = f"{rev_growth:.1f}%"

            # EPS growth
            latest_eps = self.income[0].get('eps') or 0
            prior_eps = self.income[1].get('eps') or 0
            if prior_eps:
                eps_growth = ((latest_eps - prior_eps) / abs(prior_eps)) * 100
                growth['eps_growth_yoy_percent'] = f"{eps_growth:.1f}%"

            # FCF metrics
            if self.metrics.get('free_cash_flow'):
                growth['free_cash_flow'] = self._format_number(self.metrics.get('free_cash_flow'))
                growth['fcf_per_share'] = f"${self.metrics.get('fcf_per_share', 0):.2f}"

        return growth

    def get_segment_breakdown(self) -> Dict[str, Any]:
        """Get business segment breakdown"""
        breakdown = {}

        for segment in self.segments:
            seg_name = segment.get('segment')
            revenue = segment.get('revenue') or 0
            ratio = segment.get('revenue_ratio') or 0

            breakdown[seg_name] = {
                'revenue': self._format_number(revenue),
                'percentage': f"{ratio * 100:.1f}%"
            }

        return breakdown

    def get_analyst_consensus(self) -> Dict[str, Any]:
        """Get analyst consensus estimates"""
        if not self.estimates:
            return {}

        # Get FY and quarterly estimates
        fy_estimates = [e for e in self.estimates if 'FY' in e.get('period', '')]
        q_estimates = [e for e in self.estimates if 'Q' in e.get('period', '')]

        consensus = {
            'fiscal_year_estimates': [],
            'quarterly_estimates': []
        }

        for est in fy_estimates[:2]:  # Next 2 fiscal years
            consensus['fiscal_year_estimates'].append({
                'period': est.get('date'),
                'estimated_revenue': self._format_number(est.get('estimated_revenue_avg')),
                'revenue_range': f"${est.get('estimated_revenue_low', 0)/1e9:.1f}B - ${est.get('estimated_revenue_high', 0)/1e9:.1f}B",
                'estimated_eps': f"${est.get('estimated_eps_avg', 0):.2f}",
                'eps_range': f"${est.get('estimated_eps_low', 0):.2f} - ${est.get('estimated_eps_high', 0):.2f}",
                'number_of_analysts': est.get('number_of_estimates')
            })

        for est in q_estimates[:4]:  # Next 4 quarters
            consensus['quarterly_estimates'].append({
                'period': est.get('date'),
                'estimated_revenue': self._format_number(est.get('estimated_revenue_avg')),
                'estimated_eps': f"${est.get('estimated_eps_avg', 0):.2f}",
                'number_of_analysts': est.get('number_of_estimates')
            })

        return consensus

    def generate_investment_thesis(self) -> Dict[str, Any]:
        """Generate investment thesis based on data"""
        thesis = {
            'timestamp': datetime.now().isoformat(),
            'company': self.profile.get('name'),
            'symbol': self.profile.get('symbol'),
            'summary': self.get_summary(),
            'valuation': self.get_valuation_summary(),
            'profitability': self.get_profitability_summary(),
            'financial_health': self.get_financial_health_summary(),
            'growth': self.get_growth_metrics(),
            'segments': self.get_segment_breakdown(),
            'analyst_consensus': self.get_analyst_consensus(),
            'strengths': self._identify_strengths(),
            'concerns': self._identify_concerns(),
            'investment_implications': self._assess_investment()
        }

        return thesis

    def save_analysis(self, filepath: str = None) -> str:
        """Save analysis to JSON file"""
        analysis = self.generate_investment_thesis()

        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"googl_research_analysis_{timestamp}.json"

        with open(filepath, 'w') as f:
            json.dump(analysis, f, indent=2)

        return filepath

    # Helper methods
    @staticmethod
    def _format_number(value) -> str:
        """Format large numbers for display"""
        if not value:
            return "N/A"

        if value >= 1e12:
            return f"${value/1e12:.2f}T"
        elif value >= 1e9:
            return f"${value/1e9:.2f}B"
        elif value >= 1e6:
            return f"${value/1e6:.2f}M"
        else:
            return f"${value:.2f}"

    def _calculate_net_debt_to_ebitda(self) -> str:
        """Calculate net debt to EBITDA"""
        total_debt = self.balance.get('total_debt', 0) or 0
        cash = self.balance.get('cash_and_equivalents', 0) or 0
        net_debt = total_debt - cash

        latest = self.income[0] if self.income else {}
        ebitda = latest.get('ebitda') or 0

        if ebitda:
            ratio = net_debt / ebitda
            return f"{ratio:.2f}x"
        return "N/A"

    def _identify_strengths(self) -> List[str]:
        """Identify investment strengths"""
        strengths = []

        # Strong profitability
        latest = self.income[0] if self.income else {}
        net_margin = latest.get('net_margin_percent') or 0
        if net_margin > 0.20:
            strengths.append("Exceptional profitability (>20% net margin)")

        # Strong ROE
        roe = self.ratios.get('roe') or 0
        if roe > 0.15:
            strengths.append("Strong return on equity (>15%)")

        # Strong balance sheet
        debt_to_eq = self.ratios.get('debt_to_equity') or 0
        if debt_to_eq < 0.1:
            strengths.append("Fortress balance sheet with minimal leverage")

        # Positive FCF
        fcf = self.metrics.get('free_cash_flow') or 0
        if fcf > 0:
            strengths.append("Strong free cash flow generation")

        # Diversified revenue
        if len(self.segments) > 1:
            largest_segment = max(self.segments, key=lambda x: x.get('revenue', 0))
            ratio = largest_segment.get('revenue_ratio', 0)
            if ratio < 0.80:
                strengths.append("Diversified revenue streams")

        return strengths

    def _identify_concerns(self) -> List[str]:
        """Identify investment concerns"""
        concerns = []

        # High valuation
        pe = self.ratios.get('pe_ratio') or 0
        if pe > 30:
            concerns.append(f"Premium valuation (P/E: {pe:.1f})")

        # Segment concentration
        if self.segments:
            largest_segment = max(self.segments, key=lambda x: x.get('revenue', 0))
            ratio = largest_segment.get('revenue_ratio', 0)
            if ratio > 0.75:
                seg_name = largest_segment.get('segment')
                concerns.append(f"High revenue concentration ({seg_name}: {ratio*100:.0f}%)")

        # Slowing growth
        if len(self.income) >= 2:
            latest_rev = self.income[0].get('revenue') or 0
            prior_rev = self.income[1].get('revenue') or 0
            if prior_rev:
                rev_growth = ((latest_rev - prior_rev) / prior_rev)
                if rev_growth < 0.05:
                    concerns.append(f"Modest revenue growth ({rev_growth*100:.1f}%)")

        return concerns

    def _assess_investment(self) -> Dict[str, Any]:
        """Assess investment potential"""
        pe = self.ratios.get('pe_ratio') or 0
        roe = self.ratios.get('roe') or 0
        ev_ebitda = self.metrics.get('ev_to_ebitda') or 0

        assessment = {
            'valuation_assessment': self._value_assessment(pe),
            'quality_assessment': self._quality_assessment(roe),
            'value_proposition': self._value_proposition(pe, roe, ev_ebitda)
        }

        return assessment

    @staticmethod
    def _value_assessment(pe: float) -> str:
        """Assess valuation"""
        if pe < 15:
            return "Attractive valuation"
        elif pe < 25:
            return "Fairly valued"
        elif pe < 35:
            return "Premium but justified by quality"
        else:
            return "Expensive relative to earnings"

    @staticmethod
    def _quality_assessment(roe: float) -> str:
        """Assess business quality"""
        if roe > 0.20:
            return "High quality business with excellent returns"
        elif roe > 0.15:
            return "Quality business with strong returns"
        elif roe > 0.10:
            return "Reasonable business quality"
        else:
            return "Lower quality business"

    @staticmethod
    def _value_proposition(pe: float, roe: float, ev_ebitda: float) -> str:
        """Assess overall value proposition"""
        value_score = 0

        if pe < 25:
            value_score += 1
        if roe > 0.15:
            value_score += 1
        if ev_ebitda < 15:
            value_score += 1

        if value_score >= 2:
            return "Attractive investment opportunity"
        elif value_score >= 1:
            return "Reasonable investment with certain strengths"
        else:
            return "Consider waiting for better entry point"


# Convenience functions
def fetch_and_analyze_googl() -> Dict[str, Any]:
    """Fetch GOOGL data and generate analysis"""
    fetcher = FMPResearchFetcher()
    research_data = fetcher.fetch_all('GOOGL')

    analyzer = GOOGLResearchAnalyzer(research_data)
    return analyzer.generate_investment_thesis()


def save_googl_analysis(output_dir: str = ".") -> str:
    """Fetch GOOGL data and save analysis"""
    fetcher = FMPResearchFetcher()
    research_data = fetcher.fetch_all('GOOGL')

    analyzer = GOOGLResearchAnalyzer(research_data)
    output_path = Path(output_dir) / f"googl_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    return analyzer.save_analysis(str(output_path))


if __name__ == '__main__':
    # Example usage
    print("Fetching GOOGL data and generating analysis...")
    analysis = fetch_and_analyze_googl()
    print(json.dumps(analysis, indent=2))

    # Save to file
    filepath = save_googl_analysis()
    print(f"\nAnalysis saved to: {filepath}")
