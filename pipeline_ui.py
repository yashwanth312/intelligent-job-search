"""PipelineUI: rich-based dashboard for the main scrape+screen pipeline.

Design:
  - Phase-based: each top-level step is numbered [1/N] with live elapsed timer.
  - Live scraper table: per-source status + job counts, updated as adapters finish.
  - Progress bars for the two loops with known totals: backfill + stage2.
  - Summary panel at the end with the most important numbers.
  - Graceful TTY fallback: non-TTY stdout (cron / log capture) gets plain lines.

Logging coexistence:
  The full debug trail still writes to logs/run_YYYY-MM-DD.log via the root
  logger's FileHandler. Console log output is routed through rich.logging.RichHandler
  so it interleaves cleanly with Live regions.
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from typing import Callable, Iterator

from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    return str(timedelta(seconds=int(seconds)))


def _ensure_utf8_stdout() -> None:
    """Rich emits UTF-8 glyphs (✓, ⠋, box chars). Default Windows cmd is cp1252,
    which blows up with UnicodeEncodeError. Reconfigure once, idempotently."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _enable_windows_ansi() -> None:
    """Enable ANSI processing and disable QuickEdit Mode on Windows.

    QuickEdit Mode (default on) pauses the process whenever the user clicks
    the console window, requiring Enter to resume — looks like the app froze.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        # Fix stdout: enable Virtual Terminal Processing (ANSI codes)
        stdout_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)

        # Fix stdin: disable QuickEdit + enable Extended flags so the console
        # never pauses the process on a mouse click.
        stdin_handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        in_mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(stdin_handle, ctypes.byref(in_mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            new_mode = (in_mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE
            kernel32.SetConsoleMode(stdin_handle, new_mode)
    except Exception:
        pass


def install_rich_logging(file_log_path: str | None = None, level: int = logging.INFO) -> Console:
    """Configure root logger: RichHandler for console + optional FileHandler.

    Returns the Console instance used by RichHandler (the same one UI should use).
    """
    _ensure_utf8_stdout()
    _enable_windows_ansi()
    console = Console()
    handlers: list[logging.Handler] = [
        RichHandler(
            console=console,
            rich_tracebacks=True,
            show_time=False,
            show_path=False,
            markup=False,
        )
    ]
    if file_log_path:
        fh = logging.FileHandler(file_log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        handlers.append(fh)

    # Reset root handlers so this module wins if called twice.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)

    return console


class _ScrapeTracker:
    """Live-updating table of per-adapter scrape status."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"

    def __init__(self, sources: list[tuple[str, str]]):
        # sources: [(adapter_name, display_name), ...]
        self._sources = sources
        self._by_name = {n: i for i, (n, _) in enumerate(sources)}
        self._status = [self.STATUS_RUNNING] * len(sources)
        self._counts = [0] * len(sources)
        self._errors = [""] * len(sources)
        self._starts = [time.time()] * len(sources)
        self._ends: list[float | None] = [None] * len(sources)

    def mark_done(self, adapter_name: str, job_count: int, error: str | None = None) -> None:
        i = self._by_name.get(adapter_name)
        if i is None:
            return
        self._counts[i] = job_count
        self._ends[i] = time.time()
        self._status[i] = self.STATUS_ERROR if error else self.STATUS_DONE
        self._errors[i] = error or ""

    def __rich__(self) -> Table:
        return self.render()

    def render(self) -> Table:
        t = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            padding=(0, 1),
        )
        t.add_column("Source", style="white", no_wrap=True)
        t.add_column("Status", justify="center", width=6)
        t.add_column("Jobs", justify="right", width=6)
        t.add_column("Elapsed", justify="right", width=10)

        for i, (_, display) in enumerate(self._sources):
            status = self._status[i]
            if status == self.STATUS_RUNNING:
                status_cell = Text("⠋", style="yellow")
            elif status == self.STATUS_DONE:
                status_cell = Text("✓", style="green")
            elif status == self.STATUS_ERROR:
                status_cell = Text("✗", style="red")
            else:
                status_cell = Text("·", style="dim")

            end = self._ends[i] if self._ends[i] is not None else time.time()
            elapsed = end - self._starts[i]

            jobs_cell = Text(str(self._counts[i]), style="bold" if self._counts[i] else "dim")
            elapsed_cell = Text(_fmt_elapsed(elapsed), style="dim")

            t.add_row(display, status_cell, jobs_cell, elapsed_cell)

        return t


