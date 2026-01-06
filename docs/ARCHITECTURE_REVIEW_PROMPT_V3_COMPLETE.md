# Equity Research Pipeline - Complete Architecture Audit & Remediation Prompt (V3)

You are an expert in multi-agent LLM systems, context engineering, financial research automation, and production Python systems. I need your **ruthless, complete review** of my equity research pipeline architecture, followed by **detailed step-by-step fixes** for every issue found.

---

## EXECUTIVE SUMMARY

### Original Problems (Before Hardening)
A 6-stage equity research pipeline that suffered from:

1. **Context loss across stage handoffs** - Later agents only see prose, not sources/data
2. **Web discovery blind spots** - Knowledge-cutoff priors, missing recent developments
3. **No pre-synthesis verification loop** - Errors propagate unchecked
4. **External discovery token/cost explosion** - LLM web_search returning full pages ($2.05/run, 47% of total cost)
5. **Weak holistic integration** - Vertical agents don't share a business model map
6. **Evidence not linked to claims** - EvidenceStore exists but web-derived evidence not persisted or linked

### What We Built (15-Phase Institutional Hardening)

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

## CRITICAL QUESTION: ARE THE ORIGINAL PROBLEMS ACTUALLY FIXED?

### PROBLEM 1: Context Loss Across Stage Handoffs
**Original Issue:** Later agents only see prose, not sources/data

**What Was Built:**
- `ThreadBrief` dataclass with `rationale`, `hypotheses`, `key_evidence_ids`
- `VerticalDossier` with `facts[]` containing `evidence_ids`
- `WorkspaceStore` for artifact persistence

**VERIFY THIS IS ACTUALLY WORKING:**
- [ ] Does `ThreadBrief` actually propagate evidence IDs to vertical analysts?
- [ ] Do vertical analysts actually USE the evidence IDs from discovery?
- [ ] Is `WorkspaceStore` actually populated during pipeline runs?
- [ ] Can Stage 4 (synthesis) actually access evidence from Stage 2?

### PROBLEM 2: Web Discovery Blind Spots
**Original Issue:** Knowledge-cutoff priors, missing recent developments

**What Was Built:**
- `RecencyGuard` - validates all data is recent
- `TranscriptIndex` + `FilingIndex` - BM25 retrieval for recent content
- `CoverageAuditor` - validates discovery covers all categories

**VERIFY THIS IS ACTUALLY WORKING:**
- [ ] Is `RecencyGuard` actually called in the pipeline?
- [ ] Is `CoverageAuditor` actually called in the pipeline?
- [ ] Do the indexes actually get populated before discovery runs?
- [ ] Does external discovery actually use the indexes?

### PROBLEM 3: No Pre-Synthesis Verification Loop
**Original Issue:** Errors propagate unchecked

**What Was Built:**
- `VerificationAgent` in `src/er/agents/verifier.py`
- `IntegratorAgent` in `src/er/agents/integrator.py`
- `ClaimGraphBuilder` + `EntailmentVerifier`
- `ConfidenceCalibrator`

**VERIFY THIS IS ACTUALLY WORKING:**
- [ ] Is `VerificationAgent` actually called between Stage 3 and Stage 4?
- [ ] Does the pipeline actually have a Stage 3.5/3.75?
- [ ] Does `ClaimGraph` output actually flow to synthesizer?
- [ ] Does `ConfidenceCalibrator` output actually modify claim confidence?

### PROBLEM 4: External Discovery Token Explosion
**Original Issue:** $2.05/run (47% of total cost) from full-page web_search

**What Was Built:**
- `WebResearchService` with URL discovery + fetch + summarize
- `EvidenceCards` for bounded summaries (<500 tokens)
- `SearchProvider` protocol with quota limits

**VERIFY THIS IS ACTUALLY WORKING:**
- [ ] Does `ExternalDiscoveryAgent` actually use `WebResearchService`?
- [ ] Is Claude `web_search` tool actually disabled?
- [ ] Are `EvidenceCards` being generated and used?
- [ ] What is the actual token usage now vs before?

