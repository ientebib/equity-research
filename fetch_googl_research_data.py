#!/usr/bin/env python3
"""
Comprehensive Financial Data Fetcher for GOOGL from Financial Modeling Prep API
Returns consolidated JSON with all required equity research data
"""

import json
import urllib.request
import sys
from datetime import datetime
from pathlib import Path

# Configuration
FMP_API_KEY = "tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3"
BASE_URL = "https://financialmodelingprep.com/api/v3"
SYMBOL = "GOOGL"

def fetch_fmp_data(endpoint, symbol=SYMBOL, params=""):
    """Fetch data from FMP API with API key"""
    url = f"{BASE_URL}/{endpoint}/{symbol}{params}&apikey={FMP_API_KEY}"
    try:
        print(f"Fetching: {endpoint} for {symbol}...", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"Error fetching {endpoint}: {str(e)}", file=sys.stderr)
        return None

def process_company_profile(data):
    """Process company profile data"""
    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    profile = data[0]
    return {
        'symbol': profile.get('symbol'),
        'name': profile.get('companyName'),
        'sector': profile.get('sector'),
        'industry': profile.get('industry'),
        'description': profile.get('description'),
        'website': profile.get('website'),
        'ceo': profile.get('ceo'),
        'exchange': profile.get('exchangeShortName'),
        'market_cap': profile.get('mktCap'),
        'employee_count': profile.get('employees'),
        'country': profile.get('country'),
        'stock_price': profile.get('price'),
        'beta': profile.get('beta'),
        'ipo_date': profile.get('ipoDate'),
        'full_data': profile
    }

def process_income_statement(data):
    """Process income statement data for multiple periods"""
    if not data or not isinstance(data, list):
        return []

    processed = []
    for item in data[:5]:  # Get last 5 years
        processed.append({
            'date': item.get('date'),
            'period': item.get('period'),
            'revenue': item.get('revenue'),
            'cost_of_revenue': item.get('costOfRevenue'),
            'gross_profit': item.get('grossProfit'),
            'gross_margin_percent': item.get('grossProfitRatio'),
            'operating_expenses': item.get('operatingExpenses'),
            'operating_income': item.get('operatingIncome'),
            'operating_margin_percent': item.get('operatingExpensesRatio'),
            'ebitda': item.get('ebitda'),
            'net_income': item.get('netIncome'),
            'net_margin_percent': item.get('netIncomeRatio'),
            'eps': item.get('eps'),
            'full_data': item
        })

    return processed

def process_balance_sheet(data):
    """Process balance sheet data"""
    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    sheet = data[0]
    return {
        'date': sheet.get('date'),
        'period': sheet.get('period'),
        'current_assets': sheet.get('totalCurrentAssets'),
        'total_assets': sheet.get('totalAssets'),
        'current_liabilities': sheet.get('totalCurrentLiabilities'),
        'total_liabilities': sheet.get('totalLiabilities'),
        'total_equity': sheet.get('totalStockholdersEquity'),
        'cash_and_equivalents': sheet.get('cashAndCashEquivalents'),
        'short_term_debt': sheet.get('shortTermDebt'),
        'long_term_debt': sheet.get('longTermDebt'),
        'total_debt': sheet.get('shortTermDebt', 0) + sheet.get('longTermDebt', 0),
        'retained_earnings': sheet.get('retainedEarnings'),
        'common_stock': sheet.get('commonStock'),
        'full_data': sheet
    }

def process_financial_ratios(data):
    """Process financial ratios"""
    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    ratios = data[0]
    return {
        'date': ratios.get('date'),
        'period': ratios.get('period'),
        'pe_ratio': ratios.get('priceToEarningsRatio'),
        'price_to_sales': ratios.get('priceToSalesRatio'),
        'price_to_book': ratios.get('priceToBookRatio'),
        'roe': ratios.get('returnOnEquity'),
        'roa': ratios.get('returnOnAssets'),
        'roic': ratios.get('returnOnCapitalEmployed'),
        'debt_to_equity': ratios.get('debtToEquity'),
        'debt_to_assets': ratios.get('debtToAssets'),
        'current_ratio': ratios.get('currentRatio'),
        'quick_ratio': ratios.get('quickRatio'),
        'cash_ratio': ratios.get('cashRatio'),
        'asset_turnover': ratios.get('assetTurnover'),
        'receivables_turnover': ratios.get('receivablesTurnover'),
        'inventory_turnover': ratios.get('inventoryTurnover'),
        'full_data': ratios
    }

def process_key_metrics(data):
    """Process key metrics"""
    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    metrics = data[0]
    return {
        'date': metrics.get('date'),
        'period': metrics.get('period'),
        'enterprise_value': metrics.get('enterpriseValue'),
        'ev_to_revenue': metrics.get('enterpriseValueOverRevenue'),
        'ev_to_ebitda': metrics.get('enterpriseValueOverEBITDA'),
        'free_cash_flow': metrics.get('freeCashFlow'),
        'fcf_per_share': metrics.get('freeCashFlowPerShare'),
        'book_value_per_share': metrics.get('bookValuePerShare'),
        'dividend_per_share': metrics.get('dividendPerShare'),
        'net_income_per_share': metrics.get('netIncomePerShare'),
        'revenue_per_share': metrics.get('revenuePerShare'),
        'shares_outstanding': metrics.get('sharesOutstanding'),
        'market_cap': metrics.get('marketCap'),
        'full_data': metrics
    }

