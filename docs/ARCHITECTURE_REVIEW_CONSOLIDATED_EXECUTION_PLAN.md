# Consolidated Execution Plan for Architecture Fixes

This document is a detailed, step-by-step implementation plan for another coding agent to execute. It consolidates all findings and required fixes from the latest architecture review and the external diagnostic. It is comprehensive for **all known issues** identified so far; it cannot guarantee unknown bugs. Run the full test suite and re-audit after completion.

---

## 0) Operating Principles (Non-Negotiables)

- No destructive commands (e.g., `git reset --hard`) unless explicitly requested.
- Do not revert unrelated changes (repo may be dirty).
- Use ASCII unless the file already contains Unicode.
- Preserve existing API contract unless the frontend is updated in the same change.
- Prefer small, isolated diffs per fix; do not reformat unrelated code.
- Add tests only where you change behavior; avoid broad test refactors.

---

## 1) Scope Summary

### Phase 1: Critical crashers (must fix)
1. Reject-both resynthesis uses undefined variable and missing prompt placeholders.
2. Resume/deserialization crashes in Stage 1 and Stage 3+.
3. Stage 3.5/3.75 checkpoints saved but ignored.
4. Missing `Scenario` type in `types.py`.
5. Evidence linkage broken (facts default to a single evidence ID).
6. AgentRole.WORKHORSE referenced but not defined (blocks Recency/ClaimGraph/Entailment).
7. SSE contract mismatch and stage ID mismatch between API and frontend.

### Phase 2: Correctness and reliability (should fix)
1. ThreadBriefs dropped on resume.
2. Cached fetch returns only snippets, degrading evidence cards.
3. Dry run still instantiates provider clients.
4. Provider/model mismatch when required provider key is missing (e.g., research defaults to Gemini).
5. Internal discovery does not persist evidence IDs from web_search.
6. `DiscoveryOutput.get_group_by_name()` returns early.
7. `.env.example` model defaults drift from `Settings` defaults.

### Phase 3: Feature completion (wire orphaned modules)
1. RecencyGuard, CoverageAuditor, Indexing, InputSanitizer wired into pipeline.
2. ClaimGraph + Entailment + ConfidenceCalibrator integrated into verification.
3. ReportCompiler + Peers + Valuation + Excel export integrated into pipeline.
4. RunManifest v2 adoption across CLI and API server.
5. WebResearchService batch concurrency and query budget controls.
6. Frontend types and new tabs for verification/integration/evidence.

---

## 2) File Locations (Quick Reference)

- Pipeline orchestration: `src/er/coordinator/pipeline.py`
- Synthesizer: `src/er/agents/synthesizer.py`
- Types: `src/er/types.py`
- Verifier: `src/er/agents/verifier.py`
- LLM router: `src/er/llm/router.py`
- Discovery: `src/er/agents/discovery.py`
- External discovery: `src/er/agents/external_discovery.py`
- Vertical analyst: `src/er/agents/vertical_analyst.py`
- Recency/Coverage: `src/er/agents/recency_guard.py`, `src/er/agents/coverage_auditor.py`
- ClaimGraph/Entailment: `src/er/verification/claim_graph.py`, `src/er/verification/entailment.py`
- Confidence: `src/er/confidence/calibration.py`, `src/er/confidence/tier_policy.py`
- Indexing: `src/er/indexing/transcript_index.py`, `src/er/indexing/filing_index.py`
- Security: `src/er/security/sanitizer.py`
- Retrieval: `src/er/retrieval/fetch.py`, `src/er/retrieval/evidence_cards.py`, `src/er/retrieval/service.py`
- Reports: `src/er/reports/compiler.py`
- Peers: `src/er/peers/selector.py`, `src/er/peers/comps.py`
- Valuation: `src/er/valuation/dcf.py`, `src/er/valuation/reverse_dcf.py`, `src/er/valuation/excel_export.py`
- Manifest: `src/er/manifest.py`
- Frontend API server: `frontend/api/server.py`
- Frontend SSE consumer: `frontend/src/lib/api.ts`
- Frontend UI/stages: `frontend/src/components/RunPanel.tsx`, `frontend/src/store/research.ts`, `frontend/src/components/RunHistory.tsx`
- Config defaults: `.env.example`, `src/er/config.py`

---

## 3) Required Fixes (Ordered Implementation)

### Fix 1: Reject-both resynthesis crashers (CRITICAL)

**Goal**: Remove NameError and missing-format KeyError in reject-both flow.

**Files**:
- `src/er/coordinator/pipeline.py`
- `src/er/agents/synthesizer.py`

**Steps**:
1. In `pipeline.py`, replace `discovery` with `discovery_output` in the `_run_resynthesis` call.
   - Location: `src/er/coordinator/pipeline.py:775`.
