---
name: financial-modeling
description: "Professional financial modeling for equity research including DCF valuation, trading comparables, LBO analysis, and M&A modeling. Use when building valuation models, projecting financials, or analyzing investment opportunities."
---

# Financial Modeling Skill

Expert knowledge for building institutional-quality financial models.

## DCF Valuation Framework

### Core Formula

```
Enterprise Value = Σ (FCF_t / (1 + WACC)^t) + Terminal Value / (1 + WACC)^n

Where:
- FCF = Free Cash Flow = EBIT(1-T) + D&A - CapEx - ΔNWC
- WACC = Weighted Average Cost of Capital
- Terminal Value = FCF_n+1 / (WACC - g) [Gordon Growth]
  OR = FCF_n × Exit Multiple [Exit Multiple Method]
```

### DCF Excel Model Structure

**Sheet 1: Assumptions**
| Cell | Label | Value | Notes |
|------|-------|-------|-------|
| B3 | Risk-Free Rate | 4.5% | 10-year Treasury |
| B4 | Equity Risk Premium | 5.5% | Historical average |
| B5 | Beta | 1.2 | Levered beta |
| B6 | Cost of Debt | 6.0% | Pre-tax |
| B7 | Tax Rate | 21% | Statutory |
| B8 | Debt/Capital | 20% | Target structure |
| B9 | Terminal Growth | 2.5% | GDP proxy |
| B10 | Exit Multiple | 12.0x | EV/EBITDA |

**Derived Calculations:**
```
Cost of Equity = Risk-Free + Beta × ERP
WACC = (E/V × Re) + (D/V × Rd × (1-T))
```

**Sheet 2: Income Statement Projections**
```
| Line Item          | Historical |  Yr1  |  Yr2  |  Yr3  |  Yr4  |  Yr5  |
|--------------------|------------|-------|-------|-------|-------|-------|
| Revenue            | =link      | =prev×(1+growth) |  ...  |
| % Growth           | calc       | input | input | input | input | input |
| Gross Profit       | =Rev×GM%   |  ...  |
| Gross Margin %     | calc       | input |
| Operating Expenses | =Rev×OpEx% |  ...  |
| EBIT               | =GP-OpEx   |  ...  |
| EBIT Margin %      | =EBIT/Rev  |  ...  |
```

**Sheet 3: Free Cash Flow Build**
```
| Line Item               | Formula                    |
|-------------------------|----------------------------|
| EBIT                    | =link to IS               |
| Less: Taxes             | =EBIT × Tax Rate          |
| NOPAT                   | =EBIT - Taxes             |
| Plus: D&A               | =link to CF               |
| Less: CapEx             | =Rev × CapEx%             |
| Less: Increase in NWC   | =ΔRev × NWC%              |
| Free Cash Flow          | =NOPAT + D&A - CapEx - ΔNWC |
```

**Sheet 4: DCF Valuation**
```
| Line Item               | Formula                    |
|-------------------------|----------------------------|
| FCF Year 1-5            | =link                      |
| Discount Factor         | =1/(1+WACC)^year          |
| PV of FCF               | =FCF × Discount Factor    |
| Sum of PV FCF           | =SUM(PV FCFs)             |
| Terminal Value          | =FCF5×(1+g)/(WACC-g)      |
| PV of Terminal Value    | =TV/(1+WACC)^5            |
| Enterprise Value        | =Sum PV FCF + PV TV       |
| Less: Net Debt          | =Total Debt - Cash        |
| Equity Value            | =EV - Net Debt            |
| Shares Outstanding      | =input                     |
| Implied Share Price     | =Equity Value / Shares    |
| Current Price           | =input                     |
| Upside / (Downside)     | =(Implied - Current)/Current |
```

**Sheet 5: Sensitivity Analysis**
- WACC vs Terminal Growth matrix
- Revenue Growth vs Margin matrix
- Show implied share prices

## WACC Calculation Detail