def process_analyst_estimates(data):
    """Process analyst estimates"""
    if not data or not isinstance(data, list):
        return []

    processed = []
    for item in data[:8]:  # Get next 2 years of estimates
        processed.append({
            'date': item.get('date'),
            'period': item.get('period'),
            'estimated_revenue_low': item.get('estimatedRevenueMin'),
            'estimated_revenue_high': item.get('estimatedRevenueMax'),
            'estimated_revenue_avg': item.get('estimatedRevenue'),
            'estimated_eps_low': item.get('estimatedEPSMin'),
            'estimated_eps_high': item.get('estimatedEPSMax'),
            'estimated_eps_avg': item.get('estimatedEPS'),
            'number_of_estimates': item.get('numberEstimates'),
            'full_data': item
        })

    return processed

def process_business_segments(data):
    """Process business segment information"""
    if not data or not isinstance(data, list):
        return []

    processed = []
    for item in data:
        processed.append({
            'segment': item.get('segment'),
            'revenue': item.get('revenue'),
            'revenue_ratio': item.get('revenueRatio'),
            'full_data': item
        })

    return processed

def main():
    """Main execution function"""
    print(f"Starting GOOGL data collection at {datetime.now().isoformat()}", file=sys.stderr)

    results = {
        'metadata': {
            'symbol': SYMBOL,
            'company_name': 'Alphabet Inc.',
            'fetch_timestamp': datetime.now().isoformat(),
            'api_provider': 'Financial Modeling Prep',
            'data_completeness': 'PENDING'
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

    # 1. Company Profile
    try:
        print("\n1/7 Fetching Company Profile...", file=sys.stderr)
        profile_data = fetch_fmp_data('profile')
        results['company_profile'] = process_company_profile(profile_data)
        if results['company_profile']:
            results['fetch_summary']['successful'].append('company_profile')
            print("    SUCCESS", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('company_profile')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('company_profile')

    # 2. Income Statement (5 years)
    try:
        print("2/7 Fetching Income Statement (5 years)...", file=sys.stderr)
        income_data = fetch_fmp_data('income-statement', params='?limit=5')
        results['income_statement'] = process_income_statement(income_data)
        if results['income_statement']:
            results['fetch_summary']['successful'].append('income_statement')
            print(f"    SUCCESS - {len(results['income_statement'])} periods", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('income_statement')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('income_statement')

    # 3. Balance Sheet
    try:
        print("3/7 Fetching Balance Sheet...", file=sys.stderr)
        balance_data = fetch_fmp_data('balance-sheet-statement', params='?limit=1')
        results['balance_sheet'] = process_balance_sheet(balance_data)
        if results['balance_sheet']:
            results['fetch_summary']['successful'].append('balance_sheet')
            print("    SUCCESS", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('balance_sheet')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('balance_sheet')

    # 4. Financial Ratios
    try:
        print("4/7 Fetching Financial Ratios...", file=sys.stderr)
        ratios_data = fetch_fmp_data('ratios', params='?limit=1')
        results['financial_ratios'] = process_financial_ratios(ratios_data)
        if results['financial_ratios']:
            results['fetch_summary']['successful'].append('financial_ratios')
            print("    SUCCESS", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('financial_ratios')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('financial_ratios')

    # 5. Key Metrics
    try:
        print("5/7 Fetching Key Metrics...", file=sys.stderr)
        metrics_data = fetch_fmp_data('key-metrics', params='?limit=1')
        results['key_metrics'] = process_key_metrics(metrics_data)
        if results['key_metrics']:
            results['fetch_summary']['successful'].append('key_metrics')
            print("    SUCCESS", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('key_metrics')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('key_metrics')

    # 6. Analyst Estimates
    try:
        print("6/7 Fetching Analyst Estimates...", file=sys.stderr)
        estimates_data = fetch_fmp_data('analyst-estimates', params='?limit=8')
        results['analyst_estimates'] = process_analyst_estimates(estimates_data)
        if results['analyst_estimates']:
            results['fetch_summary']['successful'].append('analyst_estimates')
            print(f"    SUCCESS - {len(results['analyst_estimates'])} periods", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('analyst_estimates')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('analyst_estimates')

    # 7. Business Segments
    try:
        print("7/7 Fetching Business Segments...", file=sys.stderr)
        segments_data = fetch_fmp_data('revenue-product-segmentation', params='?structure=flat')
        results['business_segments'] = process_business_segments(segments_data)
        if results['business_segments']:
            results['fetch_summary']['successful'].append('business_segments')
            print(f"    SUCCESS - {len(results['business_segments'])} segments", file=sys.stderr)
        else:
            results['fetch_summary']['failed'].append('business_segments')
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        results['fetch_summary']['failed'].append('business_segments')

    # Update metadata
    results['metadata']['data_completeness'] = f"{len(results['fetch_summary']['successful'])}/7 sources successful"

    # Print JSON output
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
