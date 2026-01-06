# Equity Research Pipeline - Comprehensive Architecture Review Prompt (V2)

You are an expert in multi-agent LLM systems, context engineering, financial research automation, and production Python systems. I need your **ruthless, critical review** of my equity research pipeline architecture after a major institutional-grade hardening implementation.

---

## EXECUTIVE SUMMARY: What Was Built

### Original System (Before)
A 6-stage equity research pipeline producing PM-quality research memos using multi-agent LLM orchestration (Claude, GPT, Gemini).

### What We Just Added (15-Phase Institutional Hardening)
A comprehensive hardening effort implementing:

1. **Evidence-First Architecture** - WorkspaceStore, EvidenceCards, ThreadBriefs, VerticalDossiers
2. **Coverage Scoring** - CoverageScorecard with 8 categories for research completeness
3. **Source Orchestration** - SourceCatalog + QueryPlanner for systematic data retrieval
4. **Recency Guard** - Knowledge-cutoff neutralization (no training data contamination)
5. **Transcript Index** - BM25 retrieval for earnings call excerpts
6. **Filing Index** - BM25 retrieval for SEC filings (10-K, 10-Q, 8-K)
7. **Claim Verification** - ClaimGraph extraction + entailment verification
8. **Confidence Calibration** - Evidence tier policy with systematic confidence scoring
9. **Deterministic Valuation** - DCF + Reverse DCF engines (no LLM arithmetic)
10. **Peer Selection** - Comparable company analysis with industry/market cap matching
11. **Report Compiler** - Structured report compilation with citation linking
12. **Security Hardening** - Prompt injection defense (pattern detection, sanitization)
13. **Evaluation Harness** - Pinned fixtures for deterministic testing
14. **Manifest Versioning** - Schema versioning + checkpoint-based resume invalidation

**Test Coverage: 379 tests passing**

---

## CODEBASE OVERVIEW

```
equity-research/
├── src/er/                    # 87 Python files, ~28K lines
│   ├── agents/                # LLM agents (discovery, synthesis, judge, verifier, etc.)
│   ├── analysis/              # Financial analysis utilities
│   ├── cache/                 # Request caching
│   ├── confidence/            # [NEW] Confidence calibration + tier policy
│   ├── coordinator/           # Pipeline orchestration
│   ├── data/                  # FMP client, sector classification
│   ├── eval/                  # [NEW] Evaluation harness + pinned fixtures
│   ├── evidence/              # Evidence cards + coverage scoring
│   ├── indexing/              # [NEW] Transcript + Filing indexes (BM25)
│   ├── llm/                   # Anthropic, OpenAI, token counting
│   ├── observability/         # Logging infrastructure
│   ├── peers/                 # [NEW] Peer selection + comps analysis
│   ├── reports/               # [NEW] Report compiler
│   ├── retrieval/             # Web research service
│   ├── security/              # [NEW] Prompt injection defense
│   ├── utils/                 # Text chunking, utilities
│   ├── valuation/             # [NEW] DCF + Reverse DCF engines
│   ├── verification/          # [NEW] Claim graph + entailment
│   ├── workspace/             # WorkspaceStore for evidence management
│   ├── cli/                   # CLI interface
│   ├── types.py               # Core dataclasses (~2500 lines)
│   ├── manifest.py            # [ENHANCED] Run manifest with versioning
│   └── budget.py              # Budget tracking
├── frontend/                  # Next.js dashboard
├── tests/                     # 22 test files, 379 tests
└── docs/                      # Documentation
```

---

## ARCHITECTURE FLOW (Updated)

