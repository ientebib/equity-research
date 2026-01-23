# Architecture Status

**Generated:** 2026-01-06T16:33:56.198555
**Status:** ✅ ALL COMPONENTS PRESENT

## Component Checklist

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| WorkspaceStore | ✅ | `...ntebi/equity-research/src/er/workspace/store.py` |  |
| WebResearchService | ✅ | `...ebi/equity-research/src/er/retrieval/service.py` |  |
| EvidenceCard | ✅ | `...ity-research/src/er/retrieval/evidence_cards.py` |  |
| ThreadBrief | ✅ | `/Users/isaacentebi/equity-research/src/er/types.py` |  |
| VerticalDossier | ✅ | `/Users/isaacentebi/equity-research/src/er/types.py` |  |
| Fact | ✅ | `/Users/isaacentebi/equity-research/src/er/types.py` |  |
| VerificationAgent | ✅ | `...ntebi/equity-research/src/er/agents/verifier.py` |  |
| IntegratorAgent | ✅ | `...ebi/equity-research/src/er/agents/integrator.py` |  |
| VerifiedResearchPackage | ✅ | `/Users/isaacentebi/equity-research/src/er/types.py` |  |
| CrossVerticalMap | ✅ | `/Users/isaacentebi/equity-research/src/er/types.py` |  |
| Pipeline Wiring | ✅ | `src/er/coordinator/anthropic_sdk_agent.py` | Anthropic-only pipeline (pipeline.py deprecated) |
| Citation Support | ✅ | `synthesizer.py, judge.py` | Both synthesizer and judge accept verified_package |

## Architecture Overview

**Note:** This codebase is Anthropic-only. All agents use Claude models (Opus 4.5, Sonnet 4.5, Haiku).

```
Stage 1: Data Collection (Python/FMP)
    ↓
Stage 2: Discovery (Claude Sonnet - ThreadBriefs)
    ↓
Stage 3: Deep Research (Claude Sonnet - VerticalDossiers + Facts[])
    ↓
Stage 3.5: Verification (Claude Sonnet - VerifiedResearchPackage)
    ↓
Stage 3.75: Integration (Claude Sonnet - CrossVerticalMap)
    ↓
Stage 4: Synthesis (Claude Opus - with extended thinking)
    ↓
Stage 5: Judge (Claude Opus - reviews and scores)
    ↓
Stage 6: Revision (Claude Opus - final polish)
```
