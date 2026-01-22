#!/usr/bin/env python3
"""
Test Stage 1 + Discovery with transcript integration.
Saves all outputs for review before running Deep Research.

Usage:
    export $(cat .env | xargs) && PYTHONPATH=./src python3 scripts/test_discovery_transcripts.py
"""
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("./output/transcript_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def verify_env():
    """Verify required environment variables are set."""
    fmp_key = os.environ.get("FMP_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    print("=" * 70)
    print("ENVIRONMENT CHECK")
    print("=" * 70)
    print(f"FMP_API_KEY: {'SET (' + fmp_key[:8] + '...)' if fmp_key else 'MISSING'}")
    print(f"ANTHROPIC_API_KEY: {'SET (' + anthropic_key[:8] + '...)' if anthropic_key else 'MISSING'}")

    if not fmp_key:
        print("\nWARNING: FMP_API_KEY not set - will only use local transcripts")
    if not anthropic_key:
        print("\nERROR: ANTHROPIC_API_KEY required for Discovery agent")
        return False
    return True


async def run_discovery_only():
    from er.evidence.store import EvidenceStore
    from er.data.fmp_client import FMPClient
    from er.data.transcript_loader import load_transcripts
    from er.types import CompanyContext
    from er.agents.discovery_anthropic import AnthropicDiscoveryAgent

    ticker = "GOOGL"

    print("\n" + "=" * 70)
    print(f"DISCOVERY TEST - {ticker}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    # ==========================================
    # STAGE 1: Data + Transcripts
    # ==========================================
    print("\n[STAGE 1] Fetching data + transcripts...")

    evidence_store = EvidenceStore(OUTPUT_DIR / "evidence")
    await evidence_store.init()

    fmp = FMPClient(evidence_store)
    full_context = await fmp.get_full_context(ticker)

    # Load local transcripts
    local_transcripts = load_transcripts(ticker)
    print(f"  Loaded {len(local_transcripts)} local transcripts")
    for t in local_transcripts:
        print(f"    - Q{t['quarter']} {t['year']}: {len(t['text'])} chars")

    # Merge transcripts (local override FMP)
    if local_transcripts:
        existing = {(t.get("quarter"), t.get("year")): t for t in full_context.get("transcripts", [])}
        for t in local_transcripts:
            existing[(t["quarter"], t["year"])] = t
        full_context["transcripts"] = sorted(
            list(existing.values()),
            key=lambda x: (x.get("year", 0), x.get("quarter", 0)),
            reverse=True,
        )

    # Print data summary
    profile = full_context.get("profile", {})
    print(f"\n  Company: {profile.get('companyName', 'N/A')}")
    print(f"  Sector: {profile.get('sector', 'N/A')}")
    print(f"  Market Cap: ${profile.get('mktCap', 0):,.0f}")
    print(f"  News items: {len(full_context.get('news', []))}")
    print(f"  Transcripts: {len(full_context.get('transcripts', []))}")
    print(f"  Evidence IDs: {len(full_context.get('evidence_ids', []))}")

    # Save Stage 1 output
    stage1_summary = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "profile": profile,
        "transcripts_count": len(full_context.get("transcripts", [])),
        "transcripts_quarters": [f"Q{t.get('quarter')} {t.get('year')}" for t in full_context.get("transcripts", [])],
        "news_count": len(full_context.get("news", [])),
        "evidence_ids": len(full_context.get("evidence_ids", [])),
    }
    (OUTPUT_DIR / "stage1_summary.json").write_text(json.dumps(stage1_summary, indent=2, default=str))
    print(f"\n  Saved: stage1_summary.json")

    # ==========================================
    # STAGE 2: Discovery
    # ==========================================
    print("\n" + "=" * 70)
    print("[STAGE 2] Running Discovery Agent...")
    print("  (This will take 5-10 minutes with web searches)")
    print("=" * 70)

    typed_context = CompanyContext.from_fmp_data(full_context)

    discovery_agent = AnthropicDiscoveryAgent(
        evidence_store=evidence_store,
        max_searches_per_subagent=5,
    )

    discovery_output = await discovery_agent.run(typed_context)

    # Save Discovery output
    discovery_data = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "research_threads": [
            {
                "name": t.name,  # Use 'name' to match DiscoveredThread field
                "thread_type": str(t.thread_type),
                "priority": t.priority,
                "value_driver_hypothesis": t.value_driver_hypothesis,
                "research_questions": list(t.research_questions),
                "discovery_lens": getattr(t, 'discovery_lens', None),
                "thread_id": t.thread_id,  # Include thread_id for tracing
                "is_official_segment": t.is_official_segment,
                "description": t.description,
            }
            for t in discovery_output.research_threads
        ],
        "research_groups": [
            {
                "group_id": g.group_id,
                "name": g.name,
                "theme": g.theme,
                "vertical_ids": g.vertical_ids,
                "key_questions": g.key_questions,
                "shared_context": g.shared_context,
                "grouping_rationale": g.grouping_rationale,
                "valuation_approach": g.valuation_approach,
            }
            for g in (discovery_output.research_groups or [])
        ],
        "external_threats": discovery_output.external_threats or [],
        "official_segments": discovery_output.official_segments or [],
        "searches_performed": discovery_output.searches_performed or [],
        "lens_outputs": discovery_output.lens_outputs or {},
    }
    (OUTPUT_DIR / "stage2_discovery.json").write_text(json.dumps(discovery_data, indent=2, default=str))
    print(f"  Saved: stage2_discovery.json")

    # Print summary
    print("\n" + "=" * 70)
    print("DISCOVERY RESULTS")
    print("=" * 70)
    print(f"\nFound {len(discovery_output.research_threads)} research threads:")
    for i, t in enumerate(discovery_output.research_threads, 1):
        print(f"\n  {i}. [Priority {t.priority}] {t.name}")
        print(f"     Type: {t.thread_type}")
        print(f"     Hypothesis: {t.value_driver_hypothesis[:100]}...")
        print(f"     Questions: {len(t.research_questions)}")
        if hasattr(t, 'discovery_lens') and t.discovery_lens:
            print(f"     Discovery Lens: {t.discovery_lens}")

    if discovery_output.external_threats:
        print(f"\nExternal Threats Identified: {len(discovery_output.external_threats)}")
        for threat in discovery_output.external_threats[:3]:
            name = threat.get('name', 'Unknown') if isinstance(threat, dict) else str(threat)
            print(f"  - {name}")

    if discovery_output.searches_performed:
        print(f"\nWeb Searches Performed: {len(discovery_output.searches_performed)}")
        for search in discovery_output.searches_performed[:5]:
            print(f"  - {search}")

    await evidence_store.close()

    print("\n" + "=" * 70)
    print("OUTPUT FILES:")
    print("=" * 70)
    for f in OUTPUT_DIR.glob("*.json"):
        print(f"  {f.name}: {f.stat().st_size:,} bytes")

    print("\n" + "=" * 70)
    print("NEXT STEPS:")
    print("=" * 70)
    print("  1. Review stage2_discovery.json for research threads")
    print("  2. Check if threads reference transcript sources")
    print("  3. If satisfied, run Deep Research on selected threads")

    return discovery_output


if __name__ == "__main__":
    if verify_env():
        asyncio.run(run_discovery_only())
    else:
        print("\nFix environment variables and retry.")