```
STAGE 1: Data Collection (No LLM)
├── FMP API → CompanyContext (~11K tokens)
│   • profile, financials (3Y annual + 4Q quarterly)
│   • balance sheet, cash flow, news, analyst estimates
│   • quant_metrics (ROIC, quality scores, buyback distortion, red flags)
│
├── [NEW] RecencyGuard
│   • Validates all data is recent (configurable staleness threshold)
│   • Blocks stale data from entering pipeline
│
├── [NEW] TranscriptIndex + FilingIndex
│   • BM25-indexed earnings call transcripts
│   • BM25-indexed SEC filings (10-K, 10-Q, 8-K sections)
│   • Retrieves relevant excerpts instead of passing full documents

STAGE 2: Discovery (PARALLEL - 2 agents)
├── Internal Discovery (GPT-5.2 + Web Search)
│   • INPUT: ~2K prompt + ~11K CompanyContext + web search results
│   • OUTPUT: ThreadBriefs with research questions + research groups
│   • [NEW] Uses TranscriptIndex for targeted excerpt retrieval
│
├── External Discovery (Claude Sonnet + Web Search)
│   • INPUT: ~2K prompt + minimal context + web search results
│   • OUTPUT: Competitor developments, analyst sentiment, variant perceptions
│   • [NEW] Uses FilingIndex for risk factor retrieval
│
├── [NEW] CoverageAuditor
│   • Validates discovery covers all 8 required categories
│   • Triggers second-pass retrieval for gaps (bounded iterations)
│
└── Discovery Merger (Code, no LLM)
    • Combines outputs from both discovery agents

STAGE 3: Deep Research (PARALLEL - N research groups)
├── Vertical Analyst (OpenAI o4-mini Deep Research)
│   • INPUT: ~3K prompt + ~11K CompanyContext + thread definitions
│   • OUTPUT: VerticalDossier with Facts[] and EvidenceCards
│   • [NEW] Facts have source URLs, confidence, verification status
│
├── [NEW] ClaimGraphBuilder
│   • Extracts claims from vertical analyses
│   • Links claims to supporting facts
│
└── [NEW] EntailmentVerifier
    • NLI-style verification of claims against evidence
    • Status: SUPPORTED, WEAK, UNSUPPORTED, CONTRADICTED

STAGE 3.5: Verification (NEW)
├── VerificationAgent
│   • Cross-references Facts against CompanyContext ground truth
│   • Marks facts as VERIFIED, CONTRADICTED, PARTIAL, UNVERIFIABLE
│
├── [NEW] ConfidenceCalibrator
│   • Adjusts confidence based on source tier, recency, corroboration
│   • TIER_1 (10-K, transcripts) → 1.0x multiplier
│   • TIER_4 (social media) → 0.5x multiplier
│
└── IntegratorAgent
    • Builds CrossVerticalMap linking related facts across verticals

STAGE 4: Dual Synthesis (PARALLEL - 2 synthesizers)
├── Claude Synthesis (Claude Opus + Extended Thinking)
│   • INPUT: All vertical analyses + VerifiedResearchPackage
│   • OUTPUT: ~20K token report with [citation] markers
│   • [NEW] Must cite evidence IDs for claims
│
├── GPT Synthesis (GPT-5.2)
│   • Same input, independent report
│
└── [NEW] ReportCompiler
    • Extracts investment view, conviction, target price
    • Structures report into canonical sections
    • Links citations to evidence

STAGE 5: Judge (SINGLE)
├── Judge Agent (Claude Opus + Extended Thinking)
│   • INPUT: Both synthesis reports + discovery + key metrics
│   • OUTPUT: Preferred synthesis + revision instructions
│   • [NEW] Checks citation validity
│
└── [NEW] PeerSelector + CompsAnalyzer
    • Validates valuation claims against peer multiples
    • Flags outlier assumptions

STAGE 6: Valuation & Finalization (NEW)
├── [NEW] DCFEngine
│   • Deterministic DCF calculation (no LLM arithmetic)
│   • Sensitivity analysis (WACC × terminal growth matrix)
│
├── [NEW] ReverseDCFEngine
│   • Calculates implied growth from market price
│   • "What's priced in" analysis
│
└── ValuationExporter
    • Exports to JSON, CSV, Excel

STAGE 7: Security & Output
├── [NEW] InputSanitizer
│   • Prompt injection defense on all external content
│   • Pattern detection for jailbreaks, instruction overrides
│   • Threat levels: NONE, LOW, MEDIUM, HIGH, CRITICAL
│
└── [NEW] Manifest v2.0
    • Schema versioning for resume compatibility
    • Checkpoint hashes per phase
    • Input hash for cache invalidation
```

