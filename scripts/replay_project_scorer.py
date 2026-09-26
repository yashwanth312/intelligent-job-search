"""Replay the resume project scorer over past applications — no Claude calls.

Shows how often each project would be picked, how much of each JD's weighted
skill demand the 3 picks cover, which JD skills no project covers (catalog
gaps), and a sample of picks to eyeball. Run after editing a spec's skill
tags, the taxonomy, or scorer weights.

    python scripts/replay_project_scorer.py
    python scripts/replay_project_scorer.py --since 2026-09-13 --samples 30
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import DB_FILE  # noqa: E402
from generation.portfolio import load_portfolio  # noqa: E402
from generation.project_scorer import IDF_PATH, ProjectScorer  # noqa: E402
from generation.skill_taxonomy import label  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="only applications on/after YYYY-MM-DD")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if not IDF_PATH.exists():
        print(f"⚠ {IDF_PATH} missing — every skill weighs the same. "
              f"Run: python scripts/build_skill_idf.py\n")

    pool = load_portfolio(ROOT / "profile.yaml")
    scorer = ProjectScorer(pool)
    conn = sqlite3.connect(ROOT / DB_FILE)
    rows = conn.execute(
        "SELECT DISTINCT j.title, j.company, j.description FROM feedback f "
        "JOIN jobs j ON j.fingerprint = f.job_fingerprint "
        "WHERE length(j.description) > 200 AND f.date_applied >= ?",
        (args.since,),
    ).fetchall()
    conn.close()
    if not rows:
        print("No applied jobs with descriptions in range.")
        return

    picks: Counter[str] = Counter()
    firsts: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    coverages: list[float] = []
    results = []
    for title, company, desc in rows:
        sel = scorer.select(title, desc)
        picks.update(sel.ids)
        firsts[sel.ids[0]] += 1
        gaps.update(sel.uncovered[:3])
        coverages.append(sel.coverage)
        results.append((title, company, sel))

    n = len(rows)
    names = {p.id: f"{p.name} ({p.kind})" for p in pool}
    print(f"\nReplayed {n:,} applied JDs{' since ' + args.since if args.since else ''}")
    print(f"Mean weighted skill coverage of the 3 picks: {sum(coverages) / n:.1%}\n")

    print(f"  {'Project':<34}{'On resumes':>12}{'Ranked #1':>11}")
    print("  " + "-" * 57)
    for pid in sorted(names, key=lambda i: picks[i], reverse=True):
        print(f"  {names[pid]:<34}{picks[pid] / n:>11.0%}{firsts[pid] / n:>11.0%}")

    print("\nMost frequent uncovered JD skills (catalog gap signal):")
    for skill, c in gaps.most_common(12):
        print(f"  {label(skill):<34}{c / n:>6.0%} of JDs")

    print(f"\nSample picks ({min(args.samples, n)}):")
    random.Random(args.seed).shuffle(results)
    for title, company, sel in results[:args.samples]:
        print(f"  {company[:22]:<22} {title[:44]:<44} → {', '.join(sel.names)}  [{sel.coverage:.0%}]")
    print()


if __name__ == "__main__":
    main()
