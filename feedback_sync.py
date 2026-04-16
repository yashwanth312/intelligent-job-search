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


def main():
    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    applied_ws = sheets.get_applied_sheet()
    rows = applied_ops.get_all_applied(applied_ws)

    updated = 0
    for row in rows:
        company = row.get("Company", "")
        title = row.get("Job Title", "")
        status = row.get("Status", "")
        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"

        if status and status.lower() not in ("ready to apply", ""):
            outcome_map = {
                "applied": "applied",
                "phone screen": "phone_screen",
                "interview": "interview",
                "offer": "offer",
                "rejected": "rejected",
                "no response": "no_response",
            }
            outcome = outcome_map.get(status.lower(), status.lower())
            db.update_feedback_outcome(fingerprint, outcome)
            updated += 1

    db.close()
    print(f"Synced {updated} outcomes from Applied tab to SQLite.")


if __name__ == "__main__":
    main()
