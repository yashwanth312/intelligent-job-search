"""Analyze application outcomes and generate recommendations."""
from __future__ import annotations

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

    for row in feedback:
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

    print("\n" + "=" * 55 + "\n")


if __name__ == "__main__":
    main()
