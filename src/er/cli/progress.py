"""Rich progress display for the equity research pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text


@dataclass
class StageInfo:
    """Information about a pipeline stage."""

    number: int
    name: str
    status: str = "pending"  # pending, running, complete, error
    detail: str = ""
    started_at: float | None = None
    completed_at: float | None = None

    @property
    def duration(self) -> float | None:
        """Get duration in seconds."""
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def duration_str(self) -> str:
        """Get formatted duration string."""
        d = self.duration
        if d is None:
            return ""
        if d < 60:
            return f"{d:.0f}s"
        minutes = int(d // 60)
        seconds = int(d % 60)
        return f"{minutes}m {seconds}s"


class PipelineProgress:
    """Live progress display for the equity research pipeline."""

    STAGE_NAMES = {
        1: "Data Collection",
        2: "Discovery",
        3: "Deep Research",
        4: "Dual Synthesis",
        5: "Editorial Review",
        6: "Revision",
    }

    STATUS_ICONS = {
        "pending": "[dim]...[/dim]",
        "starting": "[yellow]...[/yellow]",
        "running": "[yellow]...[/yellow]",
        "complete": "[green]OK[/green]",
        "error": "[red]ERR[/red]",
    }

    def __init__(self, console: Console, ticker: str, budget: float) -> None:
        """Initialize progress display.

        Args:
            console: Rich console to write to.
            ticker: Stock ticker being analyzed.
            budget: Budget limit in USD.
        """
        self.console = console
        self.ticker = ticker
        self.budget = budget
        self.started_at = time.time()
        self.current_cost = 0.0

        # Initialize stages
        self.stages: dict[int, StageInfo] = {
            i: StageInfo(number=i, name=name)
            for i, name in self.STAGE_NAMES.items()
        }

        # Current stage and status
        self.current_stage = 0
        self.current_detail = ""
        self.is_complete = False
        self.error_message: str | None = None

        # Live display
        self._live: Live | None = None

    def _build_display(self) -> Panel:
        """Build the progress display panel."""
        # Header with ticker and timing
        elapsed = time.time() - self.started_at
        elapsed_str = self._format_duration(elapsed)

        # Build stages table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Stage", width=3, justify="right")
        table.add_column("Status", width=4)
        table.add_column("Name", width=18)
        table.add_column("Detail", style="dim")
        table.add_column("Time", width=8, justify="right", style="dim")

        for i in range(1, 7):
            stage = self.stages[i]
            status_icon = self.STATUS_ICONS.get(stage.status, "")

            # Highlight current running stage
            if stage.status in ("starting", "running"):
                name_style = "bold yellow"
            elif stage.status == "complete":
                name_style = "green"
            elif stage.status == "error":
                name_style = "red"
            else:
                name_style = "dim"

            table.add_row(
                f"{i}.",
                status_icon,
                Text(stage.name, style=name_style),
                stage.detail[:45] + "..." if len(stage.detail) > 45 else stage.detail,
                stage.duration_str,
            )

        # Cost display
        cost_text = f"${self.current_cost:.2f} / ${self.budget:.2f}"
        if self.current_cost > self.budget * 0.8:
            cost_style = "bold red"
        elif self.current_cost > self.budget * 0.5:
            cost_style = "yellow"
        else:
            cost_style = "green"

        # Build footer
        footer = Text()
        footer.append("Cost: ", style="dim")
        footer.append(cost_text, style=cost_style)
        footer.append("  |  ", style="dim")
        footer.append("Elapsed: ", style="dim")
        footer.append(elapsed_str, style="cyan")

        # Combine into panel
        content = Group(table, Text(""), footer)

        if self.is_complete:
            title = f"[bold green]{self.ticker} Analysis Complete[/bold green]"
            border_style = "green"
        elif self.error_message:
            title = f"[bold red]{self.ticker} Analysis Failed[/bold red]"
            border_style = "red"
        else:
            title = f"[bold cyan]Analyzing {self.ticker}...[/bold cyan]"
            border_style = "cyan"

        return Panel(content, title=title, border_style=border_style)

    def _format_duration(self, seconds: float) -> str:
        """Format duration as human-readable string."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours = int(minutes // 60)
        mins = int(minutes % 60)
        return f"{hours}h {mins}m"

    def update(
        self,
        stage: int,
        stage_name: str,
        status: str,
        detail: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """Update progress from pipeline callback.

        Args:
            stage: Stage number (1-6).
            stage_name: Human-readable stage name.
            status: "starting", "running", "complete", "error".
            detail: Additional detail about what's happening.
            cost_usd: Current total cost.
        """
        self.current_cost = cost_usd
        self.current_stage = stage

        if stage in self.stages:
            stage_info = self.stages[stage]
            stage_info.status = status
            stage_info.detail = detail

            if status == "starting":
                stage_info.started_at = time.time()
            elif status == "complete":
                stage_info.completed_at = time.time()

        # Refresh the live display
        if self._live:
            self._live.update(self._build_display())

    def mark_complete(self) -> None:
        """Mark the pipeline as complete."""
        self.is_complete = True
        if self._live:
            self._live.update(self._build_display())

    def mark_error(self, message: str) -> None:
        """Mark the pipeline as failed."""
        self.error_message = message
        if self.current_stage in self.stages:
            self.stages[self.current_stage].status = "error"
            self.stages[self.current_stage].detail = message[:50]
        if self._live:
            self._live.update(self._build_display())

    def __enter__(self) -> "PipelineProgress":
        """Start the live display."""
        self._live = Live(
            self._build_display(),
            console=self.console,
            refresh_per_second=4,
            transient=False,
            auto_refresh=True,
            get_renderable=self._build_display,  # Callable for auto-refresh
        )
        self._live.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop the live display."""
        if self._live:
            # Do a final update before stopping
            self._live.update(self._build_display())
            self._live.__exit__(exc_type, exc_val, exc_tb)
            self._live = None
