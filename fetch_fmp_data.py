#!/usr/bin/env python3
"""
Fetch comprehensive financial data for GOOGL from Financial Modeling Prep API
"""

import json
import urllib.request
import sys
from datetime import datetime

def fetch_fmp_data(endpoint, symbol="GOOGL", params=""):
    """Fetch data from FMP API"""
    url = f"https://financialmodelingprep.com/api/v3/{endpoint}/{symbol}{params}"
    try:
        print(f"Fetching: {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"Error fetching {endpoint}: {str(e)}", file=sys.stderr)
        return None

def main():
    # Fetch all data
    results = {
        'fetch_timestamp': datetime.now().isoformat(),
        'symbol': 'GOOGL',
        'data_sources': []
    }

    print("Starting data collection for GOOGL...", file=sys.stderr)

    # 1. Company Profile
    print("\n1. Fetching company profile...", file=sys.stderr)
    profile = fetch_fmp_data('profile')
    results['company_profile'] = profile[0] if profile and len(profile) > 0 else profile
    results['data_sources'].append('profile')

    # 2. Income Statement (5 years)
    print("2. Fetching income statement (5 years)...", file=sys.stderr)
    income = fetch_fmp_data('income-statement', params='?limit=5')
    results['income_statement'] = income if income else []
    results['data_sources'].append('income-statement')

    # 3. Balance Sheet (most recent)
    print("3. Fetching balance sheet...", file=sys.stderr)
    balance = fetch_fmp_data('balance-sheet-statement', params='?limit=1')
    results['balance_sheet'] = balance[0] if balance and len(balance) > 0 else balance
    results['data_sources'].append('balance-sheet-statement')

    # 4. Financial Ratios (most recent)
    print("4. Fetching financial ratios...", file=sys.stderr)
    ratios = fetch_fmp_data('ratios', params='?limit=1')
    results['financial_ratios'] = ratios[0] if ratios and len(ratios) > 0 else ratios
    results['data_sources'].append('ratios')

    # 5. Key Metrics (for EV/EBITDA)
    print("5. Fetching key metrics...", file=sys.stderr)
    metrics = fetch_fmp_data('key-metrics', params='?limit=1')
    results['key_metrics'] = metrics[0] if metrics and len(metrics) > 0 else metrics
    results['data_sources'].append('key-metrics')

    # 6. Analyst Estimates (next 2 years)
    print("6. Fetching analyst estimates...", file=sys.stderr)
    estimates = fetch_fmp_data('analyst-estimates', params='?limit=8')
    results['analyst_estimates'] = estimates if estimates else []
    results['data_sources'].append('analyst-estimates')

    # 7. Revenue by Segment
    print("7. Fetching business segments...", file=sys.stderr)
    segments = fetch_fmp_data('revenue-product-segmentation', params='?structure=flat')
    results['business_segments'] = segments if segments else []
    results['data_sources'].append('revenue-product-segmentation')

    print("\nData collection complete!", file=sys.stderr)

    # Output consolidated JSON
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
