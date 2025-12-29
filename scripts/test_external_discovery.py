#!/usr/bin/env python3
"""
Test External Discovery Agent in isolation.

This script loads existing CompanyContext from a checkpoint and runs
just the External Discovery agent to test prompt effectiveness.

Usage:
    python scripts/test_external_discovery.py --run-dir output/run_XXXX
    python scripts/test_external_discovery.py --ticker GOOGL
"""

import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from er.agents.base import AgentContext
from er.agents.external_discovery import ExternalDiscoveryAgent, ExternalDiscoveryOutput
from er.budget import BudgetTracker
from er.config import Settings
from er.evidence.store import EvidenceStore
from er.llm.router import LLMRouter
from er.types import CompanyContext, RunState


def load_company_context_from_checkpoint(run_dir: Path) -> CompanyContext:
    """Load CompanyContext from a checkpoint directory."""
    context_file = run_dir / "stage1_company_context.json"

    if not context_file.exists():
        raise FileNotFoundError(f"No company context found at {context_file}")

    with open(context_file) as f:
        data = json.load(f)

    # Convert fetched_at string to datetime
    if isinstance(data.get("fetched_at"), str):
        data["fetched_at"] = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))

    # Convert evidence_ids to tuple if list
    if isinstance(data.get("evidence_ids"), list):
        data["evidence_ids"] = tuple(data["evidence_ids"])

    return CompanyContext(**data)


def create_minimal_company_context(ticker: str) -> CompanyContext:
    """Create a minimal CompanyContext for testing without checkpoint."""
    # Hardcoded for GOOGL - extend as needed
    profiles = {
        "GOOGL": {
            "symbol": "GOOGL",
            "companyName": "Alphabet Inc.",
            "sector": "Technology",
            "industry": "Internet Content & Information",
            "description": "Alphabet Inc. operates Google Services, Google Cloud, and Other Bets segments.",
        },
        "MSFT": {
            "symbol": "MSFT",
            "companyName": "Microsoft Corporation",
            "sector": "Technology",
            "industry": "Software—Infrastructure",
            "description": "Microsoft develops software, services, devices, and solutions.",
        },
        "NVDA": {
            "symbol": "NVDA",
            "companyName": "NVIDIA Corporation",
            "sector": "Technology",
            "industry": "Semiconductors",
            "description": "NVIDIA designs GPUs and AI computing platforms.",
        },
    }

    profile = profiles.get(ticker.upper(), {
        "symbol": ticker,
        "companyName": ticker,
        "sector": "Technology",
        "industry": "Technology",
        "description": f"Company with ticker {ticker}",
    })

    return CompanyContext(
        symbol=ticker.upper(),
        fetched_at=datetime.now(timezone.utc),
        profile=profile,
        evidence_ids=tuple(),
    )


