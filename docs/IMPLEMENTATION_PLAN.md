# Implementation Plan: Anthropic Multi-Agent Research Pipeline

> Based on Anthropic's "Built with Claude: How we built our multi-agent research system"

## Current State (Jan 14, 2026)

**Working:**
- Stage 1: FMPClient fetches real financial data (no hallucination)
- Evidence Store: SQLite + blob storage with `ev_xxx` IDs
- Phase 1 Complete: `AnthropicDiscoveryAgent` wired into pipeline

**Decision: Refactor to Claude Agent SDK**
- Use SDK consistently for all agents (not direct Anthropic API)
- SDK provides WebSearch, structured output, subagents
- Simpler architecture, better maintainability

**Key Insight from Discussion:**
- Discovery receives CompanyContext (fresh data from FMP)
- Discovery should ANALYZE CompanyContext + USE WEB SEARCH to fill gaps
- Web search is for: competitor info, analyst sentiment, recent news NOT in CompanyContext
- Also for: "I saw X in transcript, let me search if this is new/interesting"
- Output needs traceability: what came from CompanyContext vs web search

---

## Redesigned 7-Lens Framework

**Problem with old order:** Lens 2 (Competitors) was second, but you need to understand the company first.

**New order - logical flow:**

| # | Lens | Source | Purpose |
|---|------|--------|---------|
| 1 | **Official Segments** | CompanyContext | What does the company say it does? Extract from 10-K segments |
| 2 | **Financial Performance** | CompanyContext | How are segments performing? Revenue, growth, margins |
| 3 | **Management Emphasis** | CompanyContext (transcripts) | What is CEO prioritizing? What got deflected? |
| 4 | **Recent Developments** | CompanyContext + WEB SEARCH | News, M&A, partnerships. Search for: "things mentioned in transcript that need verification" |
| 5 | **Analyst Sentiment** | WEB SEARCH (required) | What's the Street saying? Bull/bear debate, price targets |
| 6 | **Competitive Position** | WEB SEARCH (required) | How do competitors value similar assets? What are they emphasizing? |
| 7 | **Hidden Value / Blind Spots** | Synthesis | What might the market be missing? Cross-reference all lenses |

**Key principles:**
- Lenses 1-3: Analyze CompanyContext (no search needed)
- Lens 4: CompanyContext + search to verify/expand
- Lenses 5-6: MANDATORY web search (not in CompanyContext)
- Lens 7: Synthesis (no search, just thinking)

**Output per thread must include:**
```json
{
  "name": "Google Cloud",
  "type": "SEGMENT",
  "priority": 1,
  "hypothesis": "Cloud margins accelerating faster than Street expects",
  "grounded_in": {
    "from_company_context": "Q4 margin 11.2% vs Q3 9.4% (earnings data)",
    "from_transcript": "CFO mentioned 'operating leverage' 4 times",
    "from_web_search": {
      "query": "Google Cloud margin analyst expectations 2026",
      "finding": "Street consensus 12% by Q4 2026, trend suggests 15%+",
      "source_date": "2026-01-10"
    }
  },
  "questions_for_deep_research": ["What's driving margin improvement?", "Sustainable?"]
}
```

---

## Architecture Target

```
User Query: "Analyze GOOGL"
        │
        ▼
┌─────────────────────────────────────┐
│  STAGE 1: Data Collection (Python)  │
│  FMPClient.get_full_context()       │
│  Output: JSON + evidence IDs        │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  STAGE 2: Discovery (Sonnet)        │
│  7-lens framework + web search      │
│  Output: 5-8 research threads       │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  STAGE 3: Deep Research             │
│  Lead Orchestrator (Opus 4.5)       │
│           │                         │
│     ┌─────┼─────┐                   │
│     ▼     ▼     ▼                   │
│   [S1]  [S2]  [S3]  Sonnet subagents│
│     │     │     │   (parallel)      │
│     ▼     ▼     ▼                   │
│   Write findings to filesystem      │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  STAGE 4: Verification (Sonnet)     │
│  Citation check + logic check       │
│  Output: Verified facts             │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  STAGE 5: Synthesis (Opus 4.5)      │
│  Extended thinking (15K budget)     │
│  Output: Final research report      │
└─────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Wire Discovery Agent ✅ DONE
**Completed**: `AnthropicDiscoveryAgent` wired into pipeline

---

### Phase 1.5: Refactor to Opus Orchestrator Architecture (CURRENT)

**Key Insight**: BOTH Discovery and Deep Research use Opus 4.5 as orchestrator with Sonnet subagents. But they have VERY different profiles:

## Stage 2: Discovery (LEAN)
```
Opus 4.5 Orchestrator
    │
    ├── Sonnet: Analyst sentiment search (5 tool calls max)
    ├── Sonnet: Competitor search (5 tool calls max)
    └── Sonnet: Recent news verification (5 tool calls max)