---

## NEW MODULES DEEP DIVE

### 1. Evidence Infrastructure (`src/er/evidence/`, `src/er/workspace/`)

```python
# EvidenceCard - Tracks provenance for every piece of evidence
@dataclass
class EvidenceCard:
    evidence_id: str          # Unique ID (e.g., "ev-1736...")
    source_type: str          # "10-K", "transcript", "news", "web"
    source_url: str | None
    content: str
    content_hash: str         # SHA256 for deduplication
    fetched_at: datetime
    relevance_score: float
    confidence: float
    metadata: dict

# WorkspaceStore - Central evidence repository
class WorkspaceStore:
    def add_evidence(self, card: EvidenceCard) -> str
    def get_evidence(self, evidence_id: str) -> EvidenceCard | None
    def search_evidence(self, query: str, top_k: int) -> list[EvidenceCard]
    def get_all_by_source(self, source_type: str) -> list[EvidenceCard]
```

**POTENTIAL ISSUES:**
- WorkspaceStore is in-memory only - no persistence between runs
- Content hash doesn't include source URL, so same content from different sources looks like duplicate
- No TTL/eviction policy for large runs

### 2. Indexing System (`src/er/indexing/`)

```python
# TranscriptIndex - BM25 retrieval for earnings calls
class TranscriptIndex:
    K1 = 1.5  # BM25 term frequency saturation
    B = 0.75  # BM25 length normalization

    def add_transcript(self, content: str, quarter: str, year: int, ...)
    def retrieve_excerpts(self, query: str, top_k: int = 5) -> list[TranscriptExcerpt]
    def get_by_speaker(self, speaker: str, top_k: int = 10) -> list[TranscriptExcerpt]
    def get_qa_section(self, quarter: str | None = None) -> list[TranscriptExcerpt]

# FilingIndex - BM25 retrieval for SEC filings
class FilingIndex:
    def add_filing(self, content: str, filing_type: str, filing_date: date, ...)
    def retrieve_excerpts(self, query: str, top_k: int = 5, ...) -> list[FilingExcerpt]
    def get_risk_factors(self, top_k: int = 10) -> list[FilingExcerpt]
    def get_mda_excerpts(self, query: str | None = None, ...) -> list[FilingExcerpt]
```

**POTENTIAL ISSUES:**
- BM25 implementation is from scratch, not using established libraries (rank_bm25)
- No stemming/lemmatization - exact token match only
- Chunking strategy (500 tokens, 50 overlap) may split important context
- Section detection regex may miss non-standard SEC filing formats

### 3. Verification System (`src/er/verification/`)

```python
# ClaimGraph - Tracks claims and their evidence links
@dataclass
class ClaimNode:
    claim_id: str
    text: str
    claim_type: ClaimType  # FACT, INFERENCE, FORECAST, OPINION
    supporting_evidence: list[str]  # Evidence IDs
    linked_facts: list[str]  # Fact IDs

class ClaimGraphBuilder:
    def build_from_text(self, text: str, ticker: str = "") -> ClaimGraph
    def link_facts_to_claims(self, graph: ClaimGraph, facts: list[Fact])
    def link_evidence_to_claims(self, graph: ClaimGraph, evidence_texts: list[str])

# EntailmentVerifier - NLI-style verification
class EntailmentVerifier:
    async def verify_claim(self, claim: ClaimNode, evidence_texts: list[str]) -> EntailmentResult
    async def verify_claim_graph(self, graph: ClaimGraph, ...) -> EntailmentReport
```

