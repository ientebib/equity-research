#!/usr/bin/env python3
"""
Test Stage 4 (Synthesis) using saved Deep Research output.
Loads research findings from JSON and generates equity research report.

Usage:
    PYTHONPATH=./src python3 scripts/test_synthesis.py
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

# Input: Deep Research output
RESEARCH_OUTPUT = Path("./output/deep_research_test/stage3_research.json")
DISCOVERY_OUTPUT = Path("./output/transcript_test/stage2_discovery.json")
OUTPUT_DIR = Path("./output/synthesis_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def verify_env():
    """Verify required environment variables are set."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    print("=" * 70)
    print("ENVIRONMENT CHECK")
    print("=" * 70)
    print(f"ANTHROPIC_API_KEY: {'SET (' + anthropic_key[:8] + '...)' if anthropic_key else 'MISSING'}")

    if not anthropic_key:
        print("\nERROR: ANTHROPIC_API_KEY required for Synthesis")
        return False
    return True


async def run_synthesis():
    from er.evidence.store import EvidenceStore
    from er.data.fmp_client import FMPClient
    from er.data.transcript_loader import load_transcripts
    from er.coordinator.anthropic_sdk_agent import ResearchPipeline, DiscoveredThread, ResearchFinding

    # Load Deep Research output
    print("\n" + "=" * 70)
    print("LOADING DEEP RESEARCH OUTPUT")
    print("=" * 70)

    if not RESEARCH_OUTPUT.exists():
        print(f"ERROR: Research output not found at {RESEARCH_OUTPUT}")
        print("Run test_deep_research.py first")
        return

    research_data = json.loads(RESEARCH_OUTPUT.read_text())
    print(f"  Ticker: {research_data['ticker']}")
    print(f"  Findings: {len(research_data.get('findings', []))}")

    # Load Discovery output for thread info
    discovery_data = json.loads(DISCOVERY_OUTPUT.read_text())

    # Build thread lookup
    thread_lookup = {}
    for t in discovery_data.get("research_threads", []):
        thread_lookup[t["name"]] = DiscoveredThread(
            thread_name=t["name"],
            priority=t["priority"],
            thread_type=t["thread_type"],
            value_driver_hypothesis=t["value_driver_hypothesis"],
            research_questions=t["research_questions"],
        )

    # Convert JSON findings to ResearchFinding objects
    findings = []
    for f in research_data.get("findings", []):
        thread_name = f["thread_name"]
        thread = thread_lookup.get(thread_name)
        if not thread:
            # Create a placeholder thread if not found
            thread = DiscoveredThread(
                thread_name=thread_name,
                priority=1,
                thread_type="SEGMENT",
                value_driver_hypothesis="",
                research_questions=[],
            )

        findings.append(ResearchFinding(
            thread=thread,
            key_findings=f.get("key_findings", []),
            bull_case=f.get("bull_case", ""),
            bear_case=f.get("bear_case", ""),
            data_points=f.get("data_points", []),
            sources=f.get("sources", []),
        ))

    print(f"\n  Converted {len(findings)} findings to ResearchFinding format")
    for i, f in enumerate(findings[:5], 1):
        print(f"    {i}. {f.thread.thread_name}")
    if len(findings) > 5:
        print(f"    ... and {len(findings) - 5} more")

    # ==========================================
    # Fetch fresh company context (needed for Synthesis)
    # ==========================================
    print("\n" + "=" * 70)
    print("FETCHING COMPANY CONTEXT")
    print("=" * 70)

    ticker = research_data["ticker"]
    evidence_store = EvidenceStore(OUTPUT_DIR / "evidence")
    await evidence_store.init()

    fmp = FMPClient(evidence_store)
    company_context = await fmp.get_full_context(ticker)

    profile = company_context.get("profile", {})
    print(f"  Company: {profile.get('companyName', 'N/A')}")
    print(f"  Market Cap: ${profile.get('mktCap', 0):,.0f}")

    # ==========================================
    # Run Synthesis Stage (Stage 4)
    # ==========================================
    print("\n" + "=" * 70)
    print("[STAGE 4] Running Synthesis...")
    print("  (This will take 2-5 minutes)")
    print("=" * 70)

    # Create ResearchPipeline with output directory
    agent = ResearchPipeline(output_dir=OUTPUT_DIR)
    agent._evidence_store = evidence_store

    # Run Synthesis (Stage 4)
    start_time = datetime.now()
    report = await agent._stage_synthesis(
        ticker=ticker,
        company_context=company_context,
        findings=findings,
    )
    elapsed = (datetime.now() - start_time).total_seconds()

    # Save report
    report_path = OUTPUT_DIR / "report.md"
    report_path.write_text(report)
    print(f"  Saved: report.md")

    await evidence_store.close()

    # Print summary
    print("\n" + "=" * 70)
    print("SYNTHESIS RESULTS")
    print("=" * 70)
    print(f"\nCompleted in {elapsed:.0f} seconds ({elapsed/60:.1f} minutes)")
    print(f"\nReport length: {len(report):,} characters")
    print(f"\nReport preview (first 2000 chars):")
    print("-" * 70)
    print(report[:2000])
    print("-" * 70)
    if len(report) > 2000:
        print(f"\n... (truncated, full report in {report_path})")

    print("\n" + "=" * 70)
    print("OUTPUT FILES:")
    print("=" * 70)
    for f in OUTPUT_DIR.glob("*"):
        if f.is_file():
            print(f"  {f.name}: {f.stat().st_size:,} bytes")

    return report


if __name__ == "__main__":
    if verify_env():
        asyncio.run(run_synthesis())
    else:
        print("\nFix environment variables and retry.")