class PipelineUI:
    """Top-level orchestrator for all user-visible console output."""

    def __init__(
        self,
        total_phases: int,
        console: Console | None = None,
        title: str = "INTELLIGENT JOB SEARCH",
    ):
        if console is None:
            _ensure_utf8_stdout()
            _enable_windows_ansi()
            console = Console()
        self.console = console
        self.total_phases = total_phases
        self.title = title
        self._run_start = time.time()
        self._phase_start: float | None = None
        self._current_phase: int = 0
        self._current_name: str = ""
        self._is_tty = self.console.is_terminal

    def banner(self, subtitle: str = "") -> None:
        body = Text(self.title, style="bold cyan")
        if subtitle:
            body.append(f"\n{subtitle}", style="dim")
        self.console.print(Panel(body, border_style="cyan", padding=(0, 2)))

    def phase(self, n: int, name: str) -> None:
        self._current_phase = n
        self._current_name = name
        self._phase_start = time.time()
        self.console.print(
            f"\n[bold cyan]\\[{n}/{self.total_phases}][/bold cyan] "
            f"[bold white]{name}[/bold white][dim]  …[/dim]"
        )

    def phase_done(self, detail: str = "") -> None:
        if self._phase_start is None:
            return
        elapsed = time.time() - self._phase_start
        tail = f" [dim]· {detail}[/dim]" if detail else ""
        self.console.print(
            f"     [green]✓[/green] [dim]{self._current_name} — "
            f"{_fmt_elapsed(elapsed)}[/dim]{tail}"
        )
        self._phase_start = None

    @contextmanager
    def scrape_table(
        self,
        sources: list[tuple[str, str]],
    ) -> Iterator[_ScrapeTracker]:
        """Live-updating per-source scrape status table.

        sources: list of (adapter_name, display_name) tuples. adapter_name is
        what orchestrator passes to the callback; display_name is shown in the table.
        """
        tracker = _ScrapeTracker(sources)
        if not self._is_tty:
            self.console.print(f"     scraping {len(sources)} sources...")
            yield tracker
            # Print final static table
            self.console.print(tracker.render())
            return

        with Live(
            tracker,
            console=self.console,
            refresh_per_second=4,
            transient=False,
        ) as live:
            tracker._live = live  # type: ignore[attr-defined]
            yield tracker
            live.update(tracker)

    @contextmanager
    def progress(self, label: str, total: int) -> Iterator[Callable[[int], None]]:
        """Progress bar with elapsed/ETA. Yields an `advance(n)` callable."""
        if total <= 0:
            # Nothing to do; no-op advance.
            yield lambda n=1: None
            return

        columns = [
            TextColumn(f"     [cyan]{label}[/cyan]"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("[dim]{task.completed}/{task.total}[/dim]"),
            TimeElapsedColumn(),
            TextColumn("[dim]ETA[/dim]"),
            TimeRemainingColumn(),
        ]
        with Progress(
            *columns,
            console=self.console,
            transient=False,
        ) as prog:
            task_id = prog.add_task(label, total=total)

            def _advance(n: int = 1):
                prog.update(task_id, advance=n)

            yield _advance

    def summary(
        self,
        stats: dict[str, str | int],
        top_apply: tuple[str, int] | None = None,
        log_path: str | None = None,
    ) -> None:
        """Final panel: stats + best match + total elapsed."""
        total_elapsed = time.time() - self._run_start
        lines: list[Text] = []
        label_width = max((len(k) for k in stats), default=0) + 2
        for k, v in stats.items():
            label = Text(f"{k.ljust(label_width)}", style="dim")
            value_str = f"{v:,}" if isinstance(v, int) else str(v)
            label.append(value_str, style="bold white")
            lines.append(label)
        lines.append(Text(""))
        lines.append(Text(f"{'Total elapsed'.ljust(label_width)}", style="dim").append(
            _fmt_elapsed(total_elapsed), style="bold cyan"
        ))
        if top_apply:
            name, conf = top_apply
            lines.append(Text(""))
            lines.append(Text("Top match: ", style="dim").append(
                f"{name}  ", style="bold white"
            ).append(f"(confidence {conf}/5)", style="green"))
        if log_path:
            lines.append(Text(""))
            lines.append(Text(f"Full log: {log_path}", style="dim"))

        body = Text("\n").join(lines)
        self.console.print(
            Panel(body, title="[bold]Run complete[/bold]",
                  border_style="green", padding=(1, 2))
        )

    def warn(self, msg: str) -> None:
        self.console.print(f"     [yellow]![/yellow] [yellow]{msg}[/yellow]")

    def error(self, msg: str) -> None:
        self.console.print(f"     [red]✗ {msg}[/red]")
