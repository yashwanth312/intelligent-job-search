"""Verify a fresh install before the first real run.

    python scripts/check_setup.py             # offline checks only
    python scripts/check_setup.py --online    # also open your Google Sheet

Prints PASS / WARN / FAIL per check and exits 1 if anything FAILed. It never
calls Claude for generation and never writes to your Sheet.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252; never crash on a non-ASCII character.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PLACEHOLDER_MARKERS = ("jane doe", "example.com", "acme corp", "example labs")

_results: list[tuple[str, str, str]] = []


def record(level: str, name: str, detail: str = "") -> None:
    _results.append((level, name, detail))
    tag = {"PASS": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[level]
    print(f"{tag} {name}" + (f" — {detail}" if detail else ""))


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        record("PASS", "Python version", f"{v.major}.{v.minor}.{v.micro}")
    else:
        record("FAIL", "Python version", f"{v.major}.{v.minor} found, need 3.10+")


def check_imports() -> None:
    missing = []
    for mod in ("pydantic", "yaml", "dotenv", "jobspy", "aiohttp", "gspread",
                "googleapiclient", "google.oauth2", "bs4", "rich"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        record("FAIL", "Python packages", f"missing {', '.join(missing)} — run: pip install -r requirements.txt")
    else:
        record("PASS", "Python packages")


def check_env() -> None:
    import config
    if not (ROOT / ".env").exists():
        record("FAIL", ".env file", "copy .env.example to .env and fill it in")
        return
    problems = [n for n, v in (("YOUR_NAME", config.YOUR_NAME), ("YOUR_EMAIL", config.YOUR_EMAIL),
                               ("YOUR_PHONE", config.YOUR_PHONE)) if not v.strip()]
    if problems:
        record("FAIL", ".env personal info", f"empty: {', '.join(problems)}")
    elif any(m in (config.YOUR_NAME + config.YOUR_EMAIL).lower() for m in PLACEHOLDER_MARKERS):
        record("WARN", ".env personal info", "still contains the example placeholder values")
    else:
        record("PASS", ".env personal info")
    if not config.GOOGLE_DRIVE_FOLDER_ID:
        record("PASS", "Google Drive upload", "disabled (GOOGLE_DRIVE_FOLDER_ID empty) — PDFs stay in output/")


def check_credentials() -> None:
    import config
    path = Path(config.GOOGLE_SHEETS_CREDS_FILE)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        record("FAIL", "Google credentials", f"{path.name} not found — see README step 'Google Sheets'")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        email = data["client_email"]
        assert data.get("type") == "service_account"
    except Exception:
        record("FAIL", "Google credentials", f"{path.name} is not a service-account key file")
        return
    record("PASS", "Google credentials", f"service account {email} — share your Sheet with this address (Editor)")


def check_profile() -> None:
    import yaml
    from models.profile import Profile
    path = ROOT / "profile.yaml"
    if not path.exists():
        record("FAIL", "profile.yaml", "missing — run: cp profile.example.yaml profile.yaml, then edit it")
        return
    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw) or {}
        profile = Profile(**data)
    except Exception as exc:
        record("FAIL", "profile.yaml schema", str(exc).splitlines()[0][:200])
        return
    record("PASS", "profile.yaml schema",
           f"{len(profile.experiences)} experiences, {len(profile.projects)} projects, "
           f"{len(profile.certifications)} certifications")
    import config
    if config.YOUR_NAME.strip() and profile.personal.name.strip()             and config.YOUR_NAME.strip().lower() != profile.personal.name.strip().lower():
        record("WARN", "name consistency",
               f".env YOUR_NAME={config.YOUR_NAME!r} differs from profile personal.name={profile.personal.name!r} "
               "(the resume header uses .env, the body uses profile.yaml)")
    low = raw.lower()
    hits = [m for m in PLACEHOLDER_MARKERS if m in low]
    if hits:
        record("WARN", "profile.yaml placeholders", f"still contains example text: {', '.join(hits)}")
    if not profile.experiences:
        record("WARN", "profile.yaml experiences", "empty — generated resumes will have no work history")
    if len(profile.projects) < 3:
        record("WARN", "profile.yaml projects",
               f"{len(profile.projects)} project(s); resumes show the best 3, so add more if you have them")
    for exp in profile.experiences:
        if not exp.framings:
            record("FAIL", f"experience '{exp.company}'", "needs at least one framing with bullets")

    from generation.skill_taxonomy import SKILLS
    bad = []
    for p in profile.projects:
        for tier in ("core", "supporting", "touch"):
            bad += [f"{p.name}:{t}" for t in getattr(p.skills, tier) if t not in SKILLS]
    if bad:
        record("FAIL", "project skill tags", f"not in generation/skill_taxonomy.py: {', '.join(bad)}")
    elif profile.projects:
        untagged = [p.name for p in profile.projects if not (p.skills.core or p.skills.supporting)]
        if untagged:
            record("WARN", "project skill tags", f"untagged (will rarely be picked): {', '.join(untagged)}")
        else:
            record("PASS", "project skill tags")

    try:
        from generation.resume_engine import ResumeEngine
        from screening.stage2 import Stage2Screen
        ResumeEngine(profile_path=str(path))._build_system_prompt()
        Stage2Screen(profile_path=str(path))._build_system_prompt()
        record("PASS", "prompts build from your profile")
    except Exception as exc:
        record("FAIL", "prompts build from your profile", f"{type(exc).__name__}: {exc}"[:200])


def check_claude_cli() -> None:
    import config
    try:
        out = subprocess.run([config.CLAUDE_CLI, "--version"], capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            record("PASS", "Claude CLI", f"{config.CLAUDE_CLI} ({out.stdout.strip()[:40]})")
        else:
            record("FAIL", "Claude CLI", f"exit {out.returncode}: {out.stderr.strip()[:120]}")
    except (OSError, subprocess.SubprocessError):
        record("FAIL", "Claude CLI", "not found — npm install -g @anthropic-ai/claude-code, then run `claude` once to log in "
                                      "(or set CLAUDE_CLI in .env)")


def check_weasyprint() -> None:
    try:
        from weasyprint import HTML  # noqa: F401
        record("PASS", "WeasyPrint (PDF rendering)")
    except Exception:
        record("WARN", "WeasyPrint (PDF rendering)",
               "native libraries missing — resumes fall back to .html (print to PDF in a browser). See README, section Troubleshooting")


def check_h1b() -> None:
    import config
    from screening.lca_index import LcaIndex
    if not config.SPONSORSHIP_FILTER_ENABLED:
        record("PASS", "Sponsorship filter", "OFF (default) — set SPONSORSHIP_FILTER_ENABLED=true in .env if you need visa sponsorship")
        return
    idx = LcaIndex.load()
    if idx is None:
        record("FAIL", "H-1B index", "SPONSORSHIP_FILTER_ENABLED is on but data/h1b_filers.txt is missing")
    else:
        record("PASS", "H-1B index", f"{len(idx):,} employers, built {idx.built}")


def check_config() -> None:
    import config
    record("PASS", "Search config",
           f"{len(config.TARGET_TITLES)} titles x {len(config.LOCATIONS)} locations; "
           f"daily cutoff confidence >= {config.DAILY_MIN_CONFIDENCE}")
    if config.TARGET_TITLES == ["Software Engineer", "Backend Engineer", "Full Stack Engineer",
                                "Data Engineer", "DevOps Engineer", "Cloud Engineer"]:
        record("WARN", "Title gate", "config.py still has the neutral default titles — see README, section 'Tune the title gate'")


def check_online() -> None:
    import gspread
    import config
    from google.oauth2.service_account import Credentials
    from sheets.client import SCOPES
    try:
        creds = Credentials.from_service_account_file(config.GOOGLE_SHEETS_CREDS_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        ss = gc.open(config.SPREADSHEET_NAME)
        tabs = [w.title for w in ss.worksheets()]
        record("PASS", "Google Sheet reachable", f"'{ss.title}' tabs: {', '.join(tabs)}")
    except gspread.SpreadsheetNotFound:
        record("FAIL", "Google Sheet reachable",
               f"no sheet named {config.SPREADSHEET_NAME!r} shared with the service account — create it and share (Editor)")
    except Exception as exc:
        record("FAIL", "Google Sheet reachable", f"{type(exc).__name__}: {exc}"[:200])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--online", action="store_true", help="also open your Google Sheet (read-only)")
    args = ap.parse_args()

    check_python()
    check_imports()
    if not any(level == "FAIL" and name == "Python packages" for level, name, _ in _results):
        check_env()
        check_credentials()
        check_profile()
        check_config()
        check_h1b()
        check_claude_cli()
        check_weasyprint()
        if args.online:
            check_online()

    fails = sum(1 for level, _, _ in _results if level == "FAIL")
    warns = sum(1 for level, _, _ in _results if level == "WARN")
    print(f"\n{fails} failed, {warns} warnings.")
    if fails:
        print("Fix the FAIL items above, then re-run: python scripts/check_setup.py")
    else:
        print("Ready. Next: python main.py")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
