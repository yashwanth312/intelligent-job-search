"""Per-project resume usage and callbacks, from the feedback table.

Writes data/project_usage.json in the shape the Portfolio Build Board
tracker reads from its `stats/usage` document:
    {"updated": "...", "projects": {"<id>": {"used": n, "callbacks": n}}}
Ask Claude to push it to the tracker, or just read the printout.

    python scripts/project_usage.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_FILE  # noqa: E402

CALLBACK_OUTCOMES = ("phone_screen", "interview", "offer")
OUT = ROOT / "data" / "project_usage.json"


def main() -> None:
    conn = sqlite3.connect(ROOT / DB_FILE)
    rows = conn.execute(
        "SELECT projects_used, outcome FROM feedback WHERE projects_used IS NOT NULL"
    ).fetchall()
    conn.close()

    projects: dict[str, dict[str, int]] = {}
    for used, outcome in rows:
        for pid in json.loads(used or "[]"):
            stats = projects.setdefault(pid, {"used": 0, "callbacks": 0})
            stats["used"] += 1
            stats["callbacks"] += outcome in CALLBACK_OUTCOMES

    payload = {"updated": datetime.now().isoformat(timespec="seconds"), "projects": projects}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"{len(rows)} applications with project data → {OUT}")
    for pid, s in sorted(projects.items(), key=lambda x: (-x[1]["callbacks"], -x[1]["used"])):
        print(f"  {pid:<24} used {s['used']:>4}   callbacks {s['callbacks']:>3}")


if __name__ == "__main__":
    main()
