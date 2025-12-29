# Equity Research Pipeline Strategy

## Core Philosophy

The pipeline is built on three pillars that must ALL be strong for quality output:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REASONING (Pillar 3)                        │
│   Synthesize complete, accurate information into investment thesis  │
│                                                                     │
│   - Only as good as the data it receives                           │
│   - This is where LLMs excel - deep reasoning over known facts     │
│   - Currently: Claude Opus + GPT-5.2 dual synthesis                │
└─────────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
┌───────────────────▼───────────────┐ ┌────────▼────────────────────────┐
│     COMPANY DATA (Pillar 1)       │ │    WORLD CONTEXT (Pillar 2)     │
│                                   │ │                                  │
│ What the company says about       │ │ What's happening externally      │
│ itself + verifiable financials    │ │ that affects the company         │
│                                   │ │                                  │
│ Sources:                          │ │ Sources:                         │
│ - FMP API (financials, metrics)   │ │ - News (company + industry)      │
│ - Earnings transcripts            │ │ - Competitor announcements       │
│ - SEC filings                     │ │ - Analyst ratings/debates        │
│ - Company press releases          │ │ - Market discourse (what people  │
│                                   │ │   are talking about)             │
│ Status: STRONG ✅                  │ │                                  │
│ - FMP data is comprehensive       │ │ Status: WEAK ❌                   │
│ - Transcripts provide mgmt view   │ │ - Web search is ad-hoc           │
│ - Structured, machine-readable    │ │ - No systematic competitor scan  │
│                                   │ │ - Missing market discourse       │
└───────────────────────────────────┘ └──────────────────────────────────┘
```

## Current Problem

The Discovery agent uses web search but doesn't systematically capture:

1. **Competitor developments** - What did Microsoft/OpenAI/Amazon announce recently?
2. **Market discourse** - What are people debating? (ChatGPT vs Gemini, AI safety, etc.)
3. **Analyst framing** - How is Wall Street thinking about this stock?
4. **Industry news** - Regulatory changes, market shifts, new entrants

Without complete Pillar 2, Pillar 3 (reasoning) operates on incomplete data.

**Example failure:** The GOOGL report didn't adequately discuss:
- Google selling TPUs externally (business model shift)
- ChatGPT/OpenAI competitive dynamics
- DeepMind breakthroughs
- Gemini 3.0 (released but not mentioned)

These are Pillar 2 failures - the information wasn't surfaced, so reasoning couldn't incorporate it.

---

## Key Framework: Variant Perception (Michael Steinhardt)

From the GOAT hedge fund managers, the most actionable insight:

> "Holding a well-founded view that was meaningfully different from market consensus."

**Steinhardt's 2-minute test:**
1. The idea
2. The consensus view
3. Your variant perception (what the market is missing)
4. A trigger event

**Application:** Discovery should not just find value drivers - it should map each one against consensus and identify where the market might be wrong.

---

## Improvement Options

### Option A: Strengthen Pillar 2 with Dedicated News/Competitive Agent

Add a **Stage 1.5: Competitive Intelligence** that runs BEFORE Discovery:

```
Inputs:
- Ticker
- List of known competitors (from FMP or hardcoded)

Tasks:
1. Search for each competitor's recent announcements (last 90 days)
2. Search for industry news affecting all players
3. Search for "vs" comparisons ({ticker} vs {competitor})
4. Search for analyst debates and rating changes
5. Search for market discourse topics (Twitter/Reddit sentiment, viral discussions)

Outputs:
- competitor_developments: [{company, announcement, date, implication}]
- industry_news: [{headline, date, affected_companies}]
- analyst_debates: [{topic, bull_view, bear_view}]
- market_discourse: [{topic, sentiment, volume}]
```

Discovery then receives this as additional context alongside FMP data.

### Option B: Add Variant Perception Lens to Discovery

Keep current structure but add **Lens 8: Variant Perception**:

```
For EACH research vertical identified:
1. What does Wall Street consensus believe?
2. What does YOUR analysis suggest that differs?
3. What event would prove consensus wrong?

