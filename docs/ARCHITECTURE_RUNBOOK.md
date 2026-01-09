# Equity Research Pipeline Architecture Runbook (Current)

This is the canonical, end-to-end architecture and run guide for the equity research system.
It focuses on what happens when you run a ticker, which agents/tools are used, where
payloads and citations live, and how the frontend consumes the run outputs.

## 0. Quick Start (Run a Company)

### CLI (recommended)
1. Ensure `.env` is configured (see Section 1).
2. Install deps: `pip install -e ".[dev]"`.
3. Run:
   - `er analyze AAPL --budget 25`
   - Optional: `--dry-run` (no external API calls)
   - Optional: `--resume output/run_AAPL_YYYYMMDD_HHMMSS`
   - Optional: `--transcripts-dir ./transcripts`

Outputs land in `output/run_{id}/` (CLI uses timestamped folders; API uses run IDs).

### UI (Next.js + FastAPI)
1. Start API server: `python frontend/api/server.py`
2. Start UI: `cd frontend && npm install && npm run dev`
3. Open http://localhost:3000

### Minimal Smoke Run (no external calls)
- `er analyze AAPL --dry-run`

## 1. Configuration and Environment

Settings are in `src/er/config.py` and load from `.env`.

Required:
- `SEC_USER_AGENT` (must include an email address)
- At least one LLM key: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`

Recommended data providers:
- `FMP_API_KEY` for Financial Modeling Prep
- `FINNHUB_API_KEY` optional (transcripts in higher tiers)

Core directories:
- `CACHE_DIR` (default `.cache`) for EvidenceStore
- `OUTPUT_DIR` (default `output`) for run artifacts

Model defaults (override via `.env`):
- `MODEL_WORKHORSE` (fast, cheap)
- `MODEL_RESEARCH` (balanced)
- `MODEL_JUDGE` (high quality)
- `MODEL_SYNTHESIS` (high quality)

## 2. Data Sources and Providers

- Financial Modeling Prep (FMP)
  - `src/er/data/fmp_client.py`
  - Financial statements, estimates, transcripts, ratios
- Market data via yfinance
  - `src/er/data/price_client.py`
  - Current price, market cap, beta, etc
- Web research via provider-specific search
  - `src/er/retrieval/search_provider.py`
  - OpenAI web_search or Gemini grounding; returns URLs and snippets only
- Web fetch + extraction
  - `src/er/retrieval/fetch.py`
  - Fetches HTML, extracts clean text
- Evidence card summarization
  - `src/er/retrieval/evidence_cards.py`
  - Summarizes pages into evidence cards
- Security hardening (available, not currently wired)
  - `src/er/security/sanitizer.py`
  - Intended to sanitize fetched text before summarization

## 3. Storage, Audit, and Artifacts

### EvidenceStore (global cache)
- Path: `.cache/evidence.db` and `.cache/blobs/`
- Stores raw content + metadata
- Evidence IDs like `ev_...` live here
- Lookup example:
  - `SELECT * FROM evidence WHERE evidence_id = 'ev_...';`

### WorkspaceStore (per-run artifacts)
- Path: `output/run_id/workspace.db`
- Stores structured artifacts (evidence cards, dossiers, claim graphs, etc)
- Artifact types include: `evidence_card`, `thread_brief`, `vertical_dossier`,
  `claim_graph`, `entailment_report`, `coverage_scorecard`, `recency_guard_output`,
  `dcf_valuation`, `reverse_dcf`, `peer_group`

### EventStore (agent audit trail)
- Path: `output/run_id/events.jsonl` and `output/run_id/events.db`
- Logs all agent-to-agent messages and metadata

### Run Outputs
Common files in `output/run_id/`:
```
manifest.json
report.md
costs.json
stage1_company_context.json
stage2_internal_discovery.json
stage2_external_discovery.json
stage2_discovery.json
stage3_group_research.json
stage3_verticals.json
stage3_5_verification.json
stage3_75_integration.json
stage4_claude_synthesis.json
stage4_gpt_synthesis.json
stage5_editorial_feedback.json
stage6_final_report.json
stage7_valuation.json
stage7_peers.json
stage7_compiled_report.json
<symbol>_valuation.xlsx
```

## 4. Pipeline Overview (What Happens When You Run a Company)

```
Stage 1  Data Collection
Stage 2  Discovery (internal + external + merge)
         Coverage audit + Recency guard (best-effort, no stage ID)