**POTENTIAL ISSUES:**
- Claim extraction uses regex, not actual NLP - will miss complex claims
- Entailment verification is semantic similarity based, not true NLI
- No handling of numerical claims (e.g., "revenue grew 10%" needs number parsing)
- `verify_claim` is async but blocking - no actual parallelization

### 4. Confidence Calibration (`src/er/confidence/`)

```python
# EvidenceTierPolicy - Assigns credibility tiers
class EvidenceTierPolicy:
    SOURCE_TYPE_TIERS = {
        "10-k": SourceTier.TIER_1,
        "10-q": SourceTier.TIER_1,
        "transcript": SourceTier.TIER_1,
        "press_release": SourceTier.TIER_2,
        "news": SourceTier.TIER_3,
        "social": SourceTier.TIER_4,
    }
    TRUSTED_DOMAINS = ["sec.gov", "reuters.com", "bloomberg.com", ...]

    def assign_tier(self, source_url: str, source_type: str, ...) -> TierAssignment

# ConfidenceCalibrator - Systematic confidence scoring
class ConfidenceCalibrator:
    TIER_MULTIPLIERS = {TIER_1: 1.0, TIER_2: 0.85, TIER_3: 0.7, TIER_4: 0.5}
    RECENCY_DECAY_RATE = 0.01  # Per day
    CORROBORATION_BONUS = 0.05  # Per additional source
    ENTAILMENT_MULTIPLIERS = {SUPPORTED: 1.0, WEAK: 0.7, ...}

    def calibrate_claim(self, claim, source_tier, recency_days, ...) -> float
```

**POTENTIAL ISSUES:**
- Multipliers are hardcoded, not learned from data
- Recency decay is linear, should probably be exponential
- No sector-specific adjustments (tech vs utilities have different dynamics)
- TIER_4 (social media) at 0.5x may be too high - should probably be 0.1x

### 5. Valuation Engine (`src/er/valuation/`)

```python
# DCFEngine - Deterministic DCF calculation
class DCFEngine:
    def calculate_wacc(self, inputs: WACCInputs) -> float
    def calculate_dcf(self, inputs: DCFInputs, ...) -> DCFResult
    def sensitivity_analysis(self, inputs, ..., wacc_range, tg_range) -> SensitivityTable

# ReverseDCFEngine - Implied growth calculation
class ReverseDCFEngine:
    def calculate_implied_growth(self, inputs: ReverseDCFInputs) -> ReverseDCFResult
```

**POTENTIAL ISSUES:**
- No handling of negative free cash flow (growth companies)
- Terminal value calculation assumes perpetuity growth - may not suit all companies
- No multi-stage DCF (high growth → stable growth transition)
- Reverse DCF uses binary search - may not converge for extreme valuations

### 6. Peer Selection (`src/er/peers/`)

```python
# PeerSelector - Finds comparable companies
class PeerSelector:
    SIZE_BUCKETS = {"mega_cap": 200e9, "large_cap": 10e9, ...}

    def select_peers(self, ticker, sector, industry, market_cap, ...) -> PeerGroup
    def _score_candidate(self, candidate, target_sector, ...) -> tuple[float, PeerMatchQuality, list[str]]

# CompsAnalyzer - Valuation multiples comparison
class CompsAnalyzer:
    VALUATION_METRICS = ["pe_ratio", "ev_ebitda", "ev_revenue", ...]

    def analyze(self, target_metrics, peer_metrics) -> ComparableAnalysis
    def calculate_peer_relative_score(self, target, peers) -> dict[str, float]
```

**POTENTIAL ISSUES:**
- Peer database is hardcoded with ~6 companies - needs real data source
- Scoring weights are arbitrary (40 for industry, 30 for market cap)
- No handling of conglomerates (which sector to use?)
- Missing geographic and business model similarity scoring

