/ralph-loop "
You are implementing a new architecture for the equity research pipeline at /Users/isaacentebi/equity-research.

## CONTEXT
The current 6-stage pipeline produces good reasoning but suffers from:
- Context loss across stage handoffs (later agents only see prose, not sources/data)
- Web discovery blind spots and knowledge-cutoff priors (missing recent developments)
- No pre-synthesis verification loop (errors propagate)
- External discovery token/cost explosion due to LLM web_search returning full pages
- Weak holistic integration (vertical agents don’t share a business model map)
- EvidenceStore exists but web-derived evidence is not persisted or linked to claims

Key requirement: preserve research quality, improve recall, and make every claim traceable to evidence WITHOUT exploding token costs. Keep CLI compatibility (er analyze TICKER). Keep EvidenceStore SHA256/SQLite system.

## ARCHITECTURE TO IMPLEMENT
Implement an Evidence-First Research Workspace:

1) EvidenceStore remains the canonical raw evidence store.
   - All web pages fetched/summarized must be stored as evidence with hashes.
   - Evidence IDs must propagate to artifacts.

2) Add a run-scoped WorkspaceStore (SQLite) to store structured artifacts:
   - CompanySnapshot (structured company data + quant_metrics)
   - EvidenceCards (bounded summaries of web pages, tied to evidence IDs)
   - ThreadPlan/ThreadBriefs (research threads WITH rationale and required evidence)
   - VerticalDossiers (facts[] with evidence IDs + analysis narrative)
   - VerificationReport (issues + verified facts)
   - CrossVerticalMap (holistic integration)
   - (Optional) ValuationPack (Excel + assumptions)

3) Decouple web retrieval from reasoning:
   - Add WebResearchService that:
     a) Generates/accepts search queries
     b) Uses a URL discovery provider (default: OpenAI web_search via LLMRouter)
     c) Fetches pages via HTTP (httpx), extracts text, stores raw evidence
     d) Summarizes each page into an EvidenceCard using a cheap model
     e) Caches/dedupes by URL/content hash

4) Replace the current ExternalDiscoveryAgent’s expensive “full page inside Claude web_search” flow:
   - External discovery should consume EvidenceCards, not raw tool payloads.
   - Output must include evidence IDs pointing to web evidence.

5) Add Verification stage before synthesis:
   - Extract numeric facts/claims from VerticalDossiers.
   - Verify against CompanySnapshot financials/quant_metrics deterministically.
   - For external claims, ensure evidence IDs exist; flag unsupported claims.
   - Produce VerifiedFacts + Issues. (Optional bounded repair loop later.)

6) Add a Cross-Vertical Integrator agent:
   - Inputs: VerifiedFacts + VerticalDossiers + CompanySnapshot
   - Output: CrossVerticalMap (synergies, shared risks, scenario drivers) with citations.

7) Update Synthesizer to use VerifiedFacts + CrossVerticalMap + EvidenceCards:
   - Prohibit uncited factual claims.
   - Produce report + appendix (fact table, claim table, evidence index).

8) Preserve CLI + pipeline:
   - er analyze must still work.
   - Pipeline remains 6 stages, but Stage 3 internally includes verification + integration (substeps).
   - Budget tracking remains.

## PHASES

Phase 1: Stabilize data contracts and restore missing ground-truth fields
  Working directory: /Users/isaacentebi/equity-research
  Tasks:
    - Modify src/er/types.py:
      - Add CompanyContext.quant_metrics: dict[str, Any] = field(default_factory=dict)
      - Add CompanyContext.market_data: dict[str, Any] = field(default_factory=dict) (store yfinance quote)
      - Add helper methods:
        - CompanyContext.for_synthesis() -> compact dict (profile + latest quarter + key multiples + quant_metrics + market_data)
        - CompanyContext.for_verification() -> dict with financial statements + segment data + quant_metrics + market_data
      - Ensure dataclass serialization in pipeline still works.
    - Modify src/er/agents/data_orchestrator.py:
      - Ensure get_full_context quant_metrics is carried into CompanyContext.from_fmp_data
      - Attach yfinance quote into CompanyContext.market_data
    - Modify src/er/types.py CompanyContext.from_fmp_data() to ingest quant_metrics and market_data keys if present.
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && python -m pip install -e \".[dev]\"
    - Run: cd /Users/isaacentebi/equity-research && python -c \"from er.data.fmp_client import FMPClient; from er.types import CompanyContext\"
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Expected: tests pass