2. In `synthesizer.py`, update `resynthesis()` to include `verified_facts_section` and `cross_vertical_section` in `SYNTHESIS_PROMPT.format(...)`.
   - Location: `src/er/agents/synthesizer.py:814`.
3. Reuse `_format_verified_facts()` and `_format_cross_vertical_map()` to construct those sections.

**Expected outcome**:
- Reject-both path runs without NameError or KeyError.

**Verification**:
- Add a targeted test (or minimal harness) that triggers `preferred_synthesis == "reject_both"` and ensures resynthesis completes.

**Dependencies**:
- None.

---

### Fix 2: Resume deserialization + Stage 3.5/3.75 checkpoints + ThreadBriefs (HIGH)

**Goal**: Resume does not crash and respects new stages.

**Files**:
- `src/er/coordinator/pipeline.py`
- `src/er/types.py`

**Steps**:
1. Add `CompanyContext.from_dict()` to parse `fetched_at` as `datetime` and `evidence_ids` as tuple.
2. Update `_load_company_context()` to call `CompanyContext.from_dict()`.
3. Add `VerticalAnalysis.from_dict()` that rebuilds nested objects:
   - `facts`: use `Fact.from_dict()`
   - `dossier`: use `VerticalDossier.from_dict()`
4. Update `_load_vertical_analyses()` to call `VerticalAnalysis.from_dict()`.
5. Update `_load_discovery_output()` to restore `thread_briefs`.
6. Extend `_get_completed_stages()` to include `stage3_5_verification.json` and `stage3_75_integration.json`.
7. Add loader helpers for verification/integration outputs and skip re-running them when checkpoints exist.

**Expected outcome**:
- Resume from stage1 or stage3 no longer crashes.
- Stage 3.5/3.75 are skipped when checkpoints exist.

**Verification**:
- Create fixtures for stage outputs and run the pipeline in resume mode.
- Confirm verifier can access `Fact.category` and `Fact.statement` (no dict attribute errors).

**Dependencies**:
- None.

---

### Fix 3: Define Scenario type (CRITICAL)

**Goal**: Resolve missing `Scenario` reference in `types.py`.

**Files**:
- `src/er/types.py`

**Steps**:
1. Define a minimal `Scenario` dataclass near other report/decision types.
2. Ensure it matches the JSON schema expected by synthesis output (probability + headline).

**Example**:
```python
@dataclass
class Scenario:
    probability: float
    headline: str
    description: str = ""
```

**Expected outcome**:
- `from er.types import Scenario` succeeds; no NameError on type references.

**Verification**:
- `python -c "from er.types import Scenario; print(Scenario(0.5, 'Base'))"`

**Dependencies**:
- None.

---

### Fix 4: Evidence propagation into vertical analyses + internal discovery evidence (HIGH)

**Goal**: Facts and verticals use evidence IDs from discovery and external evidence cards, not just CompanyContext.

**Files**:
- `src/er/agents/vertical_analyst.py`
- `src/er/agents/discovery.py`
- `src/er/types.py`

**Steps**:
1. For each vertical, derive `base_evidence_ids` as:
   - `thread.evidence_ids`
   - plus `ThreadBrief.key_evidence_ids` (if available)
   - fallback to `company_context.evidence_ids` only if empty
2. Use that merged list for:
   - `VerticalAnalysis.evidence_ids`
   - `Fact.evidence_id` (or add `Fact.evidence_ids` for multi-cite support; if you add it, update serializers and TS types in the same change)
3. Ensure internal discovery persists evidence IDs from web_search results:
   - Inspect `OpenAIClient.complete_with_web_search` output for source URLs/citations.
   - Store sources in EvidenceStore and add IDs to `DiscoveredThread.evidence_ids` and `ThreadBrief.key_evidence_ids`.
   - If citations are not available, at minimum store the query metadata in WorkspaceStore and mark evidence IDs as empty with explicit TODO notes.

**Expected outcome**:
- Facts and verticals have non-empty evidence IDs that trace to evidence cards or raw sources.

**Verification**:
- Unit test: a thread with evidence IDs produces facts whose evidence IDs are in that set.

**Dependencies**:
- Fix 2 for resume safety.

---

### Fix 5: AgentRole.WORKHORSE + hardening wiring (HIGH)

**Goal**: Recency/ClaimGraph/Entailment can be wired without runtime failure, and security is enforced in retrieval.

**Files**:
- `src/er/llm/router.py`
- `src/er/agents/recency_guard.py`
- `src/er/agents/coverage_auditor.py`
- `src/er/verification/claim_graph.py`
- `src/er/verification/entailment.py`
- `src/er/security/sanitizer.py`
- `src/er/retrieval/fetch.py`
- `src/er/retrieval/evidence_cards.py`
- `src/er/coordinator/pipeline.py`

