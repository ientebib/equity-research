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
from rich.table import Table

from er import __version__
from er.config import Settings, clear_settings_cache, get_settings
from er.exceptions import ConfigurationError
from er.types import Phase, RunState, utc_now

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
) -> None:
    """Run equity research analysis on a stock ticker.

    Creates a run folder with analysis outputs including:
    - Research report (Markdown)
    - Excel model with projections
    - Evidence citations
    - Full audit log
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

    # Create run state
    run_state = RunState.create(ticker=ticker, budget_usd=effective_budget)

    # Create output directory
    run_output_dir = effective_output_dir / run_state.run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)

    # Write manifest
    manifest = {
        "run_id": run_state.run_id,
        "ticker": ticker,
        "started_at": run_state.started_at.isoformat(),
        "budget_usd": effective_budget,
        "max_rounds": effective_max_rounds,
        "dry_run": dry_run,
        "phase": run_state.phase.value,
        "providers": settings.available_providers,
    }
    manifest_path = run_output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

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

    if dry_run:
        console.print("\n[yellow]Dry run mode - no APIs will be called.[/yellow]")
        run_state.phase = Phase.COMPLETE
    else:
        # TODO: Implement actual analysis pipeline
        console.print(
            "\n[yellow]Note:[/yellow] Full analysis pipeline not yet implemented."
        )
        run_state.phase = Phase.INIT

    # Update manifest with final phase
    manifest["phase"] = run_state.phase.value
    manifest["completed_at"] = utc_now().isoformat() if dry_run else None
    manifest_path.write_text(json.dumps(manifest, indent=2))

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