```python
def calculate_wacc(
    risk_free: float,      # 10-year Treasury
    beta: float,           # Levered beta
    erp: float,            # Equity risk premium (typically 5-6%)
    cost_of_debt: float,   # Pre-tax cost of debt
    tax_rate: float,       # Marginal tax rate
    debt_to_capital: float # D / (D+E)
) -> float:
    cost_of_equity = risk_free + beta * erp
    equity_weight = 1 - debt_to_capital
    debt_weight = debt_to_capital
    after_tax_debt = cost_of_debt * (1 - tax_rate)
    wacc = (equity_weight * cost_of_equity) + (debt_weight * after_tax_debt)
    return wacc
```

**Typical WACC ranges by sector:**
- Technology: 8-12%
- Consumer Staples: 6-8%
- Utilities: 5-7%
- Healthcare: 7-10%
- Financials: 8-11%

## Trading Comparables

### Metrics to Calculate

| Multiple | Formula | Use Case |
|----------|---------|----------|
| EV/Revenue | EV / LTM Revenue | Pre-profit companies |
| EV/EBITDA | EV / LTM EBITDA | Standard valuation |
| EV/EBIT | EV / LTM EBIT | When D&A varies |
| P/E | Price / EPS | Profitable companies |
| PEG | P/E / EPS Growth | Growth-adjusted |
| P/FCF | Price / FCF per share | Cash flow focused |
| P/B | Price / Book Value | Asset-heavy sectors |

### Comp Selection Criteria
1. Same industry/sector
2. Similar size (0.5x - 2x market cap)
3. Similar growth profile
4. Similar margins
5. Similar geographic mix
6. Similar capital structure

## Sum-of-the-Parts (SOTP)

For conglomerates or companies with distinct segments:

```
| Segment | Revenue | EBITDA | Multiple | EV |
|---------|---------|--------|----------|-----|
| Segment A | $10B | $2B | 12x | $24B |
| Segment B | $5B | $1B | 8x | $8B |
| Segment C | $3B | $0.5B | 15x | $7.5B |
| Corporate | - | ($0.2B) | 8x | ($1.6B) |
| Total EV | | | | $37.9B |
| Less: Net Debt | | | | ($5B) |
| Equity Value | | | | $32.9B |
```

## Key Ratios to Track

### Profitability
- Gross Margin = Gross Profit / Revenue
- Operating Margin = EBIT / Revenue
- Net Margin = Net Income / Revenue
- ROIC = NOPAT / Invested Capital
- ROE = Net Income / Shareholders' Equity

### Leverage
- Debt/Equity = Total Debt / Equity
- Debt/EBITDA = Total Debt / EBITDA
- Interest Coverage = EBIT / Interest Expense
- Net Debt/EBITDA = (Debt - Cash) / EBITDA

### Efficiency
- Asset Turnover = Revenue / Total Assets
- Inventory Days = (Inventory / COGS) × 365
- Receivable Days = (AR / Revenue) × 365
- Payable Days = (AP / COGS) × 365
- Cash Conversion Cycle = Inv Days + AR Days - AP Days

### Growth
- Revenue CAGR = (End/Start)^(1/years) - 1
- EPS CAGR
- FCF CAGR

## Excel Formula Patterns

### Year-over-Year Growth
```
=IF(B2=0, "", (C2-B2)/ABS(B2))
```

### CAGR
```
=IF(B2<=0, "", (E2/B2)^(1/3)-1)
```

### NPV of Cash Flows
```
=NPV(WACC, FCF_Year1:FCF_Year5) + PV_Terminal
```

### Terminal Value (Gordon Growth)
```
=FCF_Year5*(1+Terminal_Growth)/(WACC-Terminal_Growth)
```

### Terminal Value (Exit Multiple)
```
=EBITDA_Year5*Exit_Multiple
```

## Citation Requirements

For all valuation models:
1. Source all financial data (10-K, 10-Q, earnings releases)
2. Source comparable company data (CapIQ, Bloomberg, public filings)
3. Source beta from reliable provider (Bloomberg, Barra)
4. Source risk-free rate (Treasury.gov)
5. Document any adjustments to reported numbers
6. Date stamp all assumptions

Format: [Source] [Document] [Date] [Page/Section if applicable]

Example: "Revenue from GOOGL 10-K FY2024, p. 45"