Required searches:
- "{ticker} analyst consensus view 2025"
- "{ticker} vs {competitor} debate"
- "{ticker} what is the market missing"
```

### Option C: Two Parallel Discovery Agents

Run two agents simultaneously:
1. **Internal Discovery** - Focus on company data (Pillar 1)
2. **External Discovery** - Focus on competitive/news (Pillar 2)

Then merge outputs before Deep Research.

### Option D: Add Business Model Evolution Lens

Explicitly ask:
- What was internal-only that is now sold externally?
- What new industry does this company now compete in?
- What changed in the last 12 months?

---

## Recommended Path Forward

**Phase 1: Quick Win**
- Add Lens 8 (Variant Perception) to existing Discovery prompt
- Test on GOOGL to see if it surfaces TPU insight

**Phase 2: Systematic Competitive Intel**
- Build dedicated Competitive Intelligence agent (Stage 1.5)
- Run before Discovery to provide structured Pillar 2 data

**Phase 3: Dual Discovery**
- If needed, split Discovery into Internal/External agents
- Merge outputs with lightweight synthesizer

---

## Test Harness Requirements

To iterate on Discovery prompts quickly:

```python
# scripts/test_discovery.py
async def test_discovery(
    ticker: str,
    prompt_variant: str,  # "v1", "v2", etc.
    expected_insights: list[str],  # Things it SHOULD find
):
    """Run Discovery in isolation and score output."""

    # Load company context from saved checkpoint
    # Run Discovery with specified prompt
    # Check if expected_insights are in output
    # Return score + full output for manual review
```

Expected insights for GOOGL:
- [ ] TPU external sales (business model shift)
- [ ] Gemini 3.0 release
- [ ] ChatGPT/OpenAI competitive pressure
- [ ] DeepMind breakthroughs (AlphaFold, etc.)
- [ ] Cloud capacity constraints
- [ ] Regulatory remedies (DOJ)

---

## Architecture Principles

1. **Garbage in, garbage out** - Reasoning quality depends on data completeness
2. **Explicit > implicit** - Force the agent to search for specific things rather than hoping it finds them
3. **Variant perception** - Don't just find facts, find where facts differ from consensus
4. **Testable** - Each improvement should be testable in isolation before full pipeline run
5. **Universal** - Improvements should work for any company, not just complex ones like Google

---

## Cost Considerations

Current full pipeline cost (GOOGL): ~$5-15 depending on stages cached

Adding Competitive Intelligence agent: +$1-3 (GPT-5.2 with web search)
Adding Variant Perception lens: +$0 (same prompt, more structured output)
Dual Discovery agents: +$2-5 (doubles Discovery cost)

For research quality, the marginal cost is worth it.

---

## Target Architecture: Dual Discovery

```
                    ┌─────────────────────────────────────┐
                    │         Stage 1: Data Orchestrator   │
                    │              (FMP + Transcripts)     │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
              ┌───────────────────────┴───────────────────────┐
              │              RUN IN PARALLEL                  │
              ▼                                               ▼
┌─────────────────────────────┐             ┌─────────────────────────────┐
│  Stage 2A: Internal Discovery│             │  Stage 2B: External Discovery│
│                             │             │                             │
│  Focus: PILLAR 1            │             │  Focus: PILLAR 2            │
│  - Official segments        │             │  - Competitor announcements │
│  - Management emphasis      │             │  - Industry news (90 days)  │
│  - Asset inventory          │             │  - Analyst debates/ratings  │
│  - Financial trends         │             │  - Market discourse         │
│  - Business model analysis  │             │  - "What's everyone talking │
│                             │             │    about?" (ChatGPT, etc.)  │
│  Input: CompanyContext      │             │  - Product launches         │
│  Model: GPT-5.2 + reasoning │             │  - Regulatory developments  │
│                             │             │                             │
│                             │             │  Input: Ticker + competitors│
│                             │             │  Model: GPT-5.2 + web search│
└─────────────┬───────────────┘             └─────────────┬───────────────┘
              │                                           │
              └───────────────────┬───────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────────────┐
                    │     Stage 2C: Discovery Merger      │
                    │                                     │
                    │  Tasks:                             │
                    │  1. Combine internal + external     │
                    │  2. Identify VARIANT PERCEPTIONS    │
                    │     (where internal vs external     │
                    │      suggest different conclusions) │
                    │  3. Prioritize research threads     │
                    │  4. Assign threads to N groups      │
                    │                                     │
                    │  Model: Lightweight (Haiku/GPT-4o)  │
                    │  Cost: ~$0.10-0.30                  │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │   Stage 3: Deep Research (N agents) │
                    │                                     │
                    │   N = 2-4 based on thread count     │
                    │   Each agent gets:                  │
                    │   - Assigned threads                │
                    │   - Relevant internal findings      │
                    │   - Relevant external context       │
                    │   - Specific research questions     │
                    │                                     │
                    │   Model: Gemini 2.5 Deep Research   │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │   Stage 4: Dual Synthesis           │
                    │   (Claude Opus + GPT-5.2 parallel)  │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │   Stage 5: Editorial Judge          │
                    │   (Pick winner + incorporate loser) │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │   Stage 6: Final Revision           │
                    └─────────────────────────────────────┘
