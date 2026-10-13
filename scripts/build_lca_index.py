"""Build data/h1b_filers.txt, the H-1B employer index Phase 5 checks against.

Input is the DOL OFLC LCA disclosure data (one xlsx per fiscal-year quarter),
from https://www.dol.gov/agencies/eta/foreign-labor/performance — "LCA
Programs (H-1B, H-1B1, E-3)". dol.gov answers scripted downloads with 403, so
fetch the files in a browser and drop them in data/lca/ (gitignored). Keep the
latest eight quarters, roughly the two-year window the old h1bdata.info check
used, and re-run when DOL posts a new quarter.

Every employer and trade name on a certified H-1B LCA becomes one compact key
(see H1BChecker.filer_key). Each file takes a minute or two to read.

    python scripts/build_lca_index.py
"""
from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import date
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from screening.h1b_checker import H1BChecker  # noqa: E402
from screening.lca_index import DEFAULT_INDEX_PATH, LcaIndex  # noqa: E402

LCA_DIR = ROOT / "data" / "lca"
_COLUMNS = ("CASE_STATUS", "VISA_CLASS", "EMPLOYER_NAME", "TRADE_NAME_DBA")


def collect_filer_keys(rows: Iterable[dict]) -> set[str]:
    """Index keys for every employer and trade name on a certified H-1B LCA.

    "Certified - Withdrawn" still shows the employer filed; "Denied" and
    "Withdrawn" (pulled before certification) do not count.
    """
    keys: set[str] = set()
    for row in rows:
        if row.get("VISA_CLASS") != "H-1B":
            continue
        if not str(row.get("CASE_STATUS") or "").startswith("Certified"):
            continue
        for field in ("EMPLOYER_NAME", "TRADE_NAME_DBA"):
            name = str(row.get(field) or "").strip()
            if name:
                key = H1BChecker.filer_key(name)
                if key:
                    keys.add(key)
    return keys


def _xlsx_rows(path: Path) -> Iterable[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = next(rows)
        idx = {c: header.index(c) for c in _COLUMNS if c in header}
        missing = set(_COLUMNS) - set(idx)
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
        for r in rows:
            yield {c: r[i] for c, i in idx.items()}
    finally:
        wb.close()


def _keys_for_file(path: Path) -> tuple[str, set[str]]:
    return path.name, collect_filer_keys(_xlsx_rows(path))


def main() -> None:
    files = sorted(LCA_DIR.glob("*.xlsx"))
    if not files:
        sys.exit(f"No LCA xlsx files in {LCA_DIR} — see this script's docstring.")
    print(f"Reading {len(files)} LCA file(s) from {LCA_DIR} ...")

    keys: set[str] = set()
    with Pool(min(len(files), 4)) as pool:
        for name, file_keys in pool.imap_unordered(_keys_for_file, files):
            print(f"  {name}: {len(file_keys):,} employers")
            keys |= file_keys

    index = LcaIndex(keys, built=date.today().isoformat(), sources=[f.name for f in files])
    index.save(DEFAULT_INDEX_PATH)
    print(f"Wrote {len(index):,} employer keys to {DEFAULT_INDEX_PATH}")


if __name__ == "__main__":
    main()