Stage 3  Deep Research (vertical analysts)
Stage 3.5 Verification
Stage 3.75 Integration
Stage 4  Dual Synthesis (Claude + GPT)
Stage 5  Editorial Judge
Stage 6  Revision / Resynthesis
Stage 7  Valuation + Report Compilation (non-blocking, no UI stage)
```

### Stage 1: Data Collection
- Agent: `DataOrchestrator` (`src/er/agents/data_orchestrator.py`)
- Inputs: ticker, settings
- Calls:
  - FMP client for financials and estimates
  - yfinance for current price/market data
- Output: `CompanyContext`
- File: `stage1_company_context.json`

### Stage 2: Discovery
- Agents:
  - Internal: `DiscoveryAgent` (`src/er/agents/discovery.py`)
  - External: `ExternalDiscoveryAgent` (`src/er/agents/external_discovery.py`)
  - Merger: `DiscoveryMerger` (`src/er/agents/discovery_merger.py`)
- Internal discovery uses the LLM router (role: DISCOVERY) with provider-specific web search/grounding when enabled
- External discovery uses evidence-first pipeline (query plan -> fetch -> evidence cards -> LLM)
- Outputs:
  - `stage2_internal_discovery.json`
  - `stage2_external_discovery.json`
  - `stage2_discovery.json` (merged)
- Key objects: `DiscoveryOutput`, `DiscoveredThread`, `ThreadBrief`

### Coverage + Recency (post-Stage 2)
- Agents:
  - `CoverageAuditor` (`src/er/agents/coverage_auditor.py`)
  - `RecencyGuardAgent` (`src/er/agents/recency_guard.py`)
- Purpose: coverage gaps and last-90-days changes
- Outputs stored in WorkspaceStore (no stage file)

### Stage 3: Deep Research
- Agent: `VerticalAnalystAgent` (`src/er/agents/vertical_analyst.py`)
- Uses the LLM router (role: RESEARCH) for deep research
- Inputs: `CompanyContext`, `DiscoveryOutput`, per-thread evidence IDs
- Output: `VerticalAnalysis` for each vertical and `GroupResearchOutput`
- Files: `stage3_group_research.json`, `stage3_verticals.json`

### Stage 3.5: Verification
- Agent: `VerificationAgent` (`src/er/agents/verifier.py`)
- Steps:
  - Heuristic verification (rule-based checks)
  - Produces a fact ledger + confidence signals
- Output: `VerifiedResearchPackage`
- File: `stage3_5_verification.json`
- Note: Claim graph + entailment modules exist but are not wired into Stage 3.5

### Stage 3.75: Integration
- Agent: `IntegratorAgent` (`src/er/agents/integrator.py`)
- Output: `CrossVerticalMap`
- File: `stage3_75_integration.json`

### Stage 4: Dual Synthesis
- Agent: `SynthesizerAgent` (`src/er/agents/synthesizer.py`)
- Runs:
  - Claude Opus (Anthropic) synthesis
  - GPT synthesis (model ID in `synthesizer.py`)
- Output: `SynthesisOutput` (one per model)
- Files:
  - `stage4_claude_synthesis.json`
  - `stage4_gpt_synthesis.json`

### Stage 5: Editorial Review
- Agent: `JudgeAgent` (`src/er/agents/judge.py`)
- Compares both syntheses and issues editorial feedback
- Output: `EditorialFeedback`
- File: `stage5_editorial_feedback.json`

### Stage 6: Revision / Resynthesis
- Agent: `SynthesizerAgent`
- If both syntheses rejected, resynthesis runs with rejection context
- Output: final `SynthesisOutput`
- File: `stage6_final_report.json`
- Rendered report: `report.md`

### Stage 7: Valuation + Report Compilation (non-blocking)
- Engines:
  - `DCFEngine`, `ReverseDCFEngine` (`src/er/valuation/`)
  - `PeerSelector` (`src/er/peers/selector.py`)
  - `ReportCompiler` (`src/er/reports/compiler.py`)
  - `ValuationExporter` (`src/er/valuation/excel_export.py`)
- Outputs:
  - `stage7_valuation.json`
  - `stage7_peers.json`
  - `stage7_compiled_report.json`
  - `*_valuation.xlsx`

## 5. Agent and Prompt Inventory

Prompts live in agent files (not in `prompts/`). Key prompts:
- Discovery: `DISCOVERY_PROMPT` in `src/er/agents/discovery.py`
- External discovery: `EXTERNAL_DISCOVERY_PROMPT` in `src/er/agents/external_discovery.py`
- Deep research: `DEEP_RESEARCH_PROMPT` in `src/er/agents/vertical_analyst.py`
- Integration: `INTEGRATION_PROMPT` in `src/er/agents/integrator.py`
- Synthesis: `SYNTHESIS_PROMPT`, `REVISION_PROMPT` in `src/er/agents/synthesizer.py`
- Judge: `JUDGE_PROMPT`, `REVISION_PROMPT` in `src/er/agents/judge.py`

Other agents use programmatic prompts or internal heuristics:
- `CoverageAuditor` uses keyword coverage + WebResearchService
- `RecencyGuardAgent` uses targeted queries + heuristics
- `VerificationAgent` uses ClaimGraph + entailment verification

## 6. LLM Routing and Models

### LLMRouter Roles
Defined in `src/er/llm/router.py`:
- ORCHESTRATION, RESEARCH, SYNTHESIS, JUDGE, FACTCHECK, WORKHORSE, OUTPUT
- Each role maps to a provider/model; fallback provider is used if keys are missing
- Dry-run short-circuits before creating clients

### Models Used by Core Agents
- Internal Discovery: OpenAI `gpt-5.2` (with web_search or reasoning)
- External Discovery: LLMRouter `AgentRole.SYNTHESIS` (default to `MODEL_SYNTHESIS`)
- Deep Research: OpenAI `o4-mini-deep-research-2025-06-26`
- Synthesis: Anthropic `claude-opus-4-5-20251101` and OpenAI `gpt-5.2`
- Judge: Anthropic `claude-opus-4-5-20251101`
- Evidence cards: LLMRouter `AgentRole.OUTPUT` (cheap summarization)

## 7. Payload Contracts (Key Types)

All types are in `src/er/types.py`.

### CompanyContext
- Core data snapshot: profile, financials, transcripts, market data
- Used across discovery, research, synthesis

### DiscoveryOutput
- `research_threads`: list of `DiscoveredThread`
- `thread_briefs`: list of `ThreadBrief`
- `evidence_ids`: evidence ID pool
- `searches_performed`: used to re-fetch evidence cards

### DiscoveredThread
- `thread_id`, `name`, `thread_type`, `priority`, `description`
- `discovery_lens`, `research_questions`, `evidence_ids`

### VerticalAnalysis
- `vertical_name`, `facts`, `dossier`, `confidence`, `evidence_ids`

### Fact
- `statement`, `category`, `source`, `source_date`
- `evidence_id` (single) and `evidence_ids` (multi-cite)

### VerifiedResearchPackage
- `verification_results`, `all_verified_facts`
- `critical_issues`, `evidence_ids`

### CrossVerticalMap
- `relationships`, `shared_risks`, `cross_vertical_insights`
- `key_dependencies`, `foundational_verticals`

### SynthesisOutput
- `full_report`, `investment_view`, `conviction`, `overall_confidence`
- `thesis_summary`, `evidence_ids`

### EditorialFeedback
- `preferred_synthesis`, scores, `errors_to_fix`, `gaps_to_address`

### ValuationWorkbook / CompiledReport
- DCF, Reverse DCF, peers, report sections

## 8. Evidence and Citations (Where to See Them)

### How citations are created
- Evidence IDs are minted in EvidenceStore for every fetch or evidence card
- Threads and facts carry evidence IDs forward
- Synthesis prompt requires citing evidence IDs in brackets: `[ev_xxx]`

### Where to look up citations
- Evidence metadata: `.cache/evidence.db`
- Evidence blobs: `.cache/blobs/<hash>`
- Evidence card artifacts: `workspace.db` (artifact_type = `evidence_card`)
- Verified facts in `stage3_5_verification.json`
- Final report citations in `report.md` and `stage6_final_report.json`

## 9. Frontend / API Contract

API server: `frontend/api/server.py`

Endpoints:
- `POST /runs/start` - start a run
- `GET /runs` - list completed runs
- `GET /runs/{run_id}` - load run summary + stage payloads
- `GET /runs/{run_id}/stream` - SSE live stream
- `GET /runs/{run_id}/report` - final report
- `GET /runs/{run_id}/stage/{stage}` - specific stage
- `GET /config/agents` - list agents
- `GET /config/prompts/{agent_file}` - prompt text

SSE event shape:
- `type` (primary) and `event_type` (legacy alias)
- `agent_name`
- `stage` (float, supports 3.5 and 3.75)
- `data` (status, message, error, etc)

Frontend state:
- Types are snake_case (`frontend/src/types/index.ts`)
- Stage list includes 3.5 and 3.75

## 10. Known Gaps / Not Wired (as of now)

These modules exist but are not fully wired into the main pipeline:
- Indexing pipeline (`src/er/indexing/*`) is not used by discovery or synthesis
- TranscriptExtractor exists but is not invoked in the main run
- `prompts/` contains legacy prompt copies, not the live prompts

If you want to delete or archive these, confirm first.

## 11. Where to Change Things

- Pipeline flow: `src/er/coordinator/pipeline.py`
- Core types: `src/er/types.py`
- Prompts: files in `src/er/agents/*`
- Evidence pipeline: `src/er/retrieval/*`
- UI contract: `frontend/api/server.py`, `frontend/src/lib/api.ts`, `frontend/src/store/research.ts`
