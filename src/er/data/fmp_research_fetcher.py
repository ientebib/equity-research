"""
Financial Modeling Prep (FMP) API Integration for Equity Research
Fetches comprehensive financial data for companies
"""

import json
import urllib.request
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class FMPResearchFetcher:
    """Fetch comprehensive financial research data from FMP API"""

    def __init__(self, api_key: str = "tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3"):
        """Initialize FMP API fetcher"""
        self.api_key = api_key
        self.base_url = "https://financialmodelingprep.com/api/v3"
        self.timeout = 15

    def fetch(self, endpoint: str, symbol: str, params: str = "") -> Optional[Dict[str, Any]]:
        """Fetch data from FMP API"""
        url = f"{self.base_url}/{endpoint}/{symbol}{params}&apikey={self.api_key}"

        try:
            logger.info(f"Fetching {endpoint} for {symbol}...")
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                data = json.loads(response.read().decode())
                logger.info(f"Successfully fetched {endpoint}")
                return data
        except urllib.error.URLError as e:
            logger.error(f"URL Error fetching {endpoint}: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON Error parsing {endpoint}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {endpoint}: {str(e)}")
            return None

    def fetch_company_profile(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch company profile"""
        data = self.fetch('profile', symbol)
        if data and isinstance(data, list) and len(data) > 0:
            return self._process_profile(data[0])
        return None

    def fetch_income_statement(self, symbol: str, years: int = 5) -> List[Dict[str, Any]]:
        """Fetch income statement for N years"""
        data = self.fetch('income-statement', symbol, f'?limit={years}')
        if data and isinstance(data, list):
            return [self._process_income_statement_entry(item) for item in data[:years]]
        return []

    def fetch_balance_sheet(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch most recent balance sheet"""
        data = self.fetch('balance-sheet-statement', symbol, '?limit=1')
        if data and isinstance(data, list) and len(data) > 0:
            return self._process_balance_sheet(data[0])
        return None

    def fetch_financial_ratios(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch most recent financial ratios"""
        data = self.fetch('ratios', symbol, '?limit=1')
        if data and isinstance(data, list) and len(data) > 0:
            return self._process_financial_ratios(data[0])
        return None

    def fetch_key_metrics(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch most recent key metrics"""
        data = self.fetch('key-metrics', symbol, '?limit=1')
        if data and isinstance(data, list) and len(data) > 0:
            return self._process_key_metrics(data[0])
        return None

    def fetch_analyst_estimates(self, symbol: str, periods: int = 8) -> List[Dict[str, Any]]:
        """Fetch analyst estimates for N periods"""
        data = self.fetch('analyst-estimates', symbol, f'?limit={periods}')
        if data and isinstance(data, list):
            return [self._process_analyst_estimate(item) for item in data[:periods]]
        return []

    def fetch_business_segments(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch business segment breakdown"""
        data = self.fetch('revenue-product-segmentation', symbol, '?structure=flat')
        if data and isinstance(data, list):
            return [self._process_business_segment(item) for item in data]
        return []

    def fetch_all(self, symbol: str) -> Dict[str, Any]:
        """Fetch all research data for a company"""
        results = {
            'metadata': {
                'symbol': symbol,
                'fetch_timestamp': datetime.now().isoformat(),
                'api_provider': 'Financial Modeling Prep',
                'status': 'pending'
            },
            'company_profile': None,
            'income_statement': [],
            'balance_sheet': None,
            'financial_ratios': None,
            'key_metrics': None,
            'analyst_estimates': [],
            'business_segments': [],
            'fetch_summary': {
                'successful': [],
                'failed': []
            }
        }

        # Fetch all data points
        try:
            logger.info(f"Starting full data collection for {symbol}...")

            profile = self.fetch_company_profile(symbol)
            results['company_profile'] = profile
            if profile:
                results['fetch_summary']['successful'].append('company_profile')
                results['metadata']['company_name'] = profile.get('name')
            else:
                results['fetch_summary']['failed'].append('company_profile')

            income = self.fetch_income_statement(symbol)
            results['income_statement'] = income
            if income:
                results['fetch_summary']['successful'].append('income_statement')
            else:
                results['fetch_summary']['failed'].append('income_statement')

            balance = self.fetch_balance_sheet(symbol)
            results['balance_sheet'] = balance
            if balance:
                results['fetch_summary']['successful'].append('balance_sheet')
            else:
                results['fetch_summary']['failed'].append('balance_sheet')

            ratios = self.fetch_financial_ratios(symbol)
            results['financial_ratios'] = ratios
            if ratios:
                results['fetch_summary']['successful'].append('financial_ratios')
            else:
                results['fetch_summary']['failed'].append('financial_ratios')

            metrics = self.fetch_key_metrics(symbol)
            results['key_metrics'] = metrics
            if metrics:
                results['fetch_summary']['successful'].append('key_metrics')
            else:
                results['fetch_summary']['failed'].append('key_metrics')

            estimates = self.fetch_analyst_estimates(symbol)
            results['analyst_estimates'] = estimates
            if estimates:
                results['fetch_summary']['successful'].append('analyst_estimates')
            else:
                results['fetch_summary']['failed'].append('analyst_estimates')

            segments = self.fetch_business_segments(symbol)
            results['business_segments'] = segments
            if segments:
                results['fetch_summary']['successful'].append('business_segments')
            else:
                results['fetch_summary']['failed'].append('business_segments')

            # Update status
            successful_count = len(results['fetch_summary']['successful'])
            results['metadata']['status'] = f"{successful_count}/7 sources successful"
            results['metadata']['data_completeness'] = successful_count == 7

            logger.info(f"Data collection complete: {results['metadata']['status']}")

        except Exception as e:
            logger.error(f"Error during data collection: {str(e)}")
            results['metadata']['status'] = f"Error: {str(e)}"

        return results

    # Data processing methods
    @staticmethod
    def _process_profile(data: Dict) -> Dict[str, Any]:
        """Process company profile data"""
        return {
            'symbol': data.get('symbol'),
            'name': data.get('companyName'),
            'sector': data.get('sector'),
            'industry': data.get('industry'),
            'description': data.get('description'),
            'website': data.get('website'),
            'ceo': data.get('ceo'),
            'exchange': data.get('exchangeShortName'),
            'market_cap': data.get('mktCap'),
            'employee_count': data.get('employees'),
            'country': data.get('country'),
            'stock_price': data.get('price'),
            'beta': data.get('beta'),
            'ipo_date': data.get('ipoDate')
        }

    @staticmethod
    def _process_income_statement_entry(data: Dict) -> Dict[str, Any]:
        """Process income statement entry"""
        return {
            'date': data.get('date'),
            'period': data.get('period'),
            'revenue': data.get('revenue'),
            'cost_of_revenue': data.get('costOfRevenue'),
            'gross_profit': data.get('grossProfit'),
            'gross_margin_percent': data.get('grossProfitRatio'),
            'operating_expenses': data.get('operatingExpenses'),
            'operating_income': data.get('operatingIncome'),
            'operating_margin_percent': data.get('operatingExpensesRatio'),
            'ebitda': data.get('ebitda'),
            'net_income': data.get('netIncome'),
            'net_margin_percent': data.get('netIncomeRatio'),
            'eps': data.get('eps')
        }

    @staticmethod
    def _process_balance_sheet(data: Dict) -> Dict[str, Any]:
        """Process balance sheet data"""
        return {
            'date': data.get('date'),
            'period': data.get('period'),
            'current_assets': data.get('totalCurrentAssets'),
            'total_assets': data.get('totalAssets'),
            'current_liabilities': data.get('totalCurrentLiabilities'),
            'total_liabilities': data.get('totalLiabilities'),
            'total_equity': data.get('totalStockholdersEquity'),
            'cash_and_equivalents': data.get('cashAndCashEquivalents'),
            'short_term_debt': data.get('shortTermDebt'),
            'long_term_debt': data.get('longTermDebt'),
            'total_debt': (data.get('shortTermDebt', 0) or 0) + (data.get('longTermDebt', 0) or 0),
            'retained_earnings': data.get('retainedEarnings'),
            'common_stock': data.get('commonStock')
        }

    @staticmethod
    def _process_financial_ratios(data: Dict) -> Dict[str, Any]:
        """Process financial ratios"""
        return {
            'date': data.get('date'),
            'period': data.get('period'),
            'pe_ratio': data.get('priceToEarningsRatio'),
            'price_to_sales': data.get('priceToSalesRatio'),
            'price_to_book': data.get('priceToBookRatio'),
            'roe': data.get('returnOnEquity'),
            'roa': data.get('returnOnAssets'),
            'roic': data.get('returnOnCapitalEmployed'),
            'debt_to_equity': data.get('debtToEquity'),
            'debt_to_assets': data.get('debtToAssets'),
            'current_ratio': data.get('currentRatio'),
            'quick_ratio': data.get('quickRatio'),
            'cash_ratio': data.get('cashRatio'),
            'asset_turnover': data.get('assetTurnover')
        }

    @staticmethod
    def _process_key_metrics(data: Dict) -> Dict[str, Any]:
        """Process key metrics"""
        return {
            'date': data.get('date'),
            'period': data.get('period'),
            'enterprise_value': data.get('enterpriseValue'),
            'ev_to_revenue': data.get('enterpriseValueOverRevenue'),
            'ev_to_ebitda': data.get('enterpriseValueOverEBITDA'),
            'free_cash_flow': data.get('freeCashFlow'),
            'fcf_per_share': data.get('freeCashFlowPerShare'),
            'book_value_per_share': data.get('bookValuePerShare'),
            'dividend_per_share': data.get('dividendPerShare'),
            'net_income_per_share': data.get('netIncomePerShare'),
            'revenue_per_share': data.get('revenuePerShare'),
            'shares_outstanding': data.get('sharesOutstanding'),
            'market_cap': data.get('marketCap')
        }

    @staticmethod
    def _process_analyst_estimate(data: Dict) -> Dict[str, Any]:
        """Process analyst estimate"""
        return {
            'date': data.get('date'),
            'period': data.get('period'),
            'estimated_revenue_low': data.get('estimatedRevenueMin'),
            'estimated_revenue_high': data.get('estimatedRevenueMax'),
            'estimated_revenue_avg': data.get('estimatedRevenue'),
            'estimated_eps_low': data.get('estimatedEPSMin'),
            'estimated_eps_high': data.get('estimatedEPSMax'),
            'estimated_eps_avg': data.get('estimatedEPS'),
            'number_of_estimates': data.get('numberEstimates')
        }

    @staticmethod
    def _process_business_segment(data: Dict) -> Dict[str, Any]:
        """Process business segment"""
        return {
            'segment': data.get('segment'),
            'revenue': data.get('revenue'),
            'revenue_ratio': data.get('revenueRatio')
        }


# Main entry point for command-line usage
def main():
    """Fetch GOOGL research data and print JSON"""
    import sys

    fetcher = FMPResearchFetcher()
    symbol = sys.argv[1] if len(sys.argv) > 1 else "GOOGL"

    results = fetcher.fetch_all(symbol)
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
