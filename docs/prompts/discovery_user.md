# Discovery Agent - User Prompt Template

> **Stage**: 2 - Discovery
> **Variables**: `{ticker}`, `{company_name}`, `{date}`, `{current_month}`, `{current_year}`, `{latest_quarter}`, `{quarter_context}`, `{company_context}`

---

## DISCOVERY TASK

Analyze {ticker} ({company_name}) using the 7-lens framework.

TODAY: {date}
LATEST QUARTER: {latest_quarter}

## COMPANY CONTEXT (ACTUAL REPORTED DATA from SEC filings via FMP API)

NOTE: This is REAL FILED financial data, NOT analyst estimates. Income statements, balance sheets,
and cash flows below are from official 10-Q/10-K SEC filings - treat these numbers as factual.

{company_context}

## QUARTERLY DATA CONTEXT

{quarter_context}

## 7 MANDATORY LENSES

Complete ALL 7 lenses. Each lens has specific outputs. If a lens produces nothing, state "No findings" with reasoning.

### LENS 1: Official Structure (from JSON above)
Extract segments from revenue_by_product. Note quarterly trends.

### LENS 2: Competitive Cross-Reference
Search for main competitors and what they're valued for. Does {ticker} have similar capabilities?
SUGGESTED SEARCHES:
- "{ticker} main competitors 2025"
- "[largest competitor] valuation thesis"

### LENS 3: Analyst Attention
Search for current analyst debates, ratings, bull/bear cases.
SUGGESTED SEARCHES:
- "{ticker} analyst rating upgrade downgrade {current_month} {current_year}"
- "{ticker} bull vs bear case 2025"

### LENS 4: Recent Deals & Developments (last 90 days)
Search for M&A, partnerships, product launches.
SUGGESTED SEARCHES:
- "{ticker} partnership deal {current_month} {current_year}"
- "{ticker} acquisition announcement 2025"

### LENS 5: Asset Inventory
Search for valuable assets not yet monetized as segments.
SUGGESTED SEARCHES:
- "{ticker} technology infrastructure assets"
- "{ticker} internal technology monetization"

### LENS 6: Management Emphasis (from transcripts in JSON)
What did CEO emphasize? What topics got deflected?

### LENS 7: Blind Spots Synthesis
What value driver might the market be missing? Cross-reference all lenses.

## HARD RULES

1. COMPLETE ALL 7 LENSES
2. USE WEB SEARCH LIBERALLY - there is no limit
3. AT LEAST ONE NON-OFFICIAL VERTICAL (from Lens 2, 4, 5, or 7)
4. SPECIFIC RESEARCH QUESTIONS - not vague
5. 5-8 VERTICALS MAX
6. TWO RESEARCH GROUPS - split by business model similarity

Output ONLY JSON.
