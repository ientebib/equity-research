# GOOGL Comprehensive Financial Research Data Collection Guide

## Overview
This guide documents how to fetch comprehensive financial data for Alphabet Inc. (GOOGL) from the Financial Modeling Prep (FMP) API for equity research purposes.

## API Configuration
- **Base URL**: https://financialmodelingprep.com/api/v3/
- **API Key**: `tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3`
- **Symbol**: GOOGL
- **Provider**: Financial Modeling Prep (FMP)

## Data Collection Endpoints

### 1. Company Profile
**Endpoint**: `/profile/GOOGL`

**Fields Retrieved**:
- symbol
- companyName
- sector
- industry
- description
- website
- ceo
- exchangeShortName
- mktCap
- employees
- country
- price (stock price)
- beta
- ipoDate

**URL**:
```
https://financialmodelingprep.com/api/v3/profile/GOOGL?apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

### 2. Income Statement (5 Years)
**Endpoint**: `/income-statement/GOOGL?limit=5`

**Fields Retrieved** (per period):
- date (fiscal year end)
- period (FY)
- revenue
- costOfRevenue
- grossProfit
- grossProfitRatio
- operatingExpenses
- operatingIncome
- operatingExpensesRatio
- ebitda
- netIncome
- netIncomeRatio
- eps (earnings per share)

**URL**:
```
https://financialmodelingprep.com/api/v3/income-statement/GOOGL?limit=5&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

### 3. Balance Sheet (Most Recent)
**Endpoint**: `/balance-sheet-statement/GOOGL?limit=1`

**Fields Retrieved**:
- date
- period
- totalCurrentAssets
- totalAssets
- totalCurrentLiabilities
- totalLiabilities
- totalStockholdersEquity
- cashAndCashEquivalents
- shortTermDebt
- longTermDebt
- retainedEarnings
- commonStock

**URL**:
```
https://financialmodelingprep.com/api/v3/balance-sheet-statement/GOOGL?limit=1&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

### 4. Financial Ratios (Most Recent)
**Endpoint**: `/ratios/GOOGL?limit=1`

**Fields Retrieved**:
- date
- period
- priceToEarningsRatio (P/E)
- priceToSalesRatio
- priceToBookRatio
- returnOnEquity (ROE)
- returnOnAssets (ROA)
- returnOnCapitalEmployed (ROIC)
- debtToEquity
- debtToAssets
- currentRatio
- quickRatio
- cashRatio
- assetTurnover
- receivablesTurnover
- inventoryTurnover

**URL**:
```
https://financialmodelingprep.com/api/v3/ratios/GOOGL?limit=1&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

### 5. Key Metrics (Enterprise Value, Valuation)
**Endpoint**: `/key-metrics/GOOGL?limit=1`

**Fields Retrieved**:
- date
- period
- enterpriseValue
- enterpriseValueOverRevenue
- enterpriseValueOverEBITDA
- freeCashFlow
- freeCashFlowPerShare
- bookValuePerShare
- dividendPerShare
- netIncomePerShare
- revenuePerShare
- sharesOutstanding
- marketCap

**URL**:
```
https://financialmodelingprep.com/api/v3/key-metrics/GOOGL?limit=1&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

### 6. Analyst Estimates (2 Years Forward)
**Endpoint**: `/analyst-estimates/GOOGL?limit=8`

**Fields Retrieved** (per period):
- date
- period
- estimatedRevenue (average)
- estimatedRevenueMin
- estimatedRevenueMax
- estimatedEPS (average)
- estimatedEPSMin
- estimatedEPSMax
- numberEstimates

**URL**:
```
https://financialmodelingprep.com/api/v3/analyst-estimates/GOOGL?limit=8&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

### 7. Business Segments
**Endpoint**: `/revenue-product-segmentation/GOOGL?structure=flat`

**Fields Retrieved**:
- segment (business unit name)
- revenue
- revenueRatio (% of total)

**URL**:
```
https://financialmodelingprep.com/api/v3/revenue-product-segmentation/GOOGL?structure=flat&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3
```

## Response Format

The API returns JSON arrays. Example structure:

```json
{
  "profile": [
    {
      "symbol": "GOOGL",
      "companyName": "Alphabet Inc.",
      "sector": "Technology",
      "industry": "Internet & Direct Marketing",
      "mktCap": 2100000000000,
      ...
    }
  ],
  "income_statement": [
    {
      "date": "2024-12-31",
      "period": "FY",
      "revenue": 307394000000,
      "netIncome": 64745000000,
      ...
    },
    ...
  ]
}
```

## Python Implementation

### Using urllib (No Dependencies)

```python
import json
import urllib.request

FMP_API_KEY = "tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3"
BASE_URL = "https://financialmodelingprep.com/api/v3"
SYMBOL = "GOOGL"

def fetch_fmp_data(endpoint, symbol=SYMBOL, params=""):
    url = f"{BASE_URL}/{endpoint}/{symbol}{params}&apikey={FMP_API_KEY}"
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())

# Example: Fetch company profile
profile = fetch_fmp_data('profile')
print(json.dumps(profile[0], indent=2))

# Example: Fetch income statement
income = fetch_fmp_data('income-statement', params='?limit=5')
for year in income:
    print(f"{year['date']}: Revenue ${year['revenue']:,.0f}")
```