### 7. Security Hardening (`src/er/security/`)

```python
# InputSanitizer - Prompt injection defense
class InputSanitizer:
    INJECTION_PATTERNS = [
        (r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions?", ThreatLevel.HIGH),
        (r"DAN\s+mode", ThreatLevel.CRITICAL),
        (r"os\.(system|popen|exec)", ThreatLevel.CRITICAL),
        ...
    ]

    def sanitize(self, text: str, source: str = "unknown") -> SanitizationResult
    def is_safe_input(self, text: str) -> bool

def sanitize_evidence(evidence_text: str) -> str:
    """Convenience function for evidence sanitization."""
```

**POTENTIAL ISSUES:**
- Pattern matching is regex-based - can be bypassed with unicode tricks
- No sandboxing of code blocks - just pattern detection
- Severity comparison was broken (string vs numeric) - fixed but indicates insufficient testing
- MEDIUM threats allowed by default in non-strict mode

### 8. Evaluation Harness (`src/er/eval/`)

```python
# PinnedFixture - Frozen test data
@dataclass
class PinnedFixture:
    fixture_id: str
    ticker: str
    profile: dict[str, Any]
    financials: dict[str, Any]
    filings: list[dict[str, Any]]
    transcripts: list[dict[str, Any]]
    expected_claims: list[dict[str, Any]]
    expected_recommendation: str | None
    content_hash: str  # Integrity verification

# EvalHarness - Pipeline testing
class EvalHarness:
    MIN_RECALL = 0.7
    MIN_PRECISION = 0.5
    MIN_VERIFICATION_RATE = 0.6

    async def evaluate(self, fixture_id, actual_claims, ...) -> EvalResult
    def compare_results(self, baseline, current) -> dict  # Regression detection
```

**POTENTIAL ISSUES:**
- No actual fixtures created yet - just infrastructure
- Claim matching uses word overlap (Jaccard), not semantic similarity
- Thresholds (70% recall, 50% precision) are arbitrary
- No A/B testing support for prompt changes

### 9. Manifest Versioning (`src/er/manifest.py`)

```python
MANIFEST_VERSION = "2.0"
MIN_RESUME_VERSION = "2.0"

class RunManifest:
    version: str
    checkpoints: dict[str, str]  # phase → data hash
    input_hash: str  # For cache invalidation

    def can_resume(self) -> bool
    def invalidate_from_phase(self, phase: Phase) -> None
    def set_checkpoint(self, phase: Phase, data_hash: str) -> None
```

**POTENTIAL ISSUES:**
- Version "2.0" immediately breaks all existing runs (no migration path)
- Checkpoint hash doesn't include all relevant inputs (budget, model versions)
- `can_resume()` doesn't check if data sources are still available

---

## FRONTEND-BACKEND INTEGRATION

### CRITICAL CONTEXT
**The frontend was built BEFORE the institutional hardening.**

The Next.js dashboard was designed for the original 6-stage pipeline. It expects:
- Original stage names and data structures
- Original JSON output formats
- Original WebSocket/SSE events

**The hardening added 9 new modules** that the frontend knows nothing about:
- Verification stage (Stage 3.5)
- Confidence calibration
- Claim graphs
- Citation tracking
- New manifest fields
- New evidence structures

### Current State
```
frontend/                      # Next.js app (BUILT FOR OLD ARCHITECTURE)
├── src/app/page.tsx           # Main dashboard - expects OLD stages
├── src/components/            # UI components - expects OLD data shapes
│   ├── PipelineView.tsx       # Shows stage progression - WRONG STAGES?
│   ├── StageCard.tsx          # Individual stage display
│   └── ...
└── api/                       # Python API server (separate)
    └── server.py              # FastAPI/Flask - UPDATED?
```