Phase 2: Add WorkspaceStore for structured artifacts (non-invasive)
  Tasks:
    - Create src/er/workspace/__init__.py
    - Create src/er/workspace/store.py:
      - Implement WorkspaceStore backed by SQLite (workspace.db in run output dir)
      - Tables:
        - artifacts(id TEXT PK, type TEXT, created_at TEXT, producer TEXT, json TEXT, summary TEXT, evidence_ids TEXT)
        - search_log(id TEXT PK, query TEXT, provider TEXT, created_at TEXT, result_json TEXT)
      - Methods:
        - init()
        - put_artifact(type, producer, json_obj, summary, evidence_ids) -> artifact_id
        - get_artifact(artifact_id) -> dict
        - list_artifacts(type=None) -> list
    - Modify src/er/agents/base.py AgentContext to include workspace_store: WorkspaceStore | None
    - Modify src/er/coordinator/pipeline.py:
      - Create workspace.db inside each run output dir
      - Initialize WorkspaceStore and attach to AgentContext
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL
    - Expected:
      - output/run_AAPL_*/workspace.db exists
      - CLI exits 0

Phase 3: Implement WebResearchService (URL discovery + fetch + evidence + EvidenceCards)
  Tasks:
    - Create src/er/retrieval/__init__.py
    - Create src/er/retrieval/search_provider.py:
      - Define SearchResult dataclass {title, url, snippet, published_at?, source}
      - Define SearchProvider protocol: search(query, max_results, recency_days, domains=None) -> list[SearchResult]
      - Implement OpenAIWebSearchProvider using LLMRouter with tools=[{\"type\":\"web_search\"}] and a cheap model:
        - Prompt must force strict JSON output: {results:[...]}
        - Keep max_tokens small (e.g., 1200)
        - Return only top N results; do NOT include full page content.
    - Create src/er/retrieval/fetch.py:
      - Fetch URLs via httpx with timeouts, user-agent, retries
      - Extract readable text (use readability-lxml if available; otherwise fallback to bs4/html.parser strip)
      - Store raw HTML and extracted text into EvidenceStore with appropriate SourceTier/ToSRisk heuristics
      - Return evidence_id(s)
    - Create src/er/retrieval/evidence_cards.py:
      - Summarize extracted text into an EvidenceCard (<= 300-500 tokens) using a cheap model (router AgentRole.OUTPUT/workhorse)
      - Store the summary as an EvidenceStore entry too (content_type application/json)
      - Also store in WorkspaceStore as artifact type=\"evidence_card\" with evidence_ids=[raw_evidence_id, summary_evidence_id]
    - Add caching/deduping:
      - Before fetching, check EvidenceStore for existing source_url match; reuse if exists
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && python -c \"from er.retrieval.search_provider import OpenAIWebSearchProvider\"
    - Expected: import succeeds; tests pass

Phase 4: Refactor External Discovery to consume EvidenceCards instead of Claude full-page web_search
  Tasks:
    - Modify src/er/agents/external_discovery.py:
      - Remove/disable anthropic web_search tool usage for default path
      - Use WebResearchService:
        - Build a deterministic query plan:
          - competitors, industry news last 90 days, analyst upgrades/downgrades, product launches, regulatory
        - Execute searches with quotas (e.g., max 25 queries, max 3 results each)
        - Fetch+summarize into EvidenceCards
      - Feed EvidenceCards (summaries only) to the LLM (Claude or GPT) WITHOUT web_search tool
      - Ensure ExternalDiscoveryOutput.evidence_ids includes web evidence IDs from EvidenceCards
      - Populate searches_performed with query strings and URLs used
    - Update scripts/test_external_discovery.py to reflect new behavior and to print evidence_id counts
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && python scripts/test_external_discovery.py --ticker GOOGL
    - Expected:
      - completes without massive token usage
      - outputs searches_performed
      - output includes evidence_ids beyond base CompanyContext

Phase 5: Upgrade Discovery output to preserve “why” and evidence pointers (ThreadBriefs)
  Tasks:
    - Modify src/er/types.py:
      - Add new dataclass ThreadBrief:
        - thread_id, rationale, hypotheses, key_questions, required_evidence, key_evidence_ids, confidence
      - Add DiscoveryOutput.thread_briefs: list[ThreadBrief] (default empty for backward compat)
    - Modify src/er/agents/discovery.py:
      - Output must include ThreadBriefs (why prioritized, what changed recently, what evidence supports)
      - Ensure DiscoveredThread.evidence_ids includes relevant web evidence IDs when applicable
      - Store the ThreadPlan + ThreadBriefs into WorkspaceStore artifacts
    - Modify src/er/agents/discovery_merger.py:
      - Merge ThreadBriefs (prefer higher-confidence, union evidence ids)
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL
    - Expected: stage2 output json includes thread_briefs; CLI exits 0

Phase 6: Make Vertical Analysts produce structured facts with citations (VerticalDossier)
  Tasks:
    - Modify src/er/types.py:
      - Add Fact dataclass:
        - fact_id, statement, entity, metric?, period?, value?, unit?, evidence_ids, confidence, fact_type(enum)
      - Add VerticalDossier dataclass:
        - thread_id, title, facts: list[Fact], analysis_md, open_questions, data_gaps, overall_confidence, evidence_ids
    - Modify src/er/agents/vertical_analyst.py:
      - Change prompt to require:
        - JSON block \"FACTS_JSON\" containing facts[] with evidence_ids
        - Followed by \"ANALYSIS_MD\" markdown referencing facts by fact_id
      - Parse and return VerticalDossier(s)
      - Store VerticalDossiers into WorkspaceStore artifacts
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL
    - Expected:
      - stage3 outputs include facts arrays
      - no parsing errors

Phase 7: Add Verification Agent (pre-synthesis)
  Tasks:
    - Create src/er/agents/verifier.py:
      - Input: CompanyContext.for_verification(), VerticalDossiers
      - Deterministically verify numeric facts:
        - match metric/period to financial statements/quant_metrics within tolerance
      - Evidence checks:
        - every external fact must have >=1 evidence_id that exists in EvidenceStore
      - Output: VerificationReport:
        - verified_facts: list[Fact] (subset flagged as verified)
        - issues: list[{fact_id, severity, reason, suggested_fix}]
        - coverage_scorecard: dict
    - Modify src/er/coordinator/pipeline.py:
      - After Stage 3 vertical research, run VerifierAgent (as Stage 3 substep)
      - Save stage3_verification.json
      - Pass VerifiedFacts + Issues forward to synthesis
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL
    - Expected: verification output file exists; pipeline completes dry-run

Phase 8: Add Integrator Agent for holistic business model (pre-synthesis)
  Tasks:
    - Create src/er/agents/integrator.py:
      - Input: VerifiedFacts + VerticalDossiers + CompanySnapshot
      - Output: CrossVerticalMap artifact:
        - synergies, tensions, shared_risks, scenario_drivers
        - each item includes evidence_ids
    - Modify pipeline.py to run IntegratorAgent after verification and before synthesis; save stage3_integration.json
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL
    - Expected: integration artifact exists; CLI exits 0

Phase 9: Refactor Synthesizer and Judge to use VerifiedFacts + CrossVerticalMap + citations
  Tasks:
    - Modify src/er/agents/synthesizer.py:
      - Add inputs: verification_report, cross_vertical_map, company_context.for_synthesis()
      - Update prompt:
        - Prohibit uncited facts; require evidence IDs inline or in appendix
        - Require a \"Claims Appendix\" listing key claims with evidence IDs and confidence
    - Modify src/er/agents/judge.py:
      - Provide the judge with:
        - both reports
        - claims appendices
        - verification issues summary
      - Judge must flag any uncited claims as errors_to_fix
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL
    - Expected: synthesized markdown includes citations/claim appendix; judge outputs errors for uncited claims

Phase 10 (Optional): ValuationPack (toggleable DCF + reverse DCF + comps in Excel)
  Tasks:
    - Add PipelineConfig.include_valuation: bool = False and CLI flag --valuation/--no-valuation
    - Create src/er/valuation/engine.py:
      - Build deterministic DCF + reverse DCF + sensitivity grid
      - Build comps table from CompanyContext + selected peers
    - Create src/er/agents/valuation.py:
      - Uses VerifiedFacts + CompanyContext to populate model assumptions
      - Writes valuation.xlsx via openpyxl
      - Outputs valuation_summary.json artifact
    - Integrate into pipeline prior to synthesis when enabled; synthesizer references valuation_summary.
  Verification:
    - Run: cd /Users/isaacentebi/equity-research && pytest -q
    - Run: cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL --valuation
    - Expected: valuation.xlsx exists in run folder

## COMPLETION CRITERIA (ALL must be verified true)
- [ ] CompanyContext includes quant_metrics and market_data: Verify with `python -c "from er.types import CompanyContext; import inspect; print('quant_metrics' in CompanyContext.__dataclass_fields__)"` 
- [ ] WorkspaceStore persists artifacts: Verify with `python -c "import sqlite3; import glob; p=glob.glob('output/run_*/*workspace.db')[0]; con=sqlite3.connect(p); print(con.execute('select count(*) from artifacts').fetchone())"`
- [ ] External discovery no longer uses full-page Claude web_search by default; web pages are stored as evidence and summarized as EvidenceCards: Verify by running `python scripts/test_external_discovery.py --ticker GOOGL` and checking evidence count/logs
- [ ] Vertical outputs include Facts[] with evidence_ids: Verify by inspecting stage3 JSON output
- [ ] VerificationReport is produced before synthesis: Verify stage3_verification.json exists
- [ ] Synthesizer output includes a Claims Appendix with evidence IDs: Verify in report.md
- [ ] pytest passes: `cd /Users/isaacentebi/equity-research && pytest`
- [ ] CLI works: `cd /Users/isaacentebi/equity-research && er analyze --dry-run AAPL`

Output <promise>COMPLETE</promise> ONLY when ALL criteria verified.

## IF STUCK after 20 iterations
- Document what's blocking
- List approaches tried
- Suggest alternatives
" --max-iterations 50 --completion-promise "COMPLETE"