### PROBLEM 5: Weak Holistic Integration
**Original Issue:** Vertical agents don't share a business model map

**What Was Built:**
- `IntegratorAgent` producing `CrossVerticalMap`
- `synergies`, `tensions`, `shared_risks`, `scenario_drivers`

**VERIFY THIS IS ACTUALLY WORKING:**
- [ ] Is `IntegratorAgent` actually called?
- [ ] Does `CrossVerticalMap` actually get passed to synthesizer?
- [ ] Does synthesizer prompt actually reference the integration?

### PROBLEM 6: Evidence Not Linked to Claims
**Original Issue:** EvidenceStore exists but evidence not linked

**What Was Built:**
- `EvidenceCard` with `evidence_id`, `source_url`, `content_hash`
- `Fact` dataclass with `evidence_ids` list
- `Claim` dataclass with `supporting_facts` list
- `ClaimGraph` linking claims to facts to evidence

**VERIFY THIS IS ACTUALLY WORKING:**
- [ ] Do `Fact` objects actually have populated `evidence_ids`?
- [ ] Does the synthesizer actually produce citations?
- [ ] Can we trace from a claim → fact → evidence → source URL?
- [ ] Is there an evidence index in the output?

---

## KNOWN BUGS AND ISSUES (ALREADY IDENTIFIED)

### BUG 1: Undefined Variable on Line 775 (CRITICAL)
**File:** `src/er/coordinator/pipeline.py:775`
**Code:** `discovery,` (should be `discovery_output`)
**Impact:** Will cause `NameError` when judge rejects both syntheses
**Status:** NOT FIXED

### BUG 2: Missing `Scenario` Type
**File:** `src/er/types.py`
**Issue:** `Scenario` is referenced but never defined
**Impact:** Import errors if code path is hit
**Status:** NOT FIXED

### BUG 3: 6 Orphaned Modules NOT Wired to Pipeline
The following modules were created but are NOT imported or called in `pipeline.py`:

| Module | Location | Purpose | Status |
|--------|----------|---------|--------|
| `confidence/` | `src/er/confidence/` | ConfidenceCalibrator, EvidenceTierPolicy | NOT WIRED |
| `verification/` | `src/er/verification/` | ClaimGraph, EntailmentVerifier | NOT WIRED |
| `indexing/` | `src/er/indexing/` | TranscriptIndex, FilingIndex | NOT WIRED |
| `analysis/` | `src/er/analysis/` | Financial analysis utilities | NOT WIRED |
| `security/` | `src/er/security/` | InputSanitizer, prompt injection defense | NOT WIRED |
| `utils/` | `src/er/utils/` | Text chunking, utilities | NOT WIRED |

### BUG 4: 3 Agents Created But Never Called
| Agent | File | Purpose | Status |
|-------|------|---------|--------|
| `RecencyGuard` | `src/er/agents/recency_guard.py` | Block stale data | NEVER CALLED |
| `CoverageAuditor` | `src/er/agents/coverage_auditor.py` | Validate coverage | NEVER CALLED |
| `TranscriptExtractor` | `src/er/agents/transcript_extractor.py` | Extract transcripts | NEVER CALLED |

### BUG 5: Incomplete Checkpoint/Resume for New Stages
**Issue:** Stage 3.5 (verification) and Stage 3.75 (integration) checkpoints may not be properly saved/loaded
**Impact:** Resume from checkpoint may skip verification entirely

### BUG 6: ThreatLevel Severity Comparison (FIXED)
**File:** `src/er/security/sanitizer.py`
**Issue:** Was comparing string values alphabetically ("critical" < "high")
**Status:** FIXED - Added numeric `severity` property

---

## CODEBASE OVERVIEW