```
- **Goal**: Quick grounding, identify threads
- **Token budget**: ~50K total
- **Subagents**: 2-3 max, limited tool calls
- **Time**: 1-2 minutes
- **Output**: 5-8 research threads with `grounded_in` evidence

## Stage 3: Deep Research (HEAVY)
```
Opus 4.5 Orchestrator
    │
    ├── Sonnet: Cloud segment (15-25 tool calls)
    ├── Sonnet: YouTube segment (15-25 tool calls)
    ├── Sonnet: AI/Other segment (15-25 tool calls)
    └── ... (one per thread)
```
- **Goal**: Full investigation per thread
- **Token budget**: ~250K total
- **Subagents**: 5-8, extensive tool calls
- **Time**: 5-10 minutes
- **Output**: Detailed findings with citations

## Implementation

**Discovery Orchestrator** (`src/er/agents/discovery_orchestrator.py`): CREATED
- Opus 4.5 analyzes CompanyContext (Lenses 1-3, 7)
- Spawns 3 Sonnet subagents in parallel:
  - `analyst_sentiment` - Lens 5 (analyst ratings, bull/bear cases)
  - `competitor_position` - Lens 6 (competitive dynamics, valuations)
  - `recent_developments` - Lens 4 (news, announcements)
- Each subagent: max 5 web searches via `web_search_20250305`
- Opus synthesizes subagent findings into 5-8 threads

**Simple Discovery** (`src/er/agents/discovery_sdk.py`): CREATED
- Single Sonnet agent (no orchestrator)
- Good for quick tests, lower cost
- Same 7-lens framework, same output format

**DR Orchestrator** (`src/er/agents/dr_orchestrator.py`):
- Opus receives threads, plans research strategy
- Spawns Sonnet subagent per thread/group
- Each subagent: 15-25 tool calls, full investigation
- Opus synthesizes into findings

**Output format (Discovery)**:
```json
{
  "threads": [
    {
      "name": "Google Cloud",
      "type": "SEGMENT",
      "priority": 1,
      "hypothesis": "Cloud margins accelerating faster than Street expects",
      "grounded_in": {
        "from_company_context": "Q4 margin 11.2%",
        "from_transcript": "CFO: 'operating leverage'",
        "from_web_search": {"query": "...", "finding": "..."}
      },
      "questions": ["What's driving margin?", "Sustainable?"]
    }
  ],
  "data_gaps": ["No segment-level margins in 10-K"]
}
```

**IMPORTANT**: Discovery does NOT pre-reject threads. Include ALL interesting optionalities.
- Early-stage opportunities (like autonomous vehicles) can be huge value drivers
- Let Deep Research determine materiality, not Discovery
- Prioritize threads (1-8) but include everything worth investigating

---

### Phase 2: Lead Orchestrator for Deep Research
**Goal**: Opus 4.5 coordinates parallel Sonnet subagents

**File**: Create `src/er/coordinator/lead_orchestrator.py`

**Architecture** (from Anthropic):
```python
class LeadOrchestrator:
    """Opus 4.5 that spawns and coordinates Sonnet subagents."""

    def __init__(self, evidence_store: EvidenceStore):
        self.client = Anthropic()
        self.evidence_store = evidence_store
        self.memory = {}  # Persist plan in case of context overflow

    async def research(self, threads: list[DiscoveredThread], context: dict) -> list[VerticalAnalysis]:
        # 1. Plan research strategy (save to memory)
        plan = await self._create_plan(threads)
        self.memory["plan"] = plan

        # 2. Spawn subagents in parallel
        tasks = []
        for group in plan["groups"]:
            task = self._spawn_subagent(group, context)
            tasks.append(task)

        # 3. Gather results (parallel execution)
        results = await asyncio.gather(*tasks)

        # 4. Synthesize if needed, or return
        return results

    async def _spawn_subagent(self, group: dict, context: dict) -> VerticalAnalysis:
        """Spawn a Sonnet subagent with isolated context."""
        # Load prompt from docs/prompts/deep_research.md
        prompt = load_prompt("deep_research.md").format(
            group_name=group["name"],
            verticals_detail=group["verticals"],
            ...
        )

        # Call Sonnet with web search tool
        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=16000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )

        # Write findings to filesystem (not through lead agent)
        output_path = self.output_dir / f"subagent_{group['id']}.json"
        output_path.write_text(json.dumps(findings))

        return VerticalAnalysis(...)
