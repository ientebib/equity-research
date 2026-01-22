"""
CLI for the equity research system.

Commands:
    er analyze TICKER - Run analysis on a stock ticker
    er config - Show current configuration
    er version - Print version
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from er import __version__
from er.config import Settings, clear_settings_cache, get_settings
from er.exceptions import ConfigurationError
from er.manifest import RunManifest
from er.types import Phase, RunState, utc_now
from er.utils.dates import get_latest_quarter, get_quarter_range, format_quarter

app = typer.Typer(
    name="er",
    help="Equity Research - AI-powered institutional-grade equity analysis",
    no_args_is_help=True,
)

console = Console()
error_console = Console(stderr=True)


def _get_settings_safe() -> Settings | None:
    """Get settings, returning None if configuration is invalid."""
    try:
        clear_settings_cache()
        return get_settings()
    except Exception:
        return None


def _load_transcripts_from_dir(ticker: str, transcripts_dir: Path, num_quarters: int = 4) -> list[dict]:
    """Load transcripts from text files in a directory.

    Expected files: q3_2025.txt, q2_2025.txt, etc. (based on current quarter)

    Args:
        ticker: Stock ticker symbol.
        transcripts_dir: Directory containing transcript files.
        num_quarters: Number of quarters to load.

    Returns:
        List of transcript dicts.
    """
    console.print()
    console.print(f"[cyan]Loading transcripts from:[/cyan] {transcripts_dir}")

    # Dynamically compute quarters based on current date
    current_year, current_quarter = get_latest_quarter()
    quarters_to_load = get_quarter_range(current_year, current_quarter, num_quarters)

    transcripts = []

    for year, quarter in quarters_to_load:
        # Try different file name patterns
        patterns = [
            f"q{quarter}_{year}.txt",
            f"Q{quarter}_{year}.txt",
            f"q{quarter}{year}.txt",
            f"{year}_q{quarter}.txt",
        ]

        found = False
        for pattern in patterns:
            file_path = transcripts_dir / pattern
            if file_path.exists():
                text = file_path.read_text(encoding="utf-8")
                transcripts.append({
                    "ticker": ticker,
                    "quarter": quarter,
                    "year": year,
                    "text": text,
                    "source": "file",
                    "date": f"{year}-{quarter * 3:02d}-01",
                })
                console.print(f"  [green]✓[/green] Q{quarter} {year}: {len(text):,} chars from {pattern}")
                found = True
                break

        if not found:
            console.print(f"  [yellow]![/yellow] Q{quarter} {year}: not found (tried {patterns[0]})")

    console.print()
    if transcripts:
        console.print(f"[bold green]Loaded {len(transcripts)} transcript(s)[/bold green]")
    else:
        console.print("[yellow]No transcripts found. Analysis will proceed without them.[/yellow]")

    return transcripts


def _collect_transcripts(ticker: str, num_quarters: int = 4) -> list[dict]:
    """Interactively collect earnings call transcripts from user.

    Prompts user to paste transcripts for the last N quarters.

    Args:
        ticker: Stock ticker symbol.
        num_quarters: Number of quarters to collect (default 4).

    Returns:
        List of transcript dicts with quarter, year, and text.
    """
    from datetime import datetime

    console.print()
    console.print(
        Panel(
            f"[bold]Earnings Call Transcripts for {ticker}[/bold]\n\n"
            "Transcripts are essential for understanding management's perspective.\n"
            "You can get them from:\n"
            "  - Seeking Alpha (seekingalpha.com/earnings/earnings-call-transcripts)\n"
            "  - Company IR website\n"
            "  - The Motley Fool\n\n"
            "[dim]Paste the full transcript text, then press Enter twice to submit.[/dim]",
            title="[cyan]Transcript Collection[/cyan]",
            border_style="cyan",
        )
    )

    # Dynamically compute quarters based on current date
    current_year, current_quarter = get_latest_quarter()
    quarters_to_collect = get_quarter_range(current_year, current_quarter, num_quarters)

    transcripts = []

    for i, (year, quarter) in enumerate(quarters_to_collect, 1):
        console.print()
        console.print(f"[bold cyan]({i}/{num_quarters}) Q{quarter} {year} Transcript[/bold cyan]")
        console.print("[dim]Paste transcript below. Press Enter twice when done, or type 'skip' to skip this quarter:[/dim]")
        console.print()

        # Collect multi-line input
        lines = []
        empty_line_count = 0

        while True:
            try:
                line = input()
                if line.strip().lower() == "skip":
                    console.print(f"[yellow]Skipping Q{quarter} {year}[/yellow]")
                    break
                if line == "":
                    empty_line_count += 1
                    if empty_line_count >= 2:
                        break
                    lines.append(line)
                else:
                    empty_line_count = 0
                    lines.append(line)
            except EOFError:
                break

        text = "\n".join(lines).strip()

        if text and text.lower() != "skip":
            transcripts.append({
                "ticker": ticker,
                "quarter": quarter,
                "year": year,
                "text": text,
                "source": "manual",
                "date": f"{year}-{quarter * 3:02d}-01",  # Approximate date
            })
            console.print(f"[green]✓ Received Q{quarter} {year} transcript ({len(text):,} chars)[/green]")

    console.print()
    if transcripts:
        console.print(f"[bold green]Collected {len(transcripts)} transcript(s)[/bold green]")
    else:
        console.print("[yellow]No transcripts collected. Analysis will proceed without them.[/yellow]")

    return transcripts


@app.command()
def analyze(
    ticker: Annotated[str, typer.Argument(help="Stock ticker symbol (e.g., AAPL)")],
    budget: Annotated[
        Optional[float],
        typer.Option("--budget", "-b", help="Maximum budget in USD"),
    ] = None,
    max_rounds: Annotated[
        Optional[int],
        typer.Option("--max-rounds", "-r", help="Maximum deliberation rounds"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Create run folder without calling APIs"),
    ] = False,
    output_dir: Annotated[
        Optional[Path],
        typer.Option("--output-dir", "-o", help="Output directory"),
    ] = None,
    no_transcripts: Annotated[
        bool,
        typer.Option("--no-transcripts", help="Skip transcript collection"),
    ] = False,
    num_quarters: Annotated[
        int,
        typer.Option("--quarters", "-q", help="Number of transcript quarters to collect"),
    ] = 4,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed progress logs"),
    ] = False,
    transcripts_dir: Annotated[
        Optional[Path],
        typer.Option("--transcripts-dir", "-t", help="Directory with transcript files (q3_2025.txt, q2_2025.txt, etc.)"),
    ] = None,
    resume: Annotated[
        Optional[Path],
        typer.Option("--resume", help="Resume from a previous run directory (e.g., output/run_GOOGL_20251224_140000)"),
    ] = None,
    simple: Annotated[
        bool,
        typer.Option("--simple", "-s", help="Use simplified 3-stage pipeline with Anthropic research"),
    ] = False,
    agent_sdk: Annotated[
        bool,
        typer.Option("--agent-sdk", "-a", help="Use Claude Agent SDK multi-agent pipeline (best quality, highest cost)"),
    ] = False,
) -> None:
    """Run equity research analysis on a stock ticker.

    Creates a run folder with analysis outputs including:
    - Research report (Markdown)
    - Excel model with projections
    - Evidence citations
    - Full audit log

    Use --simple for a streamlined 3-stage pipeline that actually works.
    """
    # Load settings
    settings = _get_settings_safe()
    if settings is None:
        error_console.print(
            "[red]Error:[/red] Configuration is invalid. "
            "Run 'er config' to see what's missing."
        )
        raise typer.Exit(1)

    # Override settings with CLI options
    effective_budget = budget if budget is not None else settings.MAX_BUDGET_USD
    effective_max_rounds = (
        max_rounds if max_rounds is not None else settings.MAX_DELIBERATION_ROUNDS
    )
    effective_output_dir = output_dir if output_dir is not None else settings.OUTPUT_DIR

    # Normalize ticker
    ticker = ticker.upper().strip()

    # Handle resume mode
    is_resuming = resume is not None
    run_manifest: RunManifest | None = None

    if is_resuming:
        if not resume.exists():
            error_console.print(f"[red]Error:[/red] Resume directory not found: {resume}")
            raise typer.Exit(1)

        # Use the existing run directory
        run_output_dir = resume
        manifest_path = run_output_dir / "manifest.json"

        # Load or create RunManifest for resume
        run_manifest = RunManifest.load(run_output_dir)
        if run_manifest:
            run_id = run_manifest.run_id
        else:
            # Create new manifest if none exists
            run_id = f"run_{ticker}_resumed"
            run_manifest = RunManifest(
                output_dir=run_output_dir,
                run_id=run_id,
                ticker=ticker,
            )

        # Check which stages are already done
        stage_files = [
            "stage1_company_context.json",
            "stage2_discovery.json",
            "stage3_verticals.json",
            "stage3_5_verification.json",
            "stage3_75_integration.json",
            "stage4_claude_synthesis.json",
            "stage5_editorial_feedback.json",
        ]
        completed = [f for f in stage_files if (run_output_dir / f).exists()]

        console.print()
        console.print(
            Panel(
                f"[bold]Ticker:[/bold] {ticker}\n"
                f"[bold]Mode:[/bold] [yellow]RESUME[/yellow]\n"
                f"[bold]Resume Directory:[/bold] {run_output_dir}\n"
                f"[bold]Completed Stages:[/bold] {len(completed)}\n"
                f"[bold]Budget:[/bold] ${effective_budget:.2f}\n"
                f"[bold]Providers:[/bold] {', '.join(settings.available_providers)}",
                title="[bold yellow]Resuming Analysis[/bold yellow]",
                border_style="yellow",
            )
        )

        if completed:
            console.print("\n[dim]Loaded checkpoints:[/dim]")
            for f in completed:
                console.print(f"  [green]✓[/green] {f}")
    else:
        # Create run state for new run
        run_state = RunState.create(ticker=ticker, budget_usd=effective_budget)

        # Create output directory
        run_output_dir = effective_output_dir / run_state.run_id
        run_output_dir.mkdir(parents=True, exist_ok=True)

        # Create RunManifest v2
        run_manifest = RunManifest(
            output_dir=run_output_dir,
            run_id=run_state.run_id,
            ticker=ticker,
        )
        run_manifest.set_input_hash({
            "ticker": ticker,
            "budget_usd": effective_budget,
            "max_rounds": effective_max_rounds,
            "dry_run": dry_run,
            "providers": settings.available_providers,
        })
        run_manifest.save()
        manifest_path = run_manifest.manifest_path

        # Print run info
        console.print()
        console.print(
            Panel(
                f"[bold]Ticker:[/bold] {ticker}\n"
                f"[bold]Run ID:[/bold] {run_state.run_id}\n"
                f"[bold]Budget:[/bold] ${effective_budget:.2f}\n"
                f"[bold]Max Rounds:[/bold] {effective_max_rounds}\n"
                f"[bold]Providers:[/bold] {', '.join(settings.available_providers)}\n"
                f"[bold]Dry Run:[/bold] {dry_run}",
                title="[bold cyan]Equity Research Analysis[/bold cyan]",
                border_style="cyan",
            )
        )

        console.print(f"\n[dim]Output directory:[/dim] {run_output_dir}")
        console.print(f"[dim]Manifest:[/dim] {manifest_path}")

    # Collect transcripts (from files or interactively)
    # Skip transcript collection if resuming (use existing transcripts)
    transcripts: list[dict] = []
    if is_resuming:
        # Load existing transcripts from resume directory
        existing_transcripts_path = run_output_dir / "transcripts.json"
        if existing_transcripts_path.exists():
            transcripts = json.loads(existing_transcripts_path.read_text())
            console.print(f"\n[dim]Using {len(transcripts)} existing transcripts from checkpoint[/dim]")
    elif not dry_run and not no_transcripts:
        if transcripts_dir:
            # Load from files
            transcripts = _load_transcripts_from_dir(ticker, transcripts_dir, num_quarters)
        else:
            # Interactive collection
            transcripts = _collect_transcripts(ticker, num_quarters)

        # Save transcripts to run directory
        if transcripts:
            transcripts_path = run_output_dir / "transcripts.json"
            transcripts_path.write_text(json.dumps(transcripts, indent=2))
            console.print(f"[dim]Transcripts saved to:[/dim] {transcripts_path}")

    if dry_run:
        console.print("\n[yellow]Dry run mode - no APIs will be called.[/yellow]")
        if not is_resuming and run_manifest:
            run_state.phase = Phase.COMPLETE
            run_manifest.complete(success=True)
            run_manifest.save()
    elif agent_sdk:
        # Use Claude Agent SDK multi-agent pipeline
        import asyncio
        from er.coordinator.agent_pipeline import AgentResearchPipeline
        from er.logging import setup_logging

        setup_logging(log_level="DEBUG" if verbose else "INFO", log_file=run_output_dir / "run.log")

        console.print("\n[bold magenta]Using Claude Agent SDK multi-agent pipeline...[/bold magenta]")
        console.print("[dim]This architecture mirrors Anthropic's deep research system:[/dim]")
        console.print("[dim]  - Parallel research subagents (Sonnet)[/dim]")
        console.print("[dim]  - Synthesis with Opus 4.5[/dim]")
        console.print("[dim]  - Isolated context windows per subagent[/dim]")
        console.print()

        try:
            pipeline = AgentResearchPipeline(
                output_dir=run_output_dir,
                max_threads=8,
                enable_verification=True,
            )
            result = asyncio.run(pipeline.run(ticker))

            # Print summary
            console.print()
            console.print(
                Panel(
                    f"[bold]Research Threads:[/bold] {len(result.threads)}\n"
                    f"[bold]Report Length:[/bold] {len(result.report):,} chars\n\n"
                    f"[bold]Report Preview:[/bold]\n{result.report[:800]}...\n\n"
                    f"[dim]Verification: {result.verification.get('overall_confidence', 'N/A')}[/dim]",
                    title=f"[bold green]{ticker} Agent SDK Research Complete[/bold green]",
                    border_style="green",
                )
            )
            console.print(f"\n[bold]Report saved to:[/bold] {run_output_dir / 'report.md'}")

        except Exception as e:
            error_console.print(f"\n[red]Error:[/red] {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(1)
    elif simple:
        # Use simplified 3-stage pipeline with Anthropic research
        import asyncio
        from er.coordinator.simple_pipeline import SimplePipeline, SimpleConfig
        from er.logging import setup_logging

        setup_logging(log_level="DEBUG" if verbose else "INFO", log_file=run_output_dir / "run.log")

        console.print("\n[bold cyan]Using simplified 3-stage pipeline with Anthropic research...[/bold cyan]\n")

        simple_config = SimpleConfig(output_dir=effective_output_dir)

        def progress_callback(stage: str, message: str, progress: float) -> None:
            console.print(f"[dim][{stage}][/dim] {message}")

        try:
            pipeline = SimplePipeline(
                settings=settings,
                config=simple_config,
                progress_callback=progress_callback,
            )
            result = asyncio.run(pipeline.run(ticker))

            # Print summary
            console.print()
            console.print(
                Panel(
                    f"[bold]Executive Summary:[/bold]\n{result.synthesis.executive_summary[:500]}...\n\n"
                    f"[bold]Valuation:[/bold] {result.synthesis.valuation_summary or 'N/A'}\n\n"
                    f"[dim]Duration: {result.duration_seconds:.0f}s | "
                    f"Citations: {result.research_bundle.total_citations} | "
                    f"Evidence IDs: {len(result.research_bundle.all_evidence_ids)}[/dim]",
                    title=f"[bold green]{ticker} Research Complete[/bold green]",
                    border_style="green",
                )
            )
            console.print(f"\n[bold]Report saved to:[/bold] {result.output_dir / 'report.md'}")

        except Exception as e:
            error_console.print(f"\n[red]Error:[/red] {e}")
            import traceback
            traceback.print_exc()
            raise typer.Exit(1)
    else:
        # Run the original complex pipeline
        import asyncio
        from er.coordinator.pipeline import ResearchPipeline, PipelineConfig
        from er.logging import setup_logging
        from er.cli.progress import PipelineProgress

        # Set up logging based on verbose flag
        if verbose:
            setup_logging(log_level="DEBUG", log_file=run_output_dir / "debug.log")
            if is_resuming:
                console.print("\n[bold yellow]Resuming 6-stage analysis pipeline (verbose mode)...[/bold yellow]\n")
            else:
                console.print("\n[bold green]Starting 6-stage analysis pipeline (verbose mode)...[/bold green]\n")
        else:
            setup_logging(log_level="INFO", log_file=run_output_dir / "run.log")
            console.print()  # Blank line before progress display

        pipeline_config = PipelineConfig(
            output_dir=run_output_dir,
            resume_from_run_dir=resume if is_resuming else None,  # Pass resume directory
            max_budget_usd=effective_budget,
            include_transcripts=len(transcripts) > 0,
            num_transcript_quarters=num_quarters,
            use_web_search_discovery=True,
            use_deep_research_verticals=True,
            max_parallel_verticals=5,
            manual_transcripts=transcripts,  # Pass collected transcripts
        )

        try:
            if verbose:
                # Verbose mode: no live display, logs stream to console
                pipeline = ResearchPipeline(settings=settings, config=pipeline_config)
                result = asyncio.run(pipeline.run(ticker))
            else:
                # Normal mode: live progress display
                progress_display = PipelineProgress(console, ticker, effective_budget)
                pipeline = ResearchPipeline(
                    settings=settings,
                    config=pipeline_config,
                    progress_callback=progress_display.update,
                )
                with progress_display:
                    result = asyncio.run(pipeline.run(ticker))
                    progress_display.mark_complete()

            # Generate report
            report_path = run_output_dir / "report.md"
            report_content = result.to_report_markdown()
            report_path.write_text(report_content)

            # Update manifest using RunManifest v2
            if run_manifest:
                run_manifest.add_artifact("report", str(report_path))
                run_manifest.complete(success=True)
                run_manifest.save()
            else:
                # Fallback for edge cases
                manifest_data = {
                    "phase": "complete",
                    "completed_at": result.completed_at.isoformat(),
                    "total_cost_usd": result.total_cost_usd,
                    "duration_seconds": result.duration_seconds,
                    "final_verdict": {
                        "investment_view": result.final_report.investment_view,
                        "conviction": result.final_report.conviction,
                        "confidence": result.final_report.overall_confidence,
                    },
                }
                manifest_path.write_text(json.dumps(manifest_data, indent=2))

            # Print summary
            console.print()
            console.print(
                Panel(
                    f"[bold]Investment View:[/bold] {result.final_report.investment_view}\n"
                    f"[bold]Conviction:[/bold] {result.final_report.conviction}\n"
                    f"[bold]Confidence:[/bold] {result.final_report.overall_confidence:.0%}\n\n"
                    f"[bold]Thesis:[/bold]\n{result.final_report.thesis_summary[:300]}...\n\n"
                    f"[dim]Cost: ${result.total_cost_usd:.2f} | Duration: {result.duration_seconds:.0f}s[/dim]",
                    title=f"[bold green]{ticker} Research Complete[/bold green]",
                    border_style="green",
                )
            )
            console.print(f"\n[bold]Report saved to:[/bold] {report_path}")

        except Exception as e:
            error_console.print(f"\n[red]Error:[/red] {e}")
            # Record error in manifest
            if run_manifest:
                run_manifest.fail(str(e))
                run_manifest.save()
            raise typer.Exit(1)

    console.print()


@app.command()
def config() -> None:
    """Show current configuration.

    Displays all configuration values with API keys redacted.
    Also shows which LLM providers are available.
    """
    console.print()
    console.print("[bold]Equity Research Configuration[/bold]")
    console.print()

    settings = _get_settings_safe()

    if settings is None:
        # Try to show what's wrong
        error_console.print(
            "[red]Configuration is invalid or incomplete.[/red]"
        )
        error_console.print()
        error_console.print("Required environment variables:")
        error_console.print("  - SEC_USER_AGENT (must contain email)")
        error_console.print(
            "  - At least one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY"
        )
        error_console.print()
        error_console.print("Create a .env file or set environment variables.")
        error_console.print("See .env.example for a template.")
        raise typer.Exit(1)

    # Display settings
    table = Table(title="Settings", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    for key, value in settings.redacted_display().items():
        display_value = str(value) if value is not None else "[dim]not set[/dim]"
        table.add_row(key, display_value)

    console.print(table)

    # Display available providers
    console.print()
    providers = settings.available_providers
    if providers:
        console.print(f"[bold]Available LLM Providers:[/bold] {', '.join(providers)}")
    else:
        console.print("[yellow]No LLM providers configured.[/yellow]")

    console.print()


@app.command()
def version() -> None:
    """Print the version number."""
    console.print(f"equity-research version {__version__}")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
