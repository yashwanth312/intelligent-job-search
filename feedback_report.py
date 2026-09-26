"""Analyze application outcomes and generate recommendations."""
from __future__ import annotations

import json
import sys

from config import DB_FILE
from db.database import Database

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    db = Database(DB_FILE)
    db.initialize()
    feedback = db.get_all_feedback()
    db.close()

    if not feedback:
        print("No feedback data yet. Apply to some jobs and update outcomes first.")
        return

    # Source quality
    source_stats: dict[str, dict] = {}
    angle_stats: dict[str, dict] = {}
    confidence_stats: dict[int, dict] = {}
    project_stats: dict[str, dict] = {}
    admission_stats: dict[str, dict] = {}

    for row in feedback:
        # Materials rows marked Skipped were generated but never submitted —
        # counting them would understate every callback rate.
        if row.get("outcome") == "skipped":
            continue
        source = row.get("source", "unknown")
        angle = row.get("resume_angle", "unknown")
        conf = row.get("screen_confidence", 0)
        outcome = row.get("outcome", "applied")

        is_callback = outcome in ("phone_screen", "interview", "offer")

        # Source
        if source not in source_stats:
            source_stats[source] = {"applied": 0, "callbacks": 0}
        source_stats[source]["applied"] += 1
        if is_callback:
            source_stats[source]["callbacks"] += 1

        # Angle
        if angle not in angle_stats:
            angle_stats[angle] = {"used": 0, "callbacks": 0}
        angle_stats[angle]["used"] += 1
        if is_callback:
            angle_stats[angle]["callbacks"] += 1

        # Projects on the resume (generation.project_scorer) — a callback here
        # says which portfolio project to build first.
        for pid in json.loads(row.get("projects_used") or "[]"):
            stats = project_stats.setdefault(pid, {"used": 0, "callbacks": 0})
            stats["used"] += 1
            stats["callbacks"] += is_callback

        # Stage 1 title family that admitted the job (core | it_identity)
        if row.get("admission"):
            stats = admission_stats.setdefault(row["admission"], {"applied": 0, "callbacks": 0})
            stats["applied"] += 1
            stats["callbacks"] += is_callback

        # Confidence
        if conf not in confidence_stats:
            confidence_stats[conf] = {"applied": 0, "callbacks": 0}
        confidence_stats[conf]["applied"] += 1
        if is_callback:
            confidence_stats[conf]["callbacks"] += 1

    # Print reports
    print("\n" + "=" * 55)
    print("  FEEDBACK REPORT")
    print("=" * 55)

    print("\n  SOURCE QUALITY")
    print(f"  {'Source':<25} {'Applied':>8} {'Callbacks':>10} {'Rate':>8}")
    print("  " + "-" * 53)
    for source, stats in sorted(source_stats.items(), key=lambda x: x[1]["callbacks"], reverse=True):
        rate = (stats["callbacks"] / stats["applied"] * 100) if stats["applied"] else 0
        print(f"  {source:<25} {stats['applied']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    print("\n  RESUME ANGLE EFFECTIVENESS")
    print(f"  {'Angle':<25} {'Used':>8} {'Callbacks':>10} {'Rate':>8}")
    print("  " + "-" * 53)
    for angle, stats in sorted(angle_stats.items(), key=lambda x: x[1]["callbacks"], reverse=True):
        rate = (stats["callbacks"] / stats["used"] * 100) if stats["used"] else 0
        print(f"  {angle:<25} {stats['used']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    print("\n  SCREENING CALIBRATION")
    print(f"  {'Confidence':>10} {'Applied':>8} {'Callbacks':>10} {'Rate':>8}")
    print("  " + "-" * 38)
    for conf in sorted(confidence_stats.keys(), reverse=True):
        stats = confidence_stats[conf]
        rate = (stats["callbacks"] / stats["applied"] * 100) if stats["applied"] else 0
        print(f"  {conf:>10} {stats['applied']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    if project_stats:
        print("\n  PROJECTS ON RESUMES")
        print(f"  {'Project':<25} {'Used':>8} {'Callbacks':>10} {'Rate':>8}")
        print("  " + "-" * 53)
        for pid, stats in sorted(project_stats.items(),
                                 key=lambda x: (x[1]["callbacks"], x[1]["used"]), reverse=True):
            rate = stats["callbacks"] / stats["used"] * 100
            print(f"  {pid:<25} {stats['used']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    if admission_stats:
        print("\n  TITLE FAMILY (Stage 1 admission)")
        print(f"  {'Family':<25} {'Applied':>8} {'Callbacks':>10} {'Rate':>8}")
        print("  " + "-" * 53)
        for fam, stats in sorted(admission_stats.items()):
            rate = stats["callbacks"] / stats["applied"] * 100
            print(f"  {fam:<25} {stats['applied']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    print("\n" + "=" * 55 + "\n")


if __name__ == "__main__":
    main()