```

### Why Dual Discovery?

1. **Parallel execution** - Internal and External don't depend on each other
2. **Specialization** - Each agent optimized for its data type
3. **Complete Pillar 2** - External Discovery ONLY does competitive/news, so it's thorough
4. **Variant Perception built-in** - Merger identifies where internal vs external conflict

### External Discovery Prompt Sketch

```
You are the External Discovery Agent. Your job is to find EVERYTHING
happening OUTSIDE this company that affects its investment thesis.

TODAY: {date}
TICKER: {ticker}
KNOWN COMPETITORS: {competitors}

## MANDATORY SEARCHES

### 1. Competitor Scan (last 90 days)
For EACH competitor, search:
- "{competitor} announcement {current_month} {current_year}"
- "{competitor} product launch 2025"
- "{competitor} vs {ticker}"

### 2. Industry News
- "{industry} news {current_month} {current_year}"
- "{ticker} regulatory {current_year}"
- "{industry} market share 2025"

### 3. Market Discourse
- "{ticker} reddit twitter sentiment"
- "{ticker} what is everyone talking about"
- "AI {industry} debate 2025" (if applicable)

### 4. Analyst Sentiment
- "{ticker} analyst upgrade downgrade {current_month}"
- "{ticker} price target change 2025"
- "{ticker} bull bear debate"

## OUTPUT FORMAT

{
  "competitor_developments": [
    {"company": "...", "event": "...", "date": "...", "implication_for_ticker": "..."}
  ],
  "industry_news": [
    {"headline": "...", "date": "...", "affected_companies": [...], "implication": "..."}
  ],
  "market_discourse": [
    {"topic": "...", "sentiment": "bullish|bearish|mixed", "why_it_matters": "..."}
  ],
  "analyst_sentiment": {
    "consensus": "...",
    "recent_changes": [...],
    "key_debates": [...]
  },
  "things_people_are_talking_about": [
    "ChatGPT feature X launched",
    "DeepMind announced Y",
    ...
  ]
}
```

### Context Management for Synthesizer

With more upstream agents, we need to control what reaches synthesis:

| Stage | Output Size | What Goes Forward |
|-------|-------------|-------------------|
| 2A Internal | ~5-10K tokens | Full structured output |
| 2B External | ~5-10K tokens | Full structured output |
| 2C Merger | ~3-5K tokens | Prioritized threads + variant perceptions |
| 3 Deep Research | ~20-50K tokens per agent | SUMMARIZED per thread (~2K each) |

**Key rule:** Deep Research outputs get summarized before synthesis. The synthesizer doesn't need 50K tokens of raw research - it needs the conclusions with key evidence.

---

## Implementation Plan

### Phase 1: External Discovery Agent (NEW)
- [ ] Create `src/er/agents/external_discovery.py`
- [ ] Prompt focused on Pillar 2 (competitors, news, discourse)
- [ ] Test in isolation on GOOGL
- [ ] Verify it finds: ChatGPT, DeepMind, TPU external sales, Gemini 3.0

### Phase 2: Internal Discovery Refactor
- [ ] Rename current `discovery.py` to `internal_discovery.py`
- [ ] Remove external-focused lenses (they're now in External)
- [ ] Keep: Official segments, Management emphasis, Asset inventory, Financials

### Phase 3: Discovery Merger
- [ ] Create `src/er/agents/discovery_merger.py`
- [ ] Takes Internal + External outputs
- [ ] Identifies variant perceptions
- [ ] Outputs unified research threads with assigned groups

### Phase 4: Pipeline Integration
- [ ] Update `pipeline.py` to run 2A and 2B in parallel
- [ ] Feed merger output to Deep Research
- [ ] Test full pipeline on GOOGL
- [ ] Compare to baseline

### Phase 5: Context Compression
- [ ] Add summarization step after Deep Research
- [ ] Each thread → 2K token summary with key evidence
- [ ] Synthesizer receives compressed, high-signal input

---

## Next Steps

1. [ ] Create test harness for Discovery in isolation
2. [ ] Build External Discovery agent (Stage 2B)
3. [ ] Test External Discovery on GOOGL - does it find ChatGPT/DeepMind/TPUs?
4. [ ] Build Discovery Merger (Stage 2C)
5. [ ] Integrate into pipeline
6. [ ] Run full pipeline with dual discovery
7. [ ] Compare output quality to baseline
