#!/usr/bin/env python3
"""
Context Analysis Tool - Shows exactly what tokens go to each agent.

Usage:
    python scripts/analyze_context.py <run_directory>

Produces a table showing:
- Stage/Agent
- Input tokens breakdown (what context components)
- Output tokens
- Cost
- Duration
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def count_tokens(text: str) -> int:
    """Approximate token count (1 token ≈ 4 chars for English)."""
    if not text:
        return 0
    return len(str(text)) // 4


def format_number(n: int) -> str:
    """Format number with commas."""
    return f"{n:,}"


def format_cost(c: float) -> str:
    """Format cost."""
    return f"${c:.4f}"


def analyze_company_context(context_path: Path) -> dict:
    """Break down the company context into components."""
    if not context_path.exists():
        return {}

    with open(context_path) as f:
        data = json.load(f)

    breakdown = {}

    # Profile
    if "profile" in data:
        profile_str = json.dumps(data["profile"])
        breakdown["profile"] = {
            "chars": len(profile_str),
            "tokens": count_tokens(profile_str),
            "description": f"Company profile ({data['profile'].get('companyName', 'Unknown')})",
        }

    # Income statements
    if "income_statement_quarterly" in data and data["income_statement_quarterly"]:
        income_str = json.dumps(data["income_statement_quarterly"])
        quarters = len(data["income_statement_quarterly"])
        breakdown["income_statement_quarterly"] = {
            "chars": len(income_str),
            "tokens": count_tokens(income_str),
            "description": f"Quarterly income statements ({quarters} quarters)",
        }

    if "income_statement_annual" in data and data["income_statement_annual"]:
        income_str = json.dumps(data["income_statement_annual"])
        years = len(data["income_statement_annual"])
        breakdown["income_statement_annual"] = {
            "chars": len(income_str),
            "tokens": count_tokens(income_str),
            "description": f"Annual income statements ({years} years)",
        }

    # Balance sheets
    if "balance_sheet_quarterly" in data and data["balance_sheet_quarterly"]:
        bs_str = json.dumps(data["balance_sheet_quarterly"])
        quarters = len(data["balance_sheet_quarterly"])
        breakdown["balance_sheet_quarterly"] = {
            "chars": len(bs_str),
            "tokens": count_tokens(bs_str),
            "description": f"Quarterly balance sheets ({quarters} quarters)",
        }

    if "balance_sheet_annual" in data and data["balance_sheet_annual"]:
        bs_str = json.dumps(data["balance_sheet_annual"])
        years = len(data["balance_sheet_annual"])
        breakdown["balance_sheet_annual"] = {
            "chars": len(bs_str),
            "tokens": count_tokens(bs_str),
            "description": f"Annual balance sheets ({years} years)",
        }

    # Cash flows
    if "cash_flow_quarterly" in data and data["cash_flow_quarterly"]:
        cf_str = json.dumps(data["cash_flow_quarterly"])
        quarters = len(data["cash_flow_quarterly"])
        breakdown["cash_flow_quarterly"] = {
            "chars": len(cf_str),
            "tokens": count_tokens(cf_str),
            "description": f"Quarterly cash flows ({quarters} quarters)",
        }

    if "cash_flow_annual" in data and data["cash_flow_annual"]:
        cf_str = json.dumps(data["cash_flow_annual"])
        years = len(data["cash_flow_annual"])
        breakdown["cash_flow_annual"] = {
            "chars": len(cf_str),
            "tokens": count_tokens(cf_str),
            "description": f"Annual cash flows ({years} years)",
        }

    # Ratios and metrics
    if "key_metrics" in data and data["key_metrics"]:
        km_str = json.dumps(data["key_metrics"])
        breakdown["key_metrics"] = {
            "chars": len(km_str),
            "tokens": count_tokens(km_str),
            "description": "Key metrics and ratios",
        }

    if "financial_ratios" in data and data["financial_ratios"]:
        fr_str = json.dumps(data["financial_ratios"])
        breakdown["financial_ratios"] = {
            "chars": len(fr_str),
            "tokens": count_tokens(fr_str),
            "description": "Financial ratios",
        }

    # Revenue segmentation
    if "revenue_by_product" in data and data["revenue_by_product"]:
        rp_str = json.dumps(data["revenue_by_product"])
        breakdown["revenue_by_product"] = {
            "chars": len(rp_str),
            "tokens": count_tokens(rp_str),
            "description": "Revenue by product segment",
        }

    if "revenue_by_geography" in data and data["revenue_by_geography"]:
        rg_str = json.dumps(data["revenue_by_geography"])
        breakdown["revenue_by_geography"] = {
            "chars": len(rg_str),
            "tokens": count_tokens(rg_str),
            "description": "Revenue by geography",
        }

    # Quant metrics (our computed metrics)
    if "quant_metrics" in data and data["quant_metrics"]:
        qm_str = json.dumps(data["quant_metrics"])
        breakdown["quant_metrics"] = {
            "chars": len(qm_str),
            "tokens": count_tokens(qm_str),
            "description": "Pre-computed quant metrics (ROIC, quality, etc.)",
        }

    # Transcripts
    if "transcripts" in data and data["transcripts"]:
        tr_str = json.dumps(data["transcripts"])
        breakdown["transcripts"] = {
            "chars": len(tr_str),
            "tokens": count_tokens(tr_str),
            "description": f"Earnings call transcripts ({len(data['transcripts'])} calls)",
        }

    # News
    if "news" in data and data["news"]:
        news_str = json.dumps(data["news"])
        breakdown["news"] = {
            "chars": len(news_str),
            "tokens": count_tokens(news_str),
            "description": f"Recent news ({len(data['news'])} articles)",
        }

    return breakdown


def print_context_breakdown(breakdown: dict):
    """Print a formatted table of context breakdown."""
    print("\n" + "=" * 90)
    print("COMPANY CONTEXT TOKEN BREAKDOWN")
    print("=" * 90)
    print(f"{'Component':<35} {'Tokens':>12} {'Chars':>12}   Description")
    print("-" * 90)

    total_tokens = 0
    total_chars = 0

    for name, info in sorted(breakdown.items(), key=lambda x: -x[1]["tokens"]):
        print(
            f"{name:<35} "
            f"{format_number(info['tokens']):>12} "
            f"{format_number(info['chars']):>12}   "
            f"{info['description'][:40]}"
        )
        total_tokens += info["tokens"]
        total_chars += info["chars"]

    print("-" * 90)
    print(f"{'TOTAL':<35} {format_number(total_tokens):>12} {format_number(total_chars):>12}")
    print()


def analyze_costs(costs_path: Path) -> dict:
    """Analyze costs.json."""
    if not costs_path.exists():
        return {}

    with open(costs_path) as f:
        return json.load(f)


def print_agent_breakdown(costs: dict):
    """Print agent-by-agent breakdown."""
    if not costs.get("records"):
        print("No LLM call records found.")
        return

    print("\n" + "=" * 100)
    print("AGENT LLM CALLS BREAKDOWN")
    print("=" * 100)
    print(
        f"{'Agent':<25} {'Model':<30} {'Input':>12} {'Output':>10} {'Cost':>12}"
    )
    print("-" * 100)

    total_input = 0
    total_output = 0
    total_cost = 0.0

    for record in costs["records"]:
        print(
            f"{record['agent']:<25} "
            f"{record['model'][:28]:<30} "
            f"{format_number(record['input_tokens']):>12} "
            f"{format_number(record['output_tokens']):>10} "
            f"{format_cost(record['cost_usd']):>12}"
        )
        total_input += record["input_tokens"]
        total_output += record["output_tokens"]
        total_cost += record["cost_usd"]

    print("-" * 100)
    print(
        f"{'TOTAL':<25} "
        f"{'':<30} "
        f"{format_number(total_input):>12} "
        f"{format_number(total_output):>10} "
        f"{format_cost(total_cost):>12}"
    )
    print()


def print_stage_summary(costs: dict):
    """Print per-stage summary."""
    if not costs.get("by_phase"):
        return

    print("\n" + "=" * 60)
    print("COST BY STAGE/PHASE")
    print("=" * 60)
    print(f"{'Phase':<30} {'Cost':>15}")
    print("-" * 60)

    for phase, cost in sorted(costs["by_phase"].items(), key=lambda x: -x[1]):
        print(f"{phase:<30} {format_cost(cost):>15}")

    print("-" * 60)
    print(f"{'TOTAL':<30} {format_cost(costs.get('total_cost_usd', 0)):>15}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_context.py <run_directory>")
        print("\nExample:")
        print("  python scripts/analyze_context.py test_output_quick/run_019b8129-...")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Directory not found: {run_dir}")
        sys.exit(1)

    print(f"\n{'#' * 100}")
    print(f"# EQUITY RESEARCH PIPELINE ANALYSIS")
    print(f"# Run: {run_dir.name}")
    print(f"# Time: {datetime.now().isoformat()}")
    print(f"{'#' * 100}")

    # 1. Company Context Breakdown
    context_path = run_dir / "stage1_company_context.json"
    if context_path.exists():
        breakdown = analyze_company_context(context_path)
        print_context_breakdown(breakdown)
    else:
        print("\nNo stage1_company_context.json found")

    # 2. LLM Calls Analysis
    costs_path = run_dir / "costs.json"
    if costs_path.exists():
        costs = analyze_costs(costs_path)
        print_agent_breakdown(costs)
        print_stage_summary(costs)
    else:
        print("\nNo costs.json found")

    # 3. Summary
    print("\n" + "=" * 60)
    print("TOKEN FLOW SUMMARY")
    print("=" * 60)

    if context_path.exists():
        breakdown = analyze_company_context(context_path)
        context_tokens = sum(b["tokens"] for b in breakdown.values())
        print(f"FMP Company Context:    {format_number(context_tokens):>15} tokens")

    if costs_path.exists():
        costs = analyze_costs(costs_path)
        print(f"Total LLM Input:        {format_number(costs.get('total_input_tokens', 0)):>15} tokens")
        print(f"Total LLM Output:       {format_number(costs.get('total_output_tokens', 0)):>15} tokens")
        print(f"Total Cost:             {format_cost(costs.get('total_cost_usd', 0)):>15}")
        print(f"Budget Remaining:       {format_cost(costs.get('remaining', 0)):>15}")

    print()


if __name__ == "__main__":
    main()