```
equity-research/
├── src/er/                    # ~87 Python files, ~28K lines
│   ├── agents/                # LLM agents
│   │   ├── discovery.py       # Internal discovery (GPT)
│   │   ├── external_discovery.py # External discovery (Claude)
│   │   ├── vertical_analyst.py   # Deep research (o4-mini)
│   │   ├── synthesizer.py     # Report synthesis (Claude Opus + GPT)
│   │   ├── judge.py           # Synthesis judgment (Claude Opus)
│   │   ├── verifier.py        # [NEW] Fact verification
│   │   ├── integrator.py      # [NEW] Cross-vertical integration
│   │   ├── recency_guard.py   # [NEW] Stale data blocker - NOT WIRED
│   │   ├── coverage_auditor.py # [NEW] Coverage validator - NOT WIRED
│   │   └── transcript_extractor.py # [NEW] - NOT WIRED
│   ├── confidence/            # [NEW] - NOT WIRED TO PIPELINE
│   │   ├── calibration.py     # ConfidenceCalibrator
│   │   └── tier_policy.py     # EvidenceTierPolicy
│   ├── verification/          # [NEW] - NOT WIRED TO PIPELINE
│   │   ├── claim_graph.py     # ClaimGraphBuilder
│   │   └── entailment.py      # EntailmentVerifier
│   ├── indexing/              # [NEW] - NOT WIRED TO PIPELINE
│   │   ├── transcript_index.py # BM25 transcript retrieval
│   │   └── filing_index.py    # BM25 filing retrieval
│   ├── valuation/             # [NEW] - Partially wired
│   │   ├── dcf.py             # DCFEngine
│   │   └── reverse_dcf.py     # ReverseDCFEngine
│   ├── peers/                 # [NEW] - Partially wired
│   │   ├── selector.py        # PeerSelector
│   │   └── comps.py           # CompsAnalyzer
│   ├── security/              # [NEW] - NOT WIRED TO PIPELINE
│   │   └── sanitizer.py       # InputSanitizer
│   ├── eval/                  # [NEW] - Infrastructure only
│   │   ├── harness.py         # EvalHarness
│   │   └── fixtures.py        # PinnedFixture
│   ├── workspace/             # Evidence management
│   │   └── store.py           # WorkspaceStore
│   ├── evidence/              # Evidence cards + scoring
│   ├── coordinator/           # Pipeline orchestration
│   │   └── pipeline.py        # MAIN PIPELINE - Where things get wired
│   ├── types.py               # Core dataclasses (~2500 lines)
│   └── manifest.py            # [ENHANCED] Run manifest with versioning
├── frontend/                  # Next.js dashboard - BUILT FOR OLD ARCHITECTURE
│   ├── src/app/page.tsx       # Main dashboard
│   └── src/components/        # UI components
├── tests/                     # 22 test files, 379 tests
└── docs/                      # Documentation
```

---

## FRONTEND-BACKEND CRITICAL MISMATCH

### THE CORE PROBLEM
**The frontend was built BEFORE the institutional hardening.**

The Next.js dashboard expects:
- **6 stages** - Backend now has 7+ (added verification, integration)
- **Original data shapes** - New fields (citations, confidence, evidence_ids) not in TypeScript types
- **Original stage names** - New stages have different names
- **Original manifest format** - Manifest v2.0 has new fields

### What Frontend Expects vs What Backend Produces

| Field | Frontend Expects | Backend Produces | Status |
|-------|------------------|------------------|--------|
| Stages | 6 | 7+ | MISMATCH |
| Stage names | original | new names | MISMATCH |
| Claim confidence | N/A | 0.0-1.0 float | MISSING |
| Evidence IDs | N/A | UUID strings | MISSING |
| Citations | N/A | `[ev-xxx]` markers | MISSING |
| Verification status | N/A | SUPPORTED/WEAK/etc | MISSING |
| Manifest version | "1.0" | "2.0" | MISMATCH |

### Frontend Files That Need Updates

1. **`frontend/src/app/page.tsx`** - Main dashboard, stage progression
2. **`frontend/src/components/PipelineView.tsx`** - Stage display
3. **`frontend/src/components/StageCard.tsx`** - Individual stage cards
4. **TypeScript interfaces** - Need new types for verification, confidence, evidence