**Steps**:
1. Add `WORKHORSE` to `AgentRole` and map it in `DEFAULT_MODEL_MAP` to the workhorse model, or replace all `AgentRole.WORKHORSE` usage with `AgentRole.OUTPUT`.
2. Wire RecencyGuard and CoverageAuditor into pipeline:
   - RecencyGuard after discovery or before synthesis.
   - CoverageAuditor after external discovery (use evidence cards from WorkspaceStore).
3. Add TranscriptIndex and FilingIndex construction after Stage 1 and pass excerpts into discovery/vertical prompts.
4. Apply InputSanitizer to fetched text before it enters EvidenceCardGenerator (sanitize in `fetch.py` or `evidence_cards.py`).

**Expected outcome**:
- Recency/coverage/security agents run without role errors and operate on sanitized text.

**Verification**:
- Smoke test RecencyGuard and CoverageAuditor.
- Confirm sanitized content is stored when threats are detected.

**Dependencies**:
- Fix 4 for evidence propagation quality.

---

### Fix 6: Cached fetch should return full text (MEDIUM)

**Goal**: Avoid snippet-only evidence on reruns.

**Files**:
- `src/er/retrieval/fetch.py`

**Steps**:
1. On cache hit, read HTML blob from EvidenceStore and re-run `_extract_text()`.
2. Optional: store extracted text as derived evidence for faster reuse.

**Expected outcome**:
- Evidence cards generated from cached content are full-quality.

**Verification**:
- Fetch same URL twice; second fetch should not be snippet-only.

**Dependencies**:
- None.

---

### Fix 7: Dry run safety + provider fallback (MEDIUM)

**Goal**: `DRY_RUN=true` runs without API keys; missing provider keys do not crash research role.

**Files**:
- `src/er/llm/router.py`
- `src/er/config.py`

**Steps**:
1. Check `_dry_run` **before** `get_client_and_model()` so no clients are created.
2. Add provider fallback when selected provider key is missing:
   - If research role defaults to Gemini and `GEMINI_API_KEY` is missing, fall back to OpenAI or Anthropic if available.
   - If no fallback is possible, raise a clear, early error at router init.

**Expected outcome**:
- Dry runs succeed without API keys; live runs fail fast with clear error if no provider matches.

**Verification**:
- Run dry-run pipeline with no keys; confirm no client init errors.
- Run with only OpenAI key; research role should still function.

**Dependencies**:
- None.

---

### Fix 8: SSE contract and stage list alignment (HIGH)

**Goal**: UI shows progress for 3.5/3.75 and receives stage updates.

**Files**:
- `frontend/api/server.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/RunPanel.tsx`
- `frontend/src/store/research.ts`
- `frontend/src/components/RunHistory.tsx`

**Steps**:
1. Normalize SSE events so payload always includes `type` and uses `stage_update` for stage events.
2. Add stages 3.5 and 3.75 to frontend stage list **or** switch to string stage IDs.
3. Update run history to compute stage count from stage list, not hardcoded `/6`.
4. Update `/runs/{id}` loader to include `stage3_5` and `stage3_75` outputs.

**Expected outcome**:
- UI correctly renders verification and integration stages.

**Verification**:
- Run a pipeline and observe live stage updates.

**Dependencies**:
- Fix 2 for stage 3.5/3.75 checkpoints.

---

### Fix 9: RunManifest v2 adoption (MEDIUM)

**Goal**: consistent manifest versioning/checkpointing.

**Files**:
- `src/er/manifest.py`
- `src/er/cli/main.py`
- `frontend/api/server.py`

**Steps**:
1. Replace ad-hoc manifest dict writes with `RunManifest` in CLI and API server.
2. Persist `version`, `checkpoints`, and `input_hash`.

**Expected outcome**:
- Manifest includes version and checkpoint data; resume logic can use it.

**Verification**:
- Run pipeline; verify `manifest.json` fields are present.

**Dependencies**:
- Fix 2 for checkpoint data.

---

### Fix 10: ClaimGraph + Entailment + ConfidenceCalibrator integration (HIGH)

**Goal**: Enable claim-level verification and calibrated confidence.

**Files**:
- `src/er/verification/claim_graph.py`
- `src/er/verification/entailment.py`
- `src/er/confidence/calibration.py`
- `src/er/agents/verifier.py`
- `src/er/agents/synthesizer.py`

**Steps**:
1. Build ClaimGraph from vertical analyses after Stage 3.
2. Build evidence map from EvidenceStore (evidence IDs to text snippets or evidence card summaries).
3. Run EntailmentVerifier on the ClaimGraph.
4. Calibrate claim confidence via ConfidenceCalibrator.
5. Store ClaimGraph + entailment report in WorkspaceStore and include summaries in synthesis prompt.

