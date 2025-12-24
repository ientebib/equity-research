# API References

## Data Providers

### Financial Modeling Prep (FMP)
- **Docs**: https://site.financialmodelingprep.com/developer/docs
- **Free tier**: Yes
- **Used for**: Earnings call transcripts, financial data

### Finnhub
- **Docs**: https://finnhub.io/docs/api
- **Free tier**: Yes
- **Used for**: Earnings call transcripts (fallback)

### SEC EDGAR
- **Docs**: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- **Free**: Yes (public data)
- **Used for**: 10-K, 10-Q, 8-K filings, company facts, XBRL data
- **Rate limit**: 10 requests/second
- **Requires**: User-Agent with email identification

### yfinance
- **Docs**: https://github.com/ranaroussi/yfinance
- **Free**: Yes (Yahoo Finance data)
- **Used for**: Stock quotes, historical prices, market data

## LLM Providers

### OpenAI
- **Docs**: https://platform.openai.com/docs
- **Models used**:
  - `gpt-5.2-2025-12-11` (workhorse, with reasoning.effort parameter)

### Anthropic
- **Docs**: https://docs.anthropic.com/
- **Models used**:
  - `claude-opus-4-5-20251101` (judge)
  - `claude-sonnet-4-5-20250929` (synthesis)

### Google Gemini
- **Docs**: https://ai.google.dev/gemini-api/docs
- **Models used**:
  - `gemini-3-pro` (research)