---

## ARCHITECTURE FLOW (What SHOULD Happen)

```
STAGE 1: Data Collection (No LLM)
├── FMP API → CompanyContext (~11K tokens)
├── [NEW] RecencyGuard ← NOT WIRED
│   └── Block stale data from entering pipeline
├── [NEW] TranscriptIndex + FilingIndex ← NOT WIRED
│   └── BM25-indexed excerpts for retrieval
└── [NEW] InputSanitizer ← NOT WIRED
    └── Sanitize all external input

STAGE 2: Discovery (PARALLEL)
├── Internal Discovery (GPT)
│   └── [SHOULD] Use TranscriptIndex for excerpts
├── External Discovery (Claude)
│   └── [SHOULD] Use FilingIndex for risk factors
└── [NEW] CoverageAuditor ← NOT WIRED
    └── Validate all 8 categories covered

STAGE 3: Deep Research (PARALLEL)
├── Vertical Analyst (o4-mini)
│   └── [SHOULD] Produce Facts[] with evidence_ids
├── [NEW] ClaimGraphBuilder ← NOT WIRED
│   └── Extract claims from analysis
└── [NEW] EntailmentVerifier ← NOT WIRED
    └── Verify claims against evidence

STAGE 3.5: Verification (NEW) ← PARTIALLY IMPLEMENTED
├── VerificationAgent
│   └── Cross-reference facts against ground truth
├── [NEW] ConfidenceCalibrator ← NOT WIRED
│   └── Adjust confidence by source tier
└── IntegratorAgent
    └── Build CrossVerticalMap

STAGE 4: Synthesis (PARALLEL)
├── Claude Synthesis
│   └── [SHOULD] Cite evidence IDs
├── GPT Synthesis
│   └── [SHOULD] Cite evidence IDs
└── [NEW] ReportCompiler
    └── Structure report, link citations

STAGE 5: Judge
├── Judge Agent (Claude Opus)
│   └── [SHOULD] Check citation validity
└── [NEW] PeerSelector + CompsAnalyzer
    └── Validate valuation against peers

STAGE 6: Valuation (NEW)
├── [NEW] DCFEngine
│   └── Deterministic DCF calculation
└── [NEW] ReverseDCFEngine
    └── Implied growth from market price

STAGE 7: Output
└── [NEW] Manifest v2.0
    └── Schema versioning, checkpoints
```

---

## WHAT I NEED FROM YOU

### PART 1: Original Problems Audit
For each of the 6 original problems listed above:
1. **Is it actually fixed?** (YES/NO/PARTIAL)
2. **What evidence supports your assessment?** (code paths, imports, test coverage)
3. **What's still broken?** (specific gaps)
4. **What needs to be done to fully fix it?** (concrete steps)

### PART 2: Complete Bug Inventory
Beyond the known bugs, find:
1. **All code paths that will throw exceptions**
2. **All undefined references** (like `discovery` on line 775)
3. **All orphaned code** (exists but never called)
4. **All data that never flows where it should**
5. **All async functions that block instead of parallelize**

