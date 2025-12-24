"""
Structured logging for the equity research system.

Provides:
- Context variables for run_id, agent, phase (using contextvars)
- JSONFormatter for machine-readable logs to file
- RichHandler for pretty console output
- ContextLogger wrapper that attaches context to all log calls
- setup_logging() that configures both file and console handlers
- Context manager set_context() for scoped context
- get_logger() factory
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

# Context variables for structured logging
_run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
_agent_var: ContextVar[str | None] = ContextVar("agent", default=None)
_phase_var: ContextVar[str | None] = ContextVar("phase", default=None)


def get_run_id() -> str | None:
    """Get the current run ID from context."""
    return _run_id_var.get()


def get_agent() -> str | None:
    """Get the current agent name from context."""
    return _agent_var.get()


def get_phase() -> str | None:
    """Get the current phase from context."""
    return _phase_var.get()


def set_run_id(run_id: str | None) -> None:
    """Set the current run ID in context."""
    _run_id_var.set(run_id)


def set_agent(agent: str | None) -> None:
    """Set the current agent name in context."""
    _agent_var.set(agent)


def set_phase(phase: str | None) -> None:
    """Set the current phase in context."""
    _phase_var.set(phase)


@contextmanager
def log_context(
    run_id: str | None = None,
    agent: str | None = None,
    phase: str | None = None,
) -> Generator[None, None, None]:
    """Context manager for scoped logging context.

    Args:
        run_id: Run ID to set in context.
        agent: Agent name to set in context.
        phase: Phase to set in context.

    Yields:
        None. Context variables are set for the duration of the context.
    """
    old_run_id = _run_id_var.get()
    old_agent = _agent_var.get()
    old_phase = _phase_var.get()

    try:
        if run_id is not None:
            _run_id_var.set(run_id)
        if agent is not None:
            _agent_var.set(agent)
        if phase is not None:
            _phase_var.set(phase)
        yield
    finally:
        _run_id_var.set(old_run_id)
        _agent_var.set(old_agent)
        _phase_var.set(old_phase)


class JSONFormatter(logging.Formatter):
    """JSON formatter for machine-readable log files.

    Produces JSON Lines format with structured context.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON."""
        log_obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add context variables
        run_id = get_run_id()
        agent = get_agent()
        phase = get_phase()

        if run_id:
            log_obj["run_id"] = run_id
        if agent:
            log_obj["agent"] = agent
        if phase:
            log_obj["phase"] = phase

        # Add extra fields from the record
        if hasattr(record, "extra"):
            log_obj["extra"] = record.extra

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str)


class ContextRichHandler(RichHandler):
    """Rich handler that includes context in console output."""

    def get_level_text(self, record: logging.LogRecord) -> Text:
        """Override to add context prefix."""
        level_text = super().get_level_text(record)

        # Build context prefix
        parts: list[str] = []
        run_id = get_run_id()
        agent = get_agent()
        phase = get_phase()

        if run_id:
            # Truncate run_id for readability
            short_id = run_id.split("_")[-1][:8] if "_" in run_id else run_id[:8]
            parts.append(f"[dim]{short_id}[/dim]")
        if phase:
            parts.append(f"[cyan]{phase}[/cyan]")
        if agent:
            parts.append(f"[magenta]{agent}[/magenta]")

        if parts:
            prefix = " ".join(parts)
            return Text.from_markup(f"{level_text} {prefix}")

        return level_text


class ContextLogger:
    """Logger wrapper that automatically attaches context to log calls.

    Wraps a standard logger and adds context variables to all log calls.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def name(self) -> str:
        """Get the logger name."""
        return self._logger.name

    def _log(
        self,
        level: int,
        msg: str,
        *args: Any,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Internal logging method that adds context."""
        extra = kwargs.pop("extra", {})

        # Add context to extra
        run_id = get_run_id()
        agent = get_agent()
        phase = get_phase()

        if run_id:
            extra["run_id"] = run_id
        if agent:
            extra["agent"] = agent
        if phase:
            extra["phase"] = phase

        # Merge any additional context from kwargs
        for key in list(kwargs.keys()):
            if key not in ("exc_info", "stack_info", "stacklevel"):
                extra[key] = kwargs.pop(key)

        self._logger.log(level, msg, *args, exc_info=exc_info, extra={"extra": extra})

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log info message."""
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log warning message."""
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, exc_info: bool = False, **kwargs: Any) -> None:
        """Log error message."""
        self._log(logging.ERROR, msg, *args, exc_info=exc_info, **kwargs)

    def critical(self, msg: str, *args: Any, exc_info: bool = False, **kwargs: Any) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, msg, *args, exc_info=exc_info, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log exception with traceback."""
        self._log(logging.ERROR, msg, *args, exc_info=True, **kwargs)


# Global console for rich output
_console: Console | None = None
_setup_done: bool = False


def get_console() -> Console:
    """Get the global rich console."""
    global _console
    if _console is None:
        _console = Console(stderr=True)
    return _console


def setup_logging(
    log_level: str = "INFO",
    log_file: Path | None = None,
    console_output: bool = True,
) -> None:
    """Set up logging with JSON file handler and rich console handler.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to log file. If None, only console logging is enabled.
        console_output: Whether to enable console output.
    """
    global _setup_done

    # Get root logger for the er package
    root_logger = logging.getLogger("er")
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # File handler with JSON formatting
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setFormatter(JSONFormatter())
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        root_logger.addHandler(file_handler)

    # Console handler with rich formatting
    if console_output:
        console = get_console()
        rich_handler = ContextRichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            markup=True,
        )
        rich_handler.setLevel(getattr(logging, log_level.upper()))
        root_logger.addHandler(rich_handler)

    # Prevent propagation to root logger
    root_logger.propagate = False

    # Also configure some noisy third-party loggers
    for noisy_logger in ["httpx", "httpcore", "urllib3", "asyncio"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    _setup_done = True


def get_logger(name: str) -> ContextLogger:
    """Get a context-aware logger.

    Args:
        name: Logger name (usually __name__).

    Returns:
        ContextLogger wrapper around the standard logger.
    """
    global _setup_done

    # Ensure logging is set up with defaults if not already done
    if not _setup_done:
        setup_logging()

    # Ensure name is under the er namespace
    if not name.startswith("er"):
        name = f"er.{name}"

    logger = logging.getLogger(name)
    return ContextLogger(logger)
