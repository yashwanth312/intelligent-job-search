from unittest.mock import MagicMock

from db.database import Database
from feedback_sync import _sync, _tracker_rows


def _db(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.initialize()
    for company in ("Acme", "Beta"):
        db.save_feedback(job_fingerprint=f"{company.lower()}||sre", company=company, title="SRE",
                         source="linkedin", screen_confidence=4, resume_angle="devops",
                         date_applied="2026-09-01")
    return db


def test_tracker_outcome_overrides_materials_status(tmp_path):
    db = _db(tmp_path)
    _sync(db, [{"Company": "Acme", "Job Title": "SRE", "Status": "Applied"}])
    updated, unmatched = _sync(db, [
        {"Company": "Acme", "Job Title": "SRE", "Status": "Phone Screen"},
        {"Company": "Beta", "Job Title": "SRE", "Status": ""},
        {"Company": "Gamma", "Job Title": "SRE", "Status": "Interview"},
    ])
    outcomes = {r["company"]: r["outcome"] for r in db.get_all_feedback()}
    db.close()
    assert outcomes == {"Acme": "phone_screen", "Beta": "applied"}
    assert (updated, unmatched) == (1, 1)


def test_tracker_rows_use_the_tabs_own_header_row():
    ws = MagicMock()
    ws.get_all_values.return_value = [
        ["Company", "Job Title", "Status", "Contact", ""],
        ["Acme", "SRE", "Interview", "", ""],
    ]
    assert _tracker_rows(ws)[0]["Status"] == "Interview"