### PART 3: Integration Audit
Answer these specific questions:
1. Does `pipeline.py` import `confidence/`? (It doesn't - verify)
2. Does `pipeline.py` import `verification/`? (It doesn't - verify)
3. Does `pipeline.py` import `indexing/`? (It doesn't - verify)
4. Does `pipeline.py` import `security/`? (It doesn't - verify)
5. Where exactly should these be wired in?

### PART 4: Step-by-Step Fix Plan
For EVERY issue found, provide:

```
## Fix #N: [Issue Title]
Severity: CRITICAL/HIGH/MEDIUM/LOW
Files: [list of files to modify]

### Problem
[Detailed explanation of what's wrong]

### Solution
[Exact steps to fix, including:]
1. What to import
2. Where to call it
3. How to pass data
4. Code snippet if helpful

### Verification
[How to verify the fix works]
- Test to write
- Command to run
- Expected output

### Dependencies
[Other fixes that must come before/after]
```

### PART 5: Frontend Remediation Plan
1. **API Contract** - Define exact JSON shapes backend will produce
2. **TypeScript Types** - New interfaces for verification, evidence, confidence
3. **New Components** - UI for new stages and data
4. **Migration Strategy** - How to update without breaking

### PART 6: Prioritized Implementation Order
Number every fix in order of implementation:
1. Critical blockers (system won't run)
2. Integration gaps (orphaned modules)
3. Data flow issues (data doesn't reach destination)
4. Frontend compatibility
5. Edge cases and robustness
6. Test coverage

---

## APPENDIX A: Key Files to Review

**MUST READ:**
- `src/er/coordinator/pipeline.py` - Main orchestration, where wiring happens
- `src/er/types.py` - All dataclasses, see what exists

**NEW MODULES (Check if wired):**
- `src/er/confidence/calibration.py`
- `src/er/verification/claim_graph.py`
- `src/er/verification/entailment.py`
- `src/er/indexing/transcript_index.py`
- `src/er/indexing/filing_index.py`
- `src/er/security/sanitizer.py`
- `src/er/eval/harness.py`

**AGENTS (Check if called):**
- `src/er/agents/recency_guard.py`
- `src/er/agents/coverage_auditor.py`
- `src/er/agents/verifier.py`
- `src/er/agents/integrator.py`

**FRONTEND:**
- `frontend/src/app/page.tsx`
- `frontend/src/components/`

---

## APPENDIX B: Tests to Verify

```bash
# Run all tests
cd /Users/isaacentebi/equity-research && pytest -v

# Check if pipeline imports new modules
grep -n "from er.confidence" src/er/coordinator/pipeline.py
grep -n "from er.verification" src/er/coordinator/pipeline.py
grep -n "from er.indexing" src/er/coordinator/pipeline.py
grep -n "from er.security" src/er/coordinator/pipeline.py

# Check if agents are called
grep -n "RecencyGuard" src/er/coordinator/pipeline.py
grep -n "CoverageAuditor" src/er/coordinator/pipeline.py
grep -n "ConfidenceCalibrator" src/er/coordinator/pipeline.py

# Check the bug on line 775
sed -n '770,780p' src/er/coordinator/pipeline.py

# Verify CLI still works
er analyze --dry-run AAPL
```

---

## APPENDIX C: Token Flow Reference

From previous runs:
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

**QUESTION:** If WebResearchService + EvidenceCards are wired correctly, external_discovery cost should drop dramatically. Is this happening?

---

## REQUIRED OUTPUT FORMAT

Your response MUST include ALL of the following sections:

### SECTION 1: Original Problems Assessment
| Problem | Fixed? | Evidence | Remaining Gaps |
|---------|--------|----------|----------------|
| 1. Context loss | YES/NO/PARTIAL | ... | ... |
| 2. Discovery blind spots | YES/NO/PARTIAL | ... | ... |
| 3. No verification loop | YES/NO/PARTIAL | ... | ... |
| 4. Token explosion | YES/NO/PARTIAL | ... | ... |
| 5. Weak integration | YES/NO/PARTIAL | ... | ... |
| 6. Evidence not linked | YES/NO/PARTIAL | ... | ... |

### SECTION 2: Complete Bug List
Numbered list of every bug found with file:line locations

### SECTION 3: Orphaned Code Inventory
Every module/function that exists but isn't wired

### SECTION 4: Step-by-Step Fix Plan
Using the format specified above, with code snippets

### SECTION 5: Frontend Remediation
Complete plan with TypeScript types

### SECTION 6: Prioritized Fix Order
Numbered list in implementation order

### SECTION 7: Test Coverage Gaps
What tests need to be added

---

Be ruthless. I want to know what's broken, not validation that it looks nice. Every claim must be backed by specific file paths and line numbers.