### Using requests (Recommended)

```python
import requests
import json

FMP_API_KEY = "tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3"
BASE_URL = "https://financialmodelingprep.com/api/v3"
SYMBOL = "GOOGL"

def fetch_fmp_data(endpoint, symbol=SYMBOL, params=""):
    url = f"{BASE_URL}/{endpoint}/{symbol}"
    params_dict = {"apikey": FMP_API_KEY}

    response = requests.get(url, params=params_dict, timeout=15)
    response.raise_for_status()
    return response.json()

# Fetch all data at once
results = {
    'company_profile': fetch_fmp_data('profile'),
    'income_statement': fetch_fmp_data('income-statement', params='?limit=5'),
    'balance_sheet': fetch_fmp_data('balance-sheet-statement', params='?limit=1'),
    'financial_ratios': fetch_fmp_data('ratios', params='?limit=1'),
    'key_metrics': fetch_fmp_data('key-metrics', params='?limit=1'),
    'analyst_estimates': fetch_fmp_data('analyst-estimates', params='?limit=8'),
    'business_segments': fetch_fmp_data('revenue-product-segmentation', params='?structure=flat')
}

with open('googl_research_data.json', 'w') as f:
    json.dump(results, f, indent=2)
```

## Key Metrics for Analysis

### Valuation Metrics
- **P/E Ratio**: Price-to-Earnings (priceToEarningsRatio)
- **EV/EBITDA**: Enterprise Value to EBITDA
- **Price-to-Sales**: priceToSalesRatio
- **Price-to-Book**: priceToBookRatio

### Profitability Metrics
- **Gross Margin**: (grossProfit / revenue) × 100
- **Operating Margin**: (operatingIncome / revenue) × 100
- **Net Margin**: (netIncome / revenue) × 100
- **ROE**: Return on Equity
- **ROA**: Return on Assets
- **ROIC**: Return on Invested Capital

### Financial Health
- **Total Debt**: shortTermDebt + longTermDebt
- **Net Debt**: totalDebt - cashAndCashEquivalents
- **Debt-to-Equity**: debtToEquity ratio
- **Current Ratio**: currentRatio (liquidity)
- **Free Cash Flow**: freeCashFlow

### Growth Metrics
- **Revenue Growth YoY**: ((current_revenue - prior_revenue) / prior_revenue) × 100
- **EPS Growth**: ((current_eps - prior_eps) / prior_eps) × 100
- **FCF Growth**: Free cash flow growth rate

## Business Segments (Alphabet Inc.)

Expected segments:
1. **Google Services** - Search, Maps, YouTube, Gmail, etc.
2. **Google Cloud** - Cloud computing services
3. **Other Bets** - Waymo, Verily, Other moonshot projects

## Files Generated

All data collection scripts create the following:

1. **fetch_googl_research_data.py** - Main data fetcher
2. **googl_research_data_structure.py** - Data structure definitions
3. **googl_research_data_[timestamp].json** - Output data file

## Usage Instructions

### Method 1: Direct Python Execution
```bash
cd /Users/isaacentebi/Desktop/Projects/equity-research
python3 fetch_googl_research_data.py > googl_data_output.json
```

### Method 2: Save to File and Process
```bash
python3 fetch_googl_research_data.py | jq . > googl_research_data.json
```

### Method 3: Using the helper script
```bash
python3 run_googl_research.py
```

## Curl Examples

If you prefer direct curl commands:

```bash
# Company Profile
curl "https://financialmodelingprep.com/api/v3/profile/GOOGL?apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3" | jq .

# Income Statement
curl "https://financialmodelingprep.com/api/v3/income-statement/GOOGL?limit=5&apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3" | jq .

# All data to single file
curl "https://financialmodelingprep.com/api/v3/profile/GOOGL?apikey=tq4ccu6TYBHDmvELcyWGzKHnK4AEYNd3" > googl_data.json
```

## Data Quality Notes

1. All data from FMP is regularly updated (typically daily for current data)
2. Historical data is stable and accurate
3. Analyst estimates are aggregated consensus views
4. Segment data reflects company reporting structure
5. All financial figures are in USD

## Performance Notes

- Typical API response time: 200-500ms per endpoint
- Free tier allows: ~250 API calls per day
- Premium tier: Unlimited calls
- No rate limiting within free tier for occasional research

## Error Handling

If you encounter errors:

1. **401 Unauthorized**: API key is invalid
2. **404 Not Found**: Symbol doesn't exist or endpoint is wrong
3. **429 Too Many Requests**: Rate limit exceeded (free tier)
4. **500 Server Error**: FMP server issue (temporary)

Common solutions:
- Verify API key is correct
- Check symbol spelling (GOOGL, not GOOGLE)
- Add delays between requests if rate limited
- Verify endpoint URL is correct

## Integration with Equity Research Workflows

This data feeds into:
1. Valuation analysis (DCF, comparable companies)
2. Financial health assessment
3. Growth trend analysis
4. Segment performance tracking
5. Analyst consensus comparison
6. Investment recommendation generation

## References

- FMP Documentation: https://financialmodelingprep.com/developer/docs/
- Alphabet Inc. Investor Relations: https://abc.xyz/investor/
- SEC EDGAR: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1652044&type=10-K&dateb=&owner=exclude&count=100
