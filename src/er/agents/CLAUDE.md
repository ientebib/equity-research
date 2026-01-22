# Equity Research Pipeline - Architecture Documentation

> **Purpose**: Help future Claude Code instances understand what we're building.

## What We're Building

An **institutional-grade equity research pipeline** using the **Anthropic Multi-Agent Architecture**:
- **Lead Orchestrator (Opus 4.5)**: Coordinates research strategy
- **Sonnet Subagents**: Execute parallel research with isolated 200K context windows
- **Pure Python Data Fetching**: No AI hallucination for financial data

Based on Anthropic's published deep research architecture: https://www.anthropic.com/engineering/built-with-claude-deep-research

---

## Pipeline Stages

### Stage 1: Data Collection (IMPLEMENTED)
**File**: `src/er/coordinator/anthropic_sdk_agent.py` → `_stage_data()`

- **NO AI INVOLVED** - Pure Python
- Uses `FMPClient.get_full_context(ticker)` to fetch real financial data
- Data cached for 24 hours to avoid API limits
- Returns evidence IDs for citation tracking

```python
# This is correct - direct Python call, no Claude
full_context = await self._fmp_client.get_full_context(ticker)
```

**Why?** Claude will hallucinate financial data if asked to "fetch" it. We solved this by using Python directly.

---

### Stage 2: Discovery (IMPLEMENTED)
**File**: `src/er/agents/discovery_anthropic.py` → `AnthropicDiscoveryAgent`
**Wired in**: `src/er/coordinator/anthropic_sdk_agent.py` → `_stage_discovery()`

- Uses **7-Lens Framework** to identify research threads
- Has `web_search_20250305` tool for real-time information (up to 20 searches)
- Returns structured `DiscoveryOutput` with threads, groups, and evidence IDs

**7 Lenses**:
1. Official Structure (10-K segments)
2. Competitive Cross-Reference
3. Analyst Attention
4. Recent Developments (last 90 days)
5. Asset Inventory (hidden value)
6. Management Emphasis
7. Blind Spots (market-ignored factors)

**Output includes**:
- `research_threads`: 5-8 prioritized threads
- `research_groups`: Threads grouped by theme for parallel processing
- `official_segments`: Segments from 10-K
- `searches_performed`: Audit trail of web searches

---

### Stage 3: Deep Research (IMPLEMENTED - Jan 2026)
**File**: `src/er/coordinator/anthropic_sdk_agent.py` → `_stage_research()`

**Architecture**:
```
Lead Orchestrator (coordinates subagents)
    │
    ├── research-1 (Sonnet) - Thread 1 deep dive
    ├── research-2 (Sonnet) - Thread 2 deep dive
    └── research-N (Sonnet) - One per research thread
```

**Key Design Decision (Jan 2026)**:
Stage 3 BUILDS ON Discovery, it doesn't re-discover.

Discovery (Stage 2) does the WIDE scan:
- Identifies threads and hypotheses
- Gathers competitor analysis, analyst views, recent developments
- Identifies external threats
- Performs web searches (tracked in `searches_performed`)

Deep Research (Stage 3) does the DEEP dive:
- **Validates** Discovery's claims (are they accurate?)
- **Adds nuance** (what's the full story?)
- **Goes deeper** (what did Discovery miss?)
- **Challenges** (what's the counter-argument?)

Each subagent receives:
- Full company context (quarterly financials from JSON)
- Date grounding (TODAY IS, CURRENT MONTH, LATEST QUARTER)
- **DISCOVERY'S FINDINGS** for this thread (so they don't re-discover)
- **Threats** relevant to this thread
- **Searches** Discovery already performed

This is the "BUILD-ON-DISCOVERY" philosophy.

---

### Stage 4: Verification (TODO)
Three-layer verification:
1. **Citation Check**: Evidence IDs valid?
2. **Logic Check**: Conclusions follow from evidence?
3. **Cross-Reference**: Claims consistent across verticals?

---

### Stage 5: Synthesis (TODO)
**Prompt saved**: `docs/prompts/synthesis.md`

Combines all vertical reports into final equity research report.
Uses Opus 4.5 with **extended thinking** (15K budget).

---

## Key Files

| File | Purpose | Status |
|------|---------|--------|
| `src/er/coordinator/anthropic_sdk_agent.py` | Main pipeline orchestrator | Stage 1-2 done |
| `src/er/agents/discovery_anthropic.py` | 7-lens discovery agent | Integrated |
| `src/er/data/fmp_client.py` | Financial data API | Working |
| `src/er/evidence/store.py` | Evidence tracking | Working |
| `src/er/types.py` | Data models (CompanyContext, DiscoveryOutput) | Working |

---

## Prompts (Editable)

All prompts are in **`docs/prompts/`** - edit there, no code changes needed:

| File | Stage | Purpose |
|------|-------|---------|
| `discovery_system.md` | 2 | System prompt for 7-lens discovery |
| `discovery_user.md` | 2 | User prompt template with variables |
| `deep_research.md` | 3 | Deep research subagent prompt |
| `synthesis.md` | 5 | Final report synthesis prompt |
| `README.md` | - | Variable reference and usage guide |

**To modify agent behavior**: Edit the prompt files, re-run pipeline.

---

## Evidence System

All data has evidence IDs for citations:
- Format: `ev_<uuid7>`
- Storage: SQLite metadata + SHA-256 blob files
- Purpose: Every claim in the report traces back to source data

---

## Anti-Patterns to Avoid

1. **DON'T** ask Claude to "fetch" financial data → hallucinations
2. **DON'T** use generic prompts → use existing discovery_anthropic.py prompts
3. **DON'T** process all research in one context → subagents with isolated contexts
4. **DON'T** skip evidence tracking → every claim needs citation

---

## Implementation Progress

See **`docs/IMPLEMENTATION_PLAN.md`** for detailed plan.

| Phase | Task | Status |
|-------|------|--------|
| 1 | Wire `AnthropicDiscoveryAgent` into Stage 2 | DONE |
| 2 | Build Lead Orchestrator (Opus 4.5) | TODO |
| 3 | Build Research Subagents (Sonnet) | TODO |
| 4 | Implement Verification layer | TODO |
| 5 | Update Synthesis with extended thinking | TODO |

---

## Testing

```bash
# Run full pipeline (Stage 1 + 2 working)
PYTHONPATH=./src python3 -m er.coordinator.anthropic_sdk_agent GOOGL

# Expected Stage 2 output:
# - 5-8 research threads discovered
# - Research groups organized by theme
# - Web searches performed and logged
```