### Known Integration Issues
1. **No API contract** - Frontend expects specific JSON structure, backend doesn't validate
2. **WebSocket vs polling** - Real-time updates unclear
3. **Error propagation** - Pipeline errors may not reach frontend cleanly
4. **Run state sync** - Multiple browser tabs could show stale state
5. **[NEW] Stage mismatch** - Frontend expects 6 stages, backend now has 7+
6. **[NEW] Data shape changes** - New fields (citations, confidence, evidence_ids) not in frontend
7. **[NEW] Manifest v2.0** - Frontend may not understand new manifest format
8. **[NEW] Verification display** - No UI for claim verification results
9. **[NEW] Evidence tracking** - No UI for evidence cards and provenance

---

## CRITICAL QUESTIONS FOR REVIEW

### 1. Architecture Validity
- Is the 7-stage pipeline correct? Should stages be reorganized?
- Is verification before synthesis the right order? Or should synthesis inform verification?
- Should confidence calibration be per-claim or per-fact?

### 2. Integration Gaps
- **WorkspaceStore ↔ TranscriptIndex** - Are they actually connected? Or running in parallel?
- **ClaimGraph ↔ ConfidenceCalibrator** - Does confidence flow back to claims?
- **DCFEngine ↔ Synthesis** - Is valuation actually used in reports?
- **Security ↔ Pipeline** - Is sanitization applied to all external inputs?

### 3. Data Flow Issues
- **Evidence IDs** - Are they consistent across modules? Or regenerated?
- **Checkpoint serialization** - Can we actually resume from checkpoints?
- **Cross-vertical linking** - Does CrossVerticalMap work with new verification?

### 4. Missing Components
- **Actual data sources** - Peer database is hardcoded
- **Pinned fixtures** - Infrastructure exists, no fixtures created
- **Frontend API** - Is it actually wired up?
- **Rate limiting** - No protection against API quota exhaustion
- **Retry logic** - What happens when LLM calls fail?

### 5. Bug Suspects
- **BM25 implementation** - Custom implementation vs battle-tested library
- **Entailment verification** - Async but not actually parallel
- **Reverse DCF convergence** - Binary search may not converge
- **Security regex** - Unicode bypass vulnerabilities

### 6. Performance Concerns
- **TranscriptIndex** - Full re-index on every run?
- **ClaimGraph** - O(n²) matching of claims to evidence?
- **WorkspaceStore** - In-memory only, grows unboundedly?

### 7. Test Coverage Gaps
- **Integration tests** - Do modules work together?
- **End-to-end tests** - Can we run a full pipeline?
- **Failure tests** - What happens when APIs fail?
- **Regression tests** - Will prompt changes break output?

---

## TOKEN FLOW (From Previous Review)

```json
{
  "total_cost_usd": 4.36,
  "total_input_tokens": 758832,
  "total_output_tokens": 43666,
  "by_agent": {
    "external_discovery": 2.05 (652K input) ← 47% of cost!
    "discovery": 0.35 (83K input)
    "synthesizer": 1.35 (combined)
    "judge": 0.62
  }
}
```

**Question:** Do the new indexes (Transcript, Filing) actually reduce token usage? Or add overhead?

---

## WHAT I NEED FROM YOU

### 1. Critical Assessment
- What's fundamentally wrong with this architecture?
- What would a senior ML engineer or quant researcher criticize?
- What will break in production?