async def run_external_discovery(
    company_context: CompanyContext,
    budget: float = 5.0,
    output_dir: Path | None = None,
) -> ExternalDiscoveryOutput:
    """Run External Discovery on a company context."""

    print(f"\n{'='*60}")
    print(f" EXTERNAL DISCOVERY TEST")
    print(f" Ticker: {company_context.symbol}")
    print(f" Company: {company_context.company_name}")
    print(f" Industry: {company_context.profile.get('industry', 'Unknown')}")
    print(f" Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    # Create context
    settings = Settings()
    evidence_store = EvidenceStore(cache_dir=Path("output/evidence_cache"))
    budget_tracker = BudgetTracker(budget_limit=budget)
    llm_router = LLMRouter(settings=settings)

    agent_context = AgentContext(
        settings=settings,
        llm_router=llm_router,
        evidence_store=evidence_store,
        budget_tracker=budget_tracker,
    )

    # Create run state
    run_state = RunState.create(
        ticker=company_context.symbol,
        budget_usd=budget,
    )

    # Create and run agent
    agent = ExternalDiscoveryAgent(agent_context)

    print("Starting External Discovery...")
    print("This agent will:")
    print("  1. Search for competitor developments")
    print("  2. Find industry news and trends")
    print("  3. Analyze analyst sentiment")
    print("  4. Identify strategic shifts (last 6-12 months)")
    print("  5. Surface variant perception opportunities")
    print("\nRunning web searches (this may take 30-60 seconds)...\n")

    try:
        output = await agent.run(run_state, company_context)
    finally:
        await agent.close()

    # Print results
    print(f"\n{'='*60}")
    print(" RESULTS")
    print(f"{'='*60}\n")

    print(f"Analysis Date: {output.analysis_date}")
    print(f"Searches Performed: {len(output.searches_performed)}")

    print(f"\n--- STRATEGIC SHIFTS ({len(output.strategic_shifts)}) ---")
    for shift in output.strategic_shifts:
        print(f"  [{shift.get('materiality', '?')}] {shift.get('shift_type', '?')}: {shift.get('description', '?')}")
        print(f"      Source: {shift.get('source', 'unknown')} | Date: {shift.get('date_announced', '?')}")
        print(f"      Competitive implication: {shift.get('competitive_implication', '?')}")
        print(f"      Priced in: {shift.get('is_priced_in', '?')}")
        print()

    print(f"\n--- VARIANT PERCEPTIONS ({len(output.variant_perceptions)}) ---")
    for vp in output.variant_perceptions:
        print(f"  Topic: {vp.get('topic', '?')}")
        print(f"    Consensus: {vp.get('consensus_view', '?')}")
        print(f"    Variant:   {vp.get('variant_view', '?')}")
        print(f"    Trigger:   {vp.get('trigger_event', '?')}")
        print()

    print(f"\n--- COMPETITOR DEVELOPMENTS ({len(output.competitor_developments)}) ---")
    for cd in output.competitor_developments[:5]:  # Top 5
        print(f"  {cd.get('competitor', '?')}: {cd.get('announcement', '?')[:100]}...")
        print(f"    Source: {cd.get('source', 'unknown')} | Date: {cd.get('date', '?')}")
        print(f"    Threat level: {cd.get('threat_level', '?')}")
        print()

    print(f"\n--- ANALYST SENTIMENT ---")
    sentiment = output.analyst_sentiment
    print(f"  Consensus: {sentiment.get('consensus', '?')}")
    print(f"  Rating: {sentiment.get('average_rating', '?')}")
    print(f"  Bull thesis: {sentiment.get('bull_thesis', '?')[:100] if sentiment.get('bull_thesis') else '?'}...")
    print(f"  Bear thesis: {sentiment.get('bear_thesis', '?')[:100] if sentiment.get('bear_thesis') else '?'}...")
    print(f"  Key debates: {sentiment.get('key_debates', [])}")

    print(f"\n--- SUGGESTED RESEARCH THREADS ({len(output.suggested_threads)}) ---")
    for st in output.suggested_threads:
        print(f"  [{st.get('priority', '?')}] {st.get('name', '?')}")
        print(f"      Why: {st.get('why_it_matters', '?')[:100]}...")
        print()

    print(f"\n--- CRITICAL EXTERNAL CONTEXT ---")
    for ctx in output.critical_external_context:
        print(f"  • {ctx}")

    # Print cost
    print(f"\n{'='*60}")
    print(f" COST: ${budget_tracker.total_cost_usd:.4f}")
    print(f"{'='*60}\n")

    # Save output if requested
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"external_discovery_{company_context.symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # Convert to dict for JSON
        output_dict = {
            "meta": {
                "ticker": company_context.symbol,
                "company_name": company_context.company_name,
                "analysis_date": output.analysis_date,
                "cost_usd": budget_tracker.total_cost_usd,
            },
            "searches_performed": output.searches_performed,
            "competitor_developments": output.competitor_developments,
            "industry_news": output.industry_news,
            "analyst_sentiment": output.analyst_sentiment,
            "market_discourse": output.market_discourse,
            "strategic_shifts": output.strategic_shifts,
            "variant_perceptions": output.variant_perceptions,
            "suggested_threads": output.suggested_threads,
            "critical_external_context": output.critical_external_context,
        }

        with open(output_file, "w") as f:
            json.dump(output_dict, f, indent=2)

        print(f"Output saved to: {output_file}")

    return output


def main():
    parser = argparse.ArgumentParser(description="Test External Discovery Agent in isolation")
    parser.add_argument("--run-dir", type=str, help="Path to existing run directory with checkpoint")
    parser.add_argument("--ticker", type=str, help="Ticker symbol (creates minimal context)")
    parser.add_argument("--budget", type=float, default=5.0, help="Budget limit in USD")
    parser.add_argument("--output-dir", type=str, default="output/external_discovery_tests", help="Output directory")

    args = parser.parse_args()

    if not args.run_dir and not args.ticker:
        # Default to GOOGL
        args.ticker = "GOOGL"

    # Load company context
    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            print(f"Error: Run directory not found: {run_dir}")
            sys.exit(1)
        company_context = load_company_context_from_checkpoint(run_dir)
    else:
        company_context = create_minimal_company_context(args.ticker)

    # Run
    output_dir = Path(args.output_dir) if args.output_dir else None
    asyncio.run(run_external_discovery(company_context, args.budget, output_dir))


if __name__ == "__main__":
    main()
