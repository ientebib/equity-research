#!/usr/bin/env python3
"""
GOOGL Comprehensive Equity Research Data Fetcher
Fetches data from Financial Modeling Prep API and saves as JSON
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

# Import the data fetcher
from fetch_googl_research_data import main as fetch_data

def save_results(results: dict, symbol: str = "GOOGL"):
    """Save results to JSON file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = project_root / f"googl_research_data_{timestamp}.json"

    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    return output_file

if __name__ == '__main__':
    # Import and run the fetch function
    import urllib.request
    import json as json_module

    FMP_API_KEY = "tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3"
    BASE_URL = "https://financialmodelingprep.com/api/v3"
    SYMBOL = "GOOGL"

    def fetch_fmp_data(endpoint, symbol=SYMBOL, params=""):
        """Fetch data from FMP API"""
        url = f"{BASE_URL}/{endpoint}/{symbol}{params}&apikey={FMP_API_KEY}"
        try:
            print(f"Fetching: {endpoint}...", file=sys.stderr)
            with urllib.request.urlopen(url, timeout=15) as response:
                data = json_module.loads(response.read().decode())
                return data
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            return None

    results = {}

    print("Starting GOOGL data collection...\n", file=sys.stderr)

    # Fetch all endpoints
    endpoints = [
        ('profile', {}, "Company Profile"),
        ('income-statement', '?limit=5', "Income Statement (5 years)"),
        ('balance-sheet-statement', '?limit=1', "Balance Sheet"),
        ('ratios', '?limit=1', "Financial Ratios"),
        ('key-metrics', '?limit=1', "Key Metrics"),
        ('analyst-estimates', '?limit=8', "Analyst Estimates"),
        ('revenue-product-segmentation', '?structure=flat', "Business Segments")
    ]

    for endpoint, params, description in endpoints:
        try:
            data = fetch_fmp_data(endpoint, SYMBOL, params)
            if data:
                results[endpoint] = data
                print(f"  OK: {description}\n", file=sys.stderr)
            else:
                print(f"  FAILED: {description} (No data)\n", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {description}: {e}\n", file=sys.stderr)

    # Save results
    output_file = save_results(results, SYMBOL)
    print(f"\nResults saved to: {output_file}", file=sys.stderr)

    # Print consolidated JSON
    print(json_module.dumps(results, indent=2))
