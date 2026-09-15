"""
============================================================
  USAGE REPORT — Claude CLI token/cost visibility
============================================================
  Reads the claude_usage table (populated by every headless
  `claude -p` call in generation/claude_cli.py) and prints
  cumulative usage broken down by purpose (screening vs
  resume/cover-letter generation vs verification) for today,
  the last 7 days, and all time.

  Usage:
      python usage_report.py

  Note: token counts and cost are real; the dollar figure is a
  LOCAL ESTIMATE Claude Code computes from token counts, not an
  actual charge — this project runs on a Max subscription, not
  pay-per-token API billing. Claude Code does not expose your
  Max-plan rate-limit percentage (5-hour / weekly caps) to
  headless calls at all. To check that, run `claude` yourself
  and type `/usage`.
============================================================
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.table import Table

from config import DB_FILE
from db.database import Database

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

console = Console()


def _aggregate(rows: list[dict]) -> dict[str, dict]:
    """Group rows by purpose, summing tokens/cost and counting calls."""
    by_purpose: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        "cost_usd": 0.0,
    })
    for r in rows:
        agg = by_purpose[r["purpose"] or "other"]
        agg["calls"] += 1
        agg["input_tokens"] += r["input_tokens"] or 0
        agg["output_tokens"] += r["output_tokens"] or 0
        agg["cache_read_input_tokens"] += r["cache_read_input_tokens"] or 0
        agg["cache_creation_input_tokens"] += r["cache_creation_input_tokens"] or 0
        agg["cost_usd"] += r["cost_usd"] or 0
    return dict(by_purpose)


def _render_table(title: str, rows: list[dict]) -> Table:
    table = Table(title=title, border_style="dim", header_style="bold cyan")
    table.add_column("Purpose", style="white")
    table.add_column("Calls", justify="right")
    table.add_column("Input tok", justify="right")
    table.add_column("Output tok", justify="right")
    table.add_column("Cache read", justify="right")
    table.add_column("Est. cost", justify="right", style="green")

    if not rows:
        table.add_row("[dim]no calls in this window[/dim]", "", "", "", "", "")
        return table

    by_purpose = _aggregate(rows)
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cost_usd": 0.0}
    for purpose, agg in sorted(by_purpose.items()):
        table.add_row(
            purpose, str(agg["calls"]),
            f"{agg['input_tokens']:,}", f"{agg['output_tokens']:,}",
            f"{agg['cache_read_input_tokens']:,}", f"${agg['cost_usd']:.2f}",
        )
        for k in totals:
            totals[k] += agg[k]
    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]", f"[bold]{totals['calls']}[/bold]",
        f"[bold]{totals['input_tokens']:,}[/bold]",
        f"[bold]{totals['output_tokens']:,}[/bold]",
        f"[bold]{totals['cache_read_input_tokens']:,}[/bold]",
        f"[bold]${totals['cost_usd']:.2f}[/bold]",
    )
    return table


def main() -> None:
    db = Database(DB_FILE)
    db.initialize()
    all_rows = db.get_claude_usage_rows()
    db.close()

    if not all_rows:
        console.print(
            "\n[yellow]No Claude usage recorded yet.[/yellow] "
            "Run `python main.py` or `python generate_materials.py` first.\n"
        )
        return

    now = datetime.now(timezone.utc)
    today_start = now.strftime("%Y-%m-%d 00:00:00")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    today_rows = [r for r in all_rows if r["ts"] >= today_start]
    week_rows = [r for r in all_rows if r["ts"] >= week_start]

    console.print()
    console.print(_render_table("Today", today_rows))
    console.print()
    console.print(_render_table("Last 7 days", week_rows))
    console.print()
    console.print(_render_table("All time", all_rows))
    console.print()
    console.print(
        "[dim]Cost is a local estimate Claude Code computes from token counts — "
        "not an actual charge (this pipeline runs on a Max subscription, never "
        "pay-per-token billing).[/dim]"
    )
    console.print(
        "[dim]Max-plan rate-limit % (5-hour / weekly caps) is not exposed to "
        "headless calls — run `claude` yourself and type [bold]/usage[/bold] "
        "to check it.[/dim]\n"
    )


if __name__ == "__main__":
    main()
