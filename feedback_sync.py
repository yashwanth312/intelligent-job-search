"""Sync Applied tab outcomes to SQLite for feedback analysis."""
from __future__ import annotations

import logging
import sys

from config import DB_FILE
from db.database import Database
from sheets.client import SheetsClient
from sheets import applied as applied_ops

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


OUTCOME_MAP = {
    "applied": "applied",
    "skipped": "skipped",
    "phone screen": "phone_screen",
    "interview": "interview",
    "offer": "offer",
    "rejected": "rejected",
    "no response": "no_response",
    "reached out": "reached_out",
}


def _tracker_rows(ws) -> list[dict]:
    """Tracker rows keyed by its own header row — the tab carries columns
    (e.g. "Contact") beyond config.TRACKER_HEADERS, so don't pin headers."""
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    return [dict(zip(header, r)) for r in values[1:]]


def _sync(db: Database, rows: list[dict]) -> tuple[int, int]:
    updated = unmatched = 0
    for row in rows:
        status = str(row.get("Status", "")).strip().lower()
        if not status or status == "ready to apply":
            continue
        fingerprint = (f"{str(row.get('Company', '')).strip().lower()}||"
                       f"{str(row.get('Job Title', '')).strip().lower()}")
        if db.update_feedback_outcome(fingerprint, OUTCOME_MAP.get(status, status)):
            updated += 1
        else:
            unmatched += 1
    return updated, unmatched


def main():
    db = Database(DB_FILE)
    db.initialize()
    sheets = SheetsClient()

    # Materials first (applied/skipped), then Tracker — where interview,
    # phone screen and rejection outcomes are actually recorded — so a real
    # outcome overrides the plain "applied".
    m_upd, m_miss = _sync(db, applied_ops.get_all_applied(sheets.get_applied_sheet()))
    t_upd, t_miss = _sync(db, _tracker_rows(sheets.get_tracker_sheet()))
    db.close()
    print(f"Synced {m_upd} outcomes from Materials and {t_upd} from Tracker to SQLite "
          f"({m_miss + t_miss} rows had no matching feedback record).")


if __name__ == "__main__":
    main()
