# Token Flow Architecture

This document describes what context (tokens) flows to each agent in the equity research pipeline.

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Data Collection (No LLM)                                               │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ FMP API → CompanyContext (~6K tokens)                                       │ │
│ │   • profile: ~500 tokens                                                    │ │
│ │   • income_statement_quarterly (4Q): ~1,250 tokens                          │ │
│ │   • income_statement_annual (3Y): ~950 tokens                               │ │
│ │   • balance_sheet_annual (3Y): ~1,460 tokens                                │ │
│ │   • cash_flow_annual (3Y): ~1,200 tokens                                    │ │
│ │   • news (7 articles): ~520 tokens                                          │ │
│ │   • key_metrics: ~300 tokens                                                │ │
│ │   • quant_metrics (computed): ~200 tokens                                   │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Discovery (PARALLEL)                                                   │
│ ┌─────────────────────────────┐ ┌─────────────────────────────────────────────┐ │
│ │ Internal Discovery          │ │ External Discovery                          │ │
│ │ (GPT-5.2 + Web Search)      │ │ (Claude Sonnet + Web Search)                │ │
│ │                             │ │                                             │ │
│ │ INPUT:                      │ │ INPUT:                                      │ │
│ │ • Prompt template: ~2K      │ │ • Prompt template: ~2K                      │ │
│ │ • CompanyContext: ~6K       │ │ • CompanyContext: ~6K                       │ │
│ │ • Web search results: ???   │ │ • Web search results: ~620K (!!!)           │ │
│ │   (OpenAI internal)         │ │   (Claude fetches full pages)               │ │
│ │                             │ │                                             │ │
│ │ OUTPUT: ~3K tokens          │ │ OUTPUT: ~5K tokens                          │ │
│ │ • research_threads[]        │ │ • research_threads[]                        │ │
│ │ • research_groups[]         │ │ • research_groups[]                         │ │
│ │ • cross_cutting_themes[]    │ │ • cross_cutting_themes[]                    │ │
│ └─────────────────────────────┘ └─────────────────────────────────────────────┘ │
│                              │                                                  │
│                              ▼                                                  │
│                     ┌─────────────────┐                                         │
│                     │ Discovery Merger│ (No LLM - code merge)                   │
│                     └─────────────────┘                                         │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Deep Research (PARALLEL - 2 Groups × N Verticals)                      │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ Group A: Verticals 1, 3, 5, ... │ Group B: Verticals 2, 4, 6, ...           │ │
│ │ ┌─────────────────────────────┐ │ ┌─────────────────────────────────────────┐│ │
│ │ │ Vertical Analyst (Gemini)   │ │ │ Vertical Analyst (Gemini)               ││ │
│ │ │                             │ │ │                                         ││ │
│ │ │ INPUT:                      │ │ │ INPUT:                                  ││ │
│ │ │ • Prompt template: ~3K      │ │ │ • Prompt template: ~3K                  ││ │
│ │ │ • CompanyContext: ~6K       │ │ │ • CompanyContext: ~6K                   ││ │
│ │ │ • Thread definition: ~200   │ │ │ • Thread definition: ~200               ││ │
│ │ │ • Other threads list: ~500  │ │ │ • Other threads list: ~500              ││ │
│ │ │ • (Deep Research may add    │ │ │ • (Deep Research may add                ││ │
│ │ │   web search content)       │ │ │   web search content)                   ││ │
│ │ │                             │ │ │                                         ││ │
│ │ │ OUTPUT: ~8K tokens          │ │ │ OUTPUT: ~8K tokens                      ││ │
│ │ │ • VerticalAnalysis          │ │ │ • VerticalAnalysis                      ││ │
│ │ └─────────────────────────────┘ │ └─────────────────────────────────────────┘│ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: Dual Synthesis (PARALLEL)                                              │
│ ┌─────────────────────────────────┐ ┌───────────────────────────────────────────┐│
│ │ Claude Synthesis                │ │ GPT Synthesis                             ││
│ │ (Claude Opus + Extended Think)  │ │ (GPT-5.2 + Web Search)                    ││
│ │                                 │ │                                           ││
│ │ INPUT:                          │ │ INPUT:                                    ││
│ │ • Prompt template: ~5K          │ │ • Prompt template: ~5K                    ││
│ │ • CompanyContext: ~6K           │ │ • CompanyContext: ~6K                     ││
│ │ • Discovery output: ~5K         │ │ • Discovery output: ~5K                   ││
│ │ • ALL vertical analyses:        │ │ • ALL vertical analyses:                  ││
│ │   N × ~8K = ~40-80K             │ │   N × ~8K = ~40-80K                       ││
│ │                                 │ │                                           ││
│ │ TOTAL INPUT: ~55-95K            │ │ TOTAL INPUT: ~55-95K + web                ││
│ │                                 │ │                                           ││
│ │ OUTPUT: ~20K tokens             │ │ OUTPUT: ~20K tokens                       ││
│ │ • Full equity report            │ │ • Full equity report                      ││
│ └─────────────────────────────────┘ └───────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: Editorial Review (SINGLE)                                              │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ Judge Agent (Claude Opus + Extended Thinking)                               │ │
│ │                                                                             │ │
│ │ INPUT:                                                                      │ │
│ │ • Prompt template: ~3K                                                      │ │
│ │ • Claude synthesis report: ~20K                                             │ │
│ │ • GPT synthesis report: ~20K                                                │ │
│ │ • Discovery output: ~5K                                                     │ │
│ │ • Key metrics (minimal context): ~1K                                        │ │
│ │                                                                             │ │
│ │ TOTAL INPUT: ~50K                                                           │ │
│ │                                                                             │ │
│ │ OUTPUT: ~8K tokens                                                          │ │
│ │ • preferred_synthesis: "claude" | "gpt" | "reject_both"                     │ │
│ │ • scores and feedback                                                       │ │
│ │ • revision_instructions                                                     │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: Revision (SINGLE)                                                      │
│ ┌─────────────────────────────────────────────────────────────────────────────┐ │
│ │ Winning Synthesizer (Claude or GPT + Extended Thinking)                     │ │
│ │                                                                             │ │
│ │ INPUT:                                                                      │ │
│ │ • Original winning report: ~20K                                             │ │
│ │ • Editorial feedback: ~8K                                                   │ │
│ │ • Other report (for incorporating insights): ~20K                           │ │
│ │ • Revision prompt: ~2K                                                      │ │
│ │                                                                             │ │
│ │ TOTAL INPUT: ~50K                                                           │ │
│ │                                                                             │ │
│ │ OUTPUT: ~25K tokens                                                         │ │
│ │ • Final revised report                                                      │ │
│ └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Token Cost Analysis