```

**Key principles from Anthropic**:
- Subagents write to filesystem, pass references back (not full content)
- Each subagent gets isolated 200K context
- Use `asyncio.gather()` for true parallelism
- Lead agent saves plan to memory before potential context overflow

---

### Phase 3: Subagent Implementation
**Goal**: Sonnet subagents that do deep research with web search

**File**: Create `src/er/agents/research_subagent.py`

**Features**:
1. Load prompt from `docs/prompts/deep_research.md`
2. Use `web_search_20250305` tool for competitive/market context
3. Use interleaved thinking to evaluate tool results
4. Write output to filesystem, return reference
5. Track searches performed for audit

**Scaling heuristics** (from Anthropic):
| Query Complexity | Subagents | Tool Calls Each |
|------------------|-----------|-----------------|
| Simple fact-finding | 1 | 3-10 |
| Direct comparison | 2-4 | 10-15 |
| Complex research | 5-10+ | 15-25 |

---

### Phase 4: Verification Stage
**Goal**: Validate facts before synthesis

**File**: Create `src/er/agents/verifier.py`

**Three checks**:
1. **Citation Check**: Does `ev_xxx` ID exist? Does it support the claim?
2. **Logic Check**: Do conclusions follow from evidence?
3. **Cross-Reference**: Are claims consistent across subagents?

**Output**: `VerifiedResearchPackage` with confidence-adjusted facts

---

### Phase 5: Synthesis with Extended Thinking
**Goal**: Opus 4.5 synthesizes all research into final report

**File**: Update `src/er/agents/synthesizer.py`

**Implementation**:
```python
response = client.messages.create(
    model="claude-opus-4-5-20251101",
    max_tokens=40000,  # budget + expected output
    thinking={
        "type": "enabled",
        "budget_tokens": 15000,
    },
    messages=[{"role": "user", "content": synthesis_prompt}],
)
```

**Key**: Extended thinking for complex cross-vertical synthesis

---

## File Structure After Implementation

```
src/er/
├── coordinator/
│   ├── anthropic_sdk_agent.py    # Main pipeline entry point
│   └── lead_orchestrator.py      # TODO: DR Opus orchestrator
├── agents/
│   ├── discovery_sdk.py          # Stage 2 (simple, single agent)
│   ├── discovery_orchestrator.py # Stage 2 (Opus + Sonnet subagents) - CREATED
│   ├── dr_orchestrator.py        # TODO: Stage 3 Deep Research
│   ├── verifier.py               # TODO: Citation/logic check
│   └── synthesizer.py            # Stage 5 (existing, update)
├── data/
│   └── fmp_client.py             # Stage 1 (working)
└── evidence/
    └── store.py                  # Evidence tracking (working)

docs/prompts/
├── discovery_system.md           # Stage 2 prompt (in discovery_sdk.py)
├── deep_research.md              # TODO: Stage 3 subagent prompt
├── synthesis.md                  # Stage 5 prompt
└── README.md                     # Variable reference
```

---

## Testing Strategy

### Unit Tests
- `test_discovery.py`: Mock FMP data → verify 5-8 threads
- `test_subagent.py`: Mock context → verify web search usage
- `test_verifier.py`: Known facts → verify citation check

### Integration Tests
- Stage 1+2: FMPClient → Discovery → JSON threads
- Stage 2+3: Threads → Lead Orchestrator → Subagent outputs
- Full pipeline: GOOGL end-to-end

### Eval Criteria (from Anthropic)
- Factual accuracy: Do claims match sources?
- Citation accuracy: Do cited sources match claims?
- Completeness: Are all threads covered?
- Source quality: Primary sources over SEO farms?
- Tool efficiency: Reasonable number of searches?

---

## Implementation Order

1. **Phase 1**: Wire discovery (1 file change)
2. **Phase 2**: Lead orchestrator (new file)
3. **Phase 3**: Research subagent (new file)
4. **Phase 4**: Verifier (new file)
5. **Phase 5**: Update synthesizer (1 file change)

Each phase is independently testable. Start with Phase 1.

---

## Cost Estimates

| Stage | Model | Est. Tokens | Est. Cost |
|-------|-------|-------------|-----------|
| Discovery | Sonnet | 50K in, 8K out | ~$0.20 |
| Deep Research (5 subagents) | Sonnet x5 | 250K in, 40K out | ~$1.00 |
| Verification | Sonnet | 100K in, 10K out | ~$0.40 |
| Synthesis | Opus + thinking | 150K in, 20K out | ~$3.00 |
| **Total per run** | | | **~$4.60** |

Multi-agent is ~15x more expensive than single chat, but delivers institutional-grade research.

---

## Next Action

Start with **Phase 1**: Wire `AnthropicDiscoveryAgent` into `anthropic_sdk_agent.py`.

```bash
# Test after Phase 1
python -c "
from er.coordinator.anthropic_sdk_agent import AnthropicAgentPipeline
import asyncio
pipeline = AnthropicAgentPipeline()
asyncio.run(pipeline.run('GOOGL'))
"
```