**Expected outcome**:
- VerifiedResearchPackage contains calibrated confidence and claim verification results.

**Verification**:
- Unit test: a supported claim gets higher calibrated confidence than contradicted.

**Dependencies**:
- Fix 4 (evidence propagation) and Fix 5 (AgentRole.WORKHORSE).

---

### Fix 11: ReportCompiler + Peers + Valuation + Excel Stage (MEDIUM)

**Goal**: Produce a structured report and valuation outputs.

**Files**:
- `src/er/reports/compiler.py`
- `src/er/peers/selector.py`
- `src/er/peers/comps.py`
- `src/er/valuation/dcf.py`
- `src/er/valuation/reverse_dcf.py`
- `src/er/valuation/excel_export.py`
- `src/er/coordinator/pipeline.py`

**Steps**:
1. Add a valuation stage after synthesis or after verification/integration.
2. Compute DCF and Reverse DCF with deterministic engines.
3. Run PeerSelector + CompsAnalyzer and include results in valuation summary.
4. Use ReportCompiler to generate a report that includes citations and valuation appendix.
5. Export Excel workbook via `ValuationExporter` and add artifact to manifest.

**Expected outcome**:
- Run output includes compiled report + valuation artifacts.

**Verification**:
- Check output directory for Excel and compiled report artifacts.

**Dependencies**:
- Fix 10 for calibrated confidence; Fix 9 for manifest artifacts.

---

### Fix 12: WebResearchService batch concurrency and query budgets (LOW)

**Goal**: Avoid unnecessary latency and manage cost.

**Files**:
- `src/er/retrieval/service.py`
- `src/er/agents/external_discovery.py`

**Steps**:
1. Change `research_batch()` to use a semaphore and `asyncio.gather` with low concurrency (e.g., 3).
2. Enforce a strict max query budget and log queries used.
3. Consider reducing default query count or adding config overrides.

**Expected outcome**:
- Faster batch execution without rate-limit spikes.

**Verification**:
- Measure wall-clock time before/after; no errors under rate limits.

**Dependencies**:
- None.

---

### Fix 13: `get_group_by_name` logic bug (LOW)

**Goal**: correct lookup for non-first groups.

**Files**:
- `src/er/types.py`

**Steps**:
1. Move return outside loop; only return when match found.

**Verification**:
- Unit test with two groups; returns correct group.

**Dependencies**:
- None.

---

### Fix 14: `.env.example` alignment (LOW)

**Goal**: reduce onboarding/config confusion.

**Files**:
- `.env.example`
- `src/er/config.py`

**Steps**:
1. Update example model defaults to match `Settings` defaults or document divergence.

**Verification**:
- Doc-only change.

**Dependencies**:
- None.

---

## 4) Optional Architecture Enhancements (Post-Fix)

These are not required for stability but were explicitly requested in the review prompt. Implement after Phase 1-3 fixes.

1. **Specialized agents**: Sentiment, Macro, Risk/Bear. Add new agent classes, wire into pipeline, and add UI tabs.
2. **Bull/Bear debate**: Add an adversarial stage before synthesis. Require citations with evidence IDs.
3. **Cross-validation**: Have agents check each others' claims; down-rank unsupported claims.
4. **Memory/reflection**: Store outcomes and feedback in WorkspaceStore and use to update confidence calibration.

---

## 5) Acceptance Criteria

A change set is considered complete when:
- Reject-both resynthesis runs without NameError/KeyError.
- Resume from stage1 and stage3 does not crash.
- Stage 3.5/3.75 checkpoints are loaded/skipped correctly.
- `Scenario` type exists and imports cleanly.
- Evidence IDs propagate beyond CompanyContext into facts.
- Recency/ClaimGraph/Entailment no longer crash due to AgentRole.WORKHORSE.
- UI shows verification/integration stages with live updates.
- Cached fetch returns full text on rerun.
- Dry run does not instantiate provider clients.

---

## 6) Validation Checklist

- `pytest -k resynthesis` (reject-both path)
- `pytest -k resume` (Stage 1 + Stage 3 resume paths)
- `pytest -k evidence` (facts cite non-empty evidence IDs)
- `pytest -k coverage` (if CoverageAuditor wired)
- Manual UI smoke test for 3.5/3.75 updates
- Dry-run smoke test with no API keys

If you cannot run tests, document exactly what you did not run and why.

---

## 7) Notes for Agent

- Keep new data structures backward compatible (avoid breaking JSON for existing frontends).
- If you change schema (e.g., `Fact.evidence_id` -> `evidence_ids`), update serialization and TS types in the same change.
- Do not attempt to wire all orphaned modules at once; wire only after core evidence propagation and resume are correct.
- Prefer adding minimal new fields over breaking existing ones.