### CRITICAL FINDING: Web Search Token Explosion

The external discovery agent (Claude Sonnet with web search) consumed **~620K tokens** for a single company because Claude fetches and reads **full web page content** for each search result.

| Component | Tokens | % of Total |
|-----------|--------|------------|
| FMP Company Context | ~6K | 1% |
| Web Search Results (Claude) | ~620K | **99%** |
| **Total External Discovery Input** | **626K** | 100% |

This was a **100x cost multiplier** vs. just using FMP data!

### Root Cause Analysis

**Anthropic Claude Web Search (`web_search_20250305`):**
- Returns **encrypted full page content** for each search result (not snippets)
- Uses Brave Search as the underlying provider
- Each search returns multiple results × ~6K tokens per page = ~60K tokens per search
- 10 searches × ~60K = ~600K tokens
- Pricing: $10/1000 searches + standard token costs for all content

**OpenAI GPT Web Search (Responses API):**
- Uses `{"type": "web_search"}` tool
- For mini models: Fixed 8,000 tokens per search call
- For GPT-5.2: Variable, but significantly less than Claude
- Actual measured: ~82K tokens for internal discovery (vs Claude's 652K)

### ✅ FIX IMPLEMENTED: Domain Filtering

Added `allowed_domains` parameter to restrict Claude web searches to high-quality financial news sources:

```python
# src/er/agents/external_discovery.py
allowed_domains = [
    # Tier 1: Premium financial news
    "bloomberg.com", "reuters.com", "wsj.com", "ft.com", "cnbc.com",
    # Tier 1: Tech news
    "theverge.com", "arstechnica.com", "techcrunch.com", "theinformation.com",
    # Tier 2: Market analysis
    "seekingalpha.com", "fool.com", "marketwatch.com", "finance.yahoo.com",
    # Company sources
    "sec.gov", "prnewswire.com", "businesswire.com",
]
```

**Expected Impact:**
- Reduces junk content from SEO spam sites and content farms
- Pages from quality sources tend to be cleaner and shorter
- Estimated 30-50% token reduction while maintaining research quality

### Estimated Total Pipeline Cost

For a full pipeline run with 5 verticals:

| Stage | Agent(s) | Input Tokens | Output Tokens | Est. Cost |
|-------|----------|--------------|---------------|-----------|
| 1 | Data Orchestrator | 0 (API calls) | N/A | $0 (FMP API) |
| 2 | Internal Discovery (GPT-5.2) | ~80K | ~14K | ~$0.35 |
| 2 | External Discovery (Claude) | ~400K* | ~5K | **~$1.30*** |
| 3 | Vertical Analysts (5x Gemini) | 5 × ~10K | 5 × ~8K | ~$0.30 |
| 4 | Claude Synthesis | ~80K | ~20K | ~$0.60 |
| 4 | GPT Synthesis | ~80K | ~20K | ~$0.50 |
| 5 | Judge (Claude Opus) | ~50K | ~8K | ~$0.35 |
| 6 | Revision (Claude/GPT) | ~50K | ~25K | ~$0.40 |
| **TOTAL** | | | | **~$3.80*** |

*With domain filtering enabled (estimated 35% reduction)

### API Comparison: Claude vs OpenAI Web Search

| Feature | Claude (`web_search_20250305`) | OpenAI (Responses API) |
|---------|-------------------------------|------------------------|
| Content returned | Full page (encrypted) | Summarized/processed |
| Domain filtering | ✅ `allowed_domains` | ❌ Not available |
| Max searches | ✅ `max_uses` | ❌ No limit control |
| Tokens per search | ~60K (variable) | ~8K (fixed for mini) |
| Pricing | $10/1000 + tokens | $30/1000 + tokens |

## Cost Optimization Options

1. **✅ Domain Filtering (Implemented)**: Restricts to quality sources, ~35% token reduction
2. **Reduce `max_uses`**: Lower from 10 to 5 searches (trades coverage for cost)
3. **Disable External Discovery**: Use `--no-external-discovery` (saves ~$1.30/run)
4. **Transcript Extraction Agent**: Pre-extract key quotes instead of full transcripts
5. **Stage-Specific Context Views**: Send minimal context per stage (WS2 in plan)

## Running Token Analysis

```bash
# Analyze a completed run
python scripts/analyze_context.py test_output/run_XXXXX

# View token flow dashboard
python -m er.observability.token_flow test_output/run_XXXXX
```