### 2. Integration Audit
- Are the new modules actually connected to the pipeline?
- Is data flowing correctly between stages?
- Are there orphaned modules (code exists but isn't used)?

### 3. Bug Hunt
- What code patterns look buggy?
- What edge cases will fail?
- What race conditions exist?

### 4. Missing Pieces
- What obvious components are missing?
- What should exist but doesn't?
- What needs to be wired up?

### 5. Frontend-Backend Gaps
- Is the API contract defined?
- Will real-time updates work?
- What breaks when the frontend connects?

### 6. Test Quality Assessment
- Are the 379 tests actually testing the right things?
- What isn't tested that should be?
- Are there tests that pass but don't validate behavior?

### 7. Prioritized Fix List
Give me a ranked list of what to fix first:
1. **CRITICAL** - Will cause production failures
2. **HIGH** - Major functionality broken
3. **MEDIUM** - Works but wrong
4. **LOW** - Nice to have

---

## APPENDIX: Key Files to Review

**Core Types:**
- `src/er/types.py` (~2500 lines) - All dataclasses

**Pipeline:**
- `src/er/coordinator/pipeline.py` - Main orchestration

**New Modules (Priority Review):**
- `src/er/indexing/transcript_index.py` - BM25 implementation
- `src/er/verification/claim_graph.py` - Claim extraction
- `src/er/verification/entailment.py` - Entailment verification
- `src/er/confidence/calibration.py` - Confidence scoring
- `src/er/valuation/dcf.py` - DCF calculation
- `src/er/valuation/reverse_dcf.py` - Implied growth
- `src/er/security/sanitizer.py` - Injection defense
- `src/er/eval/harness.py` - Evaluation framework
- `src/er/manifest.py` - Versioning + checkpoints

**Tests:**
- `tests/test_*.py` (22 files, 379 tests)

---

Be direct and ruthless. I want to know what's broken, not validation that it looks nice.

---

## REQUIRED OUTPUT FORMAT

Your review MUST include:

### PART 1: Complete Diagnostic Report

Provide a comprehensive analysis covering:

1. **Architecture Issues** - Structural problems with the design
2. **Integration Failures** - Where modules don't connect properly
3. **Bug Identification** - Specific code that will fail and why
4. **Missing Implementations** - Code that exists but isn't wired up
5. **Frontend Breakage** - What's broken due to backend changes
6. **Test Coverage Gaps** - What isn't tested that should be
7. **Performance Bottlenecks** - What will be slow or resource-intensive
8. **Security Vulnerabilities** - Beyond the sanitizer, what's exposed

For each issue identified, provide:
- **Location**: File path and line numbers if possible
- **Severity**: CRITICAL / HIGH / MEDIUM / LOW
- **Impact**: What breaks when this fails
- **Root Cause**: Why this is wrong

### PART 2: Step-by-Step Fix Plan

For every issue in Part 1, provide:

```
## Fix #N: [Issue Title]
Severity: CRITICAL/HIGH/MEDIUM/LOW
Files: [list of files to modify]

### Problem
[Detailed explanation of what's wrong]

### Solution
[Exact steps to fix, including code snippets if helpful]

### Verification
[How to verify the fix works - test to write, command to run]

### Dependencies
[Other fixes that must come before/after this one]
```

### PART 3: Prioritized Implementation Order

Provide a numbered list of fixes in the order they should be implemented:

1. Fix critical blockers first (things that prevent the system from running)
2. Fix integration issues (connect orphaned modules)
3. Fix data flow issues (ensure data reaches where it needs to go)
4. Fix frontend compatibility
5. Fix edge cases and robustness
6. Add missing tests

### PART 4: Frontend Remediation Plan

Specifically for the frontend:

1. **API Contract Definition** - What the new API should look like
2. **Data Shape Changes** - New TypeScript interfaces needed
3. **New Components** - UI for verification, evidence, confidence
4. **Stage Updates** - How to display the new pipeline stages
5. **Migration Strategy** - How to update without breaking existing functionality

### PART 5: Testing Strategy

1. **Unit Tests to Add** - Specific functions that need tests
2. **Integration Tests to Add** - Module combinations to test
3. **End-to-End Tests to Add** - Full pipeline scenarios
4. **Regression Tests to Add** - Prevent future breakage

---

I expect a thorough, actionable response. Vague recommendations like "improve error handling" are not acceptable. Tell me exactly what's wrong, where, and how to fix it.
