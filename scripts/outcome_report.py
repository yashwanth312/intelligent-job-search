"""What converts? Callback rates across every application, in one pass.

Joins the feedback table (one row per generated application; outcomes synced
from the Materials + Tracker tabs by feedback_sync.py) with the cloud
auto-apply log (runs/applications.csv), de-duplicates re-scraped jobs, and
prints callback rates by title domain, source, month, Stage 1 admission,
screening confidence and resume project, plus the callbacks themselves.

Outcome semantics:
  callback  = phone_screen | interview | offer
  positive  = callback | reached_out           (recruiter made contact)
  skipped   = materials generated, never submitted -> excluded from rates
  applied / intended / submitted / blocked:*  = no response yet
Rates on fewer than 30 applications are marked "(low n)".

Usage:
  python scripts/outcome_report.py                       # everything
  python scripts/outcome_report.py --since 2026-09-13    # one window
  python scripts/outcome_report.py --split 2026-09-13    # before vs after a change
  python scripts/outcome_report.py --json out.json       # also dump rows for ad-hoc analysis
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "jobs.db"
APPS_CSV = ROOT / "runs" / "applications.csv"

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CALLBACK = {"phone_screen", "interview", "offer"}
POSITIVE = CALLBACK | {"reached_out"}
RANK = {"offer": 6, "interview": 5, "phone_screen": 4, "reached_out": 3,
        "rejected": 2, "no_response": 1}
LOW_N = 30

# First match wins; order puts the specific families before the broad ones.
DOMAINS = [
    ("MLOps / AI infra", r"\bmlops\b|\bllmops\b|ml (platform|infra)|ai (platform|infra)"),
    ("AI/ML", r"\bai\b|\bml\b|machine learning|\bllm\b|gen ?ai|generative|artificial intelligence|agentic"),
    ("SRE", r"site reliability|\bsre\b|reliability engineer"),
    ("Cloud", r"\bcloud\b"),
    ("DevOps", r"devops|dev ops|devsecops"),
    ("Network", r"network"),
    ("Security", r"security|\bsoc\b|cyber"),
    ("IT / Identity", r"sysadmin|system administrator|systems administrator|windows|identity|"
                      r"\biam\b|endpoint|m365|microsoft 365|vmware|\bit\b"),
    ("Systems / Infra / Platform", r"infrastructure|platform|systems|\bsde\b.*infra|production engineer"),
    ("Software", r"software|developer|\bsde\b|backend|back-end|full ?stack|programmer"),
    ("Data", r"\bdata\b|analytics|etl"),
]
DOMAIN_RES = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in DOMAINS]


def domain(title: str) -> str:
    for name, rx in DOMAIN_RES:
        if rx.search(title or ""):
            return name
    return "Other"


def norm_title(title: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (title or "").lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def load_feedback() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM feedback")]
    finally:
        con.close()
    # Re-scraped jobs produce duplicate rows (slightly different title/fingerprint):
    # collapse on company + normalized title, keeping the most advanced outcome.
    best: dict[tuple, dict] = {}
    for r in rows:
        key = ((r.get("company") or "").strip().lower(), norm_title(r.get("title")))
        cur = best.get(key)
        if cur is None or RANK.get(r.get("outcome"), 0) > RANK.get(cur.get("outcome"), 0):
            best[key] = r
    out = list(best.values())
    for r in out:
        r["domain"] = domain(r.get("title"))
        r["source_family"] = (r.get("source") or "unknown").split("-")[0].lower()
        r["month"] = (r.get("date_applied") or "")[:7]
    return out, len(rows)


def rate_table(title: str, rows: list[dict], key, min_n: int = 1) -> None:
    stats: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        keys = key(r)
        for k in keys if isinstance(keys, list) else [keys]:
            s = stats[str(k)]
            s[0] += 1
            s[1] += r["outcome"] in CALLBACK
            s[2] += r["outcome"] in POSITIVE
    shown = [(k, s) for k, s in stats.items() if s[0] >= min_n]
    if not shown:
        return
    print(f"\n{title}")
    print(f"  {'':<30}{'apps':>6}{'callbk':>8}{'rate':>8}{'positive':>10}{'rate':>8}")
    for k, (n, cb, pos) in sorted(shown, key=lambda kv: (-kv[1][1] / kv[1][0], -kv[1][0])):
        flag = "  (low n)" if n < LOW_N else ""
        print(f"  {k[:30]:<30}{n:>6}{cb:>8}{cb / n:>8.1%}{pos:>10}{pos / n:>8.1%}{flag}")


def report(rows: list[dict], label: str) -> None:
    rated = [r for r in rows if r.get("outcome") != "skipped"]
    cb = [r for r in rated if r["outcome"] in CALLBACK]
    pos = [r for r in rated if r["outcome"] in POSITIVE]
    dates = sorted(r["date_applied"] for r in rated if r.get("date_applied"))
    print(f"\n{'=' * 78}\n {label}: {len(rated)} applications "
          f"({dates[0] if dates else '?'} -> {dates[-1] if dates else '?'}), "
          f"{len(cb)} callbacks ({len(cb) / max(len(rated), 1):.2%}), "
          f"{len(pos)} positive ({len(pos) / max(len(rated), 1):.2%})\n{'=' * 78}")
    print("Outcomes:", dict(collections.Counter(r["outcome"] for r in rows).most_common()))

    rate_table("By title domain", rated, lambda r: r["domain"])
    rate_table("By source", rated, lambda r: r["source_family"], min_n=3)
    rate_table("By month applied", rated, lambda r: r["month"])
    rate_table("By Stage 2 confidence", rated, lambda r: r.get("screen_confidence"))
    rate_table("By Stage 1 admission (rows since it was recorded)",
               [r for r in rated if r.get("admission")], lambda r: r["admission"])
    rate_table("By resume project (rows since projects were recorded)",
               [r for r in rated if r.get("projects_used")],
               lambda r: json.loads(r["projects_used"] or "[]"))

    if pos:
        print("\nPositive responses:")
        for r in sorted(pos, key=lambda r: r.get("date_applied") or ""):
            print(f"  {r.get('date_applied')}  {r['outcome']:<13} {r['domain']:<27} "
                  f"{r.get('company')} | {r.get('title')} ({r['source_family']})")


def applications_log() -> None:
    if not APPS_CSV.exists():
        return
    with open(APPS_CSV, encoding="utf-8") as f:
        apps = list(csv.DictReader(f))
    if not apps:
        return
    status = collections.Counter(a["status"].split(":")[0].strip() for a in apps)
    print(f"\nCloud auto-apply log (runs/applications.csv): {len(apps)} attempts  {dict(status)}")
    blocked = collections.Counter(
        (a.get("detail") or a["status"]).split(";")[0][:70]
        for a in apps if a["status"].startswith("blocked"))
    for reason, n in blocked.most_common(8):
        print(f"  {n:>3}x blocked: {reason}")
    portals = collections.Counter(a.get("portal") for a in apps if a["status"] == "submitted")
    print("  submitted by portal:", dict(portals.most_common()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", help="only applications on/after YYYY-MM-DD")
    ap.add_argument("--split", help="compare before vs on/after YYYY-MM-DD")
    ap.add_argument("--json", help="write the de-duplicated rows to this path")
    args = ap.parse_args()

    rows, raw_n = load_feedback()
    print(f"feedback table: {raw_n} rows -> {len(rows)} after company+title de-dup")
    if args.since:
        rows = [r for r in rows if (r.get("date_applied") or "") >= args.since]

    if args.split:
        report([r for r in rows if (r.get("date_applied") or "") < args.split],
               f"BEFORE {args.split}")
        report([r for r in rows if (r.get("date_applied") or "") >= args.split],
               f"ON/AFTER {args.split}")
    else:
        report(rows, f"SINCE {args.since}" if args.since else "ALL APPLICATIONS")

    applications_log()

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
        print(f"\nrows written to {args.json}")


if __name__ == "__main__":
    main()
