"""A fresh clone has no profile.yaml, .env, credentials.json or jobs.db.

These tests guard against code that only works on the author's machine, such
as importing a module that is gitignored and so never reaches the repository.
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "*.py"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines()
            if line and not line.startswith(("tests/", "examples/"))]


@pytest.mark.parametrize("path", _tracked_python_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_module_imports_without_personal_files(path):
    """Every module imports (scripts with a __main__ guard are safe to import)."""
    rel = path.relative_to(ROOT).with_suffix("")
    name = ".".join(rel.parts)
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    importlib.import_module(name)


def test_database_creates_itself_in_an_empty_directory(tmp_path):
    from db.database import Database
    db = Database(str(tmp_path / "jobs.db"))
    db.initialize()
    assert (tmp_path / "jobs.db").exists()
    del db


def test_pipeline_ui_is_tracked_not_ignored():
    """main.py imports it; it once lived in a gitignored output/ folder."""
    out = subprocess.run(["git", "check-ignore", "pipeline_ui.py"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 1, "pipeline_ui.py is gitignored"


def test_no_personal_identifiers_in_tracked_files():
    banned = ["yashw", "medisetti", "yashwanthsaikrishna", "404this", "KV Bits",
              "Ocklet", "DiaSense", "Texas Instruments"]
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.splitlines()
    skip_suffix = (".png", ".jpg", ".pdf", ".xlsx")
    skip_names = {"tests/test_fresh_clone.py"}
    hits = []
    for rel in files:
        if rel in skip_names or rel.endswith(skip_suffix) or rel.startswith("data/h1b_filers"):
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        # The public repo's own clone URL is the one legitimate mention.
        text = p.read_text(encoding="utf-8", errors="ignore").lower().replace("yashwanth312", "")
        hits += [f"{rel}: {b}" for b in banned if b.lower() in text]
    assert not hits, "personal identifiers found:\n" + "\n".join(hits)


def test_check_setup_survives_a_cp1252_console(tmp_path):
    """Windows consoles default to cp1252; the script prints non-ASCII text."""
    import os
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_setup.py")], cwd=tmp_path,
                         env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert "Traceback" not in out.stderr, out.stderr
    assert out.returncode in (0, 1)


def test_text_files_are_opened_as_utf8():
    """open()/read_text() without an encoding use cp1252 on Windows and break
    on the em dashes and arrows that profiles and templates contain."""
    import re
    offenders = []
    pattern = re.compile(r"""(?<![\w.])open\((?![^)]*encoding)[^)]*\)|\.read_text\(\s*\)""")
    for path in _tracked_python_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if pattern.search(code) and '"rb"' not in code and '"wb"' not in code:
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
