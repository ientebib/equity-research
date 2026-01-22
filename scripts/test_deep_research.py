#!/usr/bin/env python3
"""
Test Stage 3 (Deep Research) using saved Discovery output.
Loads Discovery threads from JSON and runs Deep Research stage.

Usage:
    PYTHONPATH=./src python3 scripts/test_deep_research.py
"""
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

# Load .env file manually
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value

load_env()

# Input: Discovery output from test_discovery_transcripts.py
DISCOVERY_OUTPUT = Path("./output/transcript_test/stage2_discovery.json")
OUTPUT_DIR = Path("./output/deep_research_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def verify_env():
    """Verify required environment variables are set."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    fmp_key = os.environ.get("FMP_API_KEY", "")

    print("=" * 70)
    print("ENVIRONMENT CHECK")
    print("=" * 70)
    print(f"ANTHROPIC_API_KEY: {'SET (' + anthropic_key[:8] + '...)' if anthropic_key else 'MISSING'}")
    print(f"FMP_API_KEY: {'SET (' + fmp_key[:8] + '...)' if fmp_key else 'MISSING'}")

    if not anthropic_key:
        print("\nERROR: ANTHROPIC_API_KEY required for Deep Research")
        return False
    return True


async def run_deep_research():
    from er.evidence.store import EvidenceStore
    from er.data.fmp_client import FMPClient
    from er.data.transcript_loader import load_transcripts
    from er.types import CompanyContext
    from er.coordinator.anthropic_sdk_agent import ResearchPipeline, DiscoveredThread

    # Load Discovery output
    print("\n" + "=" * 70)
    print("LOADING DISCOVERY OUTPUT")
    print("=" * 70)

    if not DISCOVERY_OUTPUT.exists():
        print(f"ERROR: Discovery output not found at {DISCOVERY_OUTPUT}")
        print("Run test_discovery_transcripts.py first")
        return

    discovery_data = json.loads(DISCOVERY_OUTPUT.read_text())
    print(f"  Ticker: {discovery_data['ticker']}")
    print(f"  Threads: {len(discovery_data.get('research_threads', []))}")

    # Convert JSON threads to DiscoveredThread objects
    threads = []
    for t in discovery_data.get("research_threads", []):
        threads.append(DiscoveredThread(
            thread_name=t["name"],  # JSON uses 'name', SDK uses 'thread_name'
            priority=t["priority"],
            thread_type=t["thread_type"],
            value_driver_hypothesis=t["value_driver_hypothesis"],
            research_questions=t["research_questions"],
        ))

    print(f"\n  Converted {len(threads)} threads to DiscoveredThread format")
    for i, t in enumerate(threads[:5], 1):
        print(f"    {i}. [P{t.priority}] {t.thread_name}")
    if len(threads) > 5:
        print(f"    ... and {len(threads) - 5} more")

    # ==========================================
    # Fetch fresh company context (needed for Deep Research)
    # ==========================================
    print("\n" + "=" * 70)
    print("FETCHING COMPANY CONTEXT")
    print("=" * 70)

    ticker = discovery_data["ticker"]
    evidence_store = EvidenceStore(OUTPUT_DIR / "evidence")
    await evidence_store.init()

    fmp = FMPClient(evidence_store)
    company_context = await fmp.get_full_context(ticker)

    # Load local transcripts
    local_transcripts = load_transcripts(ticker)
    if local_transcripts:
        print(f"  Loaded {len(local_transcripts)} local transcripts")
        existing = {(t.get("quarter"), t.get("year")): t for t in company_context.get("transcripts", [])}
        for t in local_transcripts:
            existing[(t["quarter"], t["year"])] = t
        company_context["transcripts"] = sorted(
            list(existing.values()),
            key=lambda x: (x.get("year", 0), x.get("quarter", 0)),
            reverse=True,
        )

    profile = company_context.get("profile", {})
    print(f"  Company: {profile.get('companyName', 'N/A')}")
    print(f"  Market Cap: ${profile.get('mktCap', 0):,.0f}")
    print(f"  Transcripts: {len(company_context.get('transcripts', []))}")

    # ==========================================
    # Run Deep Research Stage
    # ==========================================
    print("\n" + "=" * 70)
    print("[STAGE 3] Running Deep Research...")
    print("  (This will take 10-20 minutes with web searches)")
    print("=" * 70)

    # Create ResearchPipeline with output directory
    agent = ResearchPipeline(
        output_dir=OUTPUT_DIR,
        max_threads=min(len(threads), 4),  # Limit to 4 threads for test
    )
    agent._evidence_store = evidence_store

    # Store discovery data so _stage_research can access lens_outputs, threats, etc.
    # We need to reconstruct a minimal DiscoveryOutput-like object
    from types import SimpleNamespace
    agent._discovery_output = SimpleNamespace(
        research_threads=[],  # Already converted to local threads
        lens_outputs=discovery_data.get("lens_outputs", {}),
        external_threats=discovery_data.get("external_threats", []),
        searches_performed=discovery_data.get("searches_performed", []),
        research_groups=discovery_data.get("research_groups", []),
    )

    # Run Deep Research (Stage 3)
    start_time = datetime.now()
    research_findings = await agent._stage_research(
        ticker=ticker,
        threads=threads[:4],  # Limit to top 4 threads for test
        company_context=company_context,
    )
    elapsed = (datetime.now() - start_time).total_seconds()

    # Save results
    findings_data = {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": elapsed,
        "threads_researched": len(threads[:4]),
        "findings": [
            {
                "thread_name": f.thread.thread_name if f.thread else "Unknown",
                "key_findings": f.key_findings,
                "bull_case": f.bull_case,
                "bear_case": f.bear_case,
                "data_points": f.data_points,
                "sources": f.sources,
            }
            for f in research_findings
        ],
    }
    (OUTPUT_DIR / "stage3_research.json").write_text(json.dumps(findings_data, indent=2, default=str))

    await evidence_store.close()

    # Print summary
    print("\n" + "=" * 70)
    print("DEEP RESEARCH RESULTS")
    print("=" * 70)
    print(f"\nCompleted in {elapsed:.0f} seconds ({elapsed/60:.1f} minutes)")
    print(f"\nResearched {len(research_findings)} threads:")

    for i, f in enumerate(research_findings, 1):
        thread_name = f.thread.thread_name if f.thread else "Unknown"
        print(f"\n  {i}. {thread_name}")
        print(f"     Key findings: {len(f.key_findings)}")
        if f.key_findings:
            first = f.key_findings[0]
            if isinstance(first, dict):
                first = first.get('finding', str(first))[:100]
            else:
                first = str(first)[:100]
            print(f"     First finding: {first}...")

    print("\n" + "=" * 70)
    print("OUTPUT FILES:")
    print("=" * 70)
    for f in OUTPUT_DIR.glob("*.json"):
        print(f"  {f.name}: {f.stat().st_size:,} bytes")

    return research_findings


if __name__ == "__main__":
    if verify_env():
        asyncio.run(run_deep_research())
    else:
        print("\nFix environment variables and retry.")
