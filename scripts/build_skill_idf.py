"""Build data/skill_idf.json — per-skill document frequency over every stored JD.

The project scorer weights a JD skill by its rarity (inverse document
frequency): "python" is in ~60% of postings and says little about fit,
"active directory" is in ~8% and says a lot. Extraction over ~75k
descriptions takes a few minutes, so it runs offline here and the scorer only
reads the JSON. Re-run occasionally (monthly is plenty) as the corpus grows.

    python scripts/build_skill_idf.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DB_FILE  # noqa: E402
from generation.skill_taxonomy import extract  # noqa: E402

OUT = ROOT / "data" / "skill_idf.json"
MIN_DESC_CHARS = 200


def _skills(row: tuple[str, str]) -> list[str]:
    title, desc = row
    return sorted(extract(f"{title}\n{desc}"))


def main() -> None:
    conn = sqlite3.connect(ROOT / DB_FILE)
    rows = conn.execute(
        "SELECT title, description FROM jobs WHERE length(description) > ?",
        (MIN_DESC_CHARS,),
    ).fetchall()
    conn.close()

    df: Counter[str] = Counter()
    with Pool() as pool:
        for skills in pool.imap_unordered(_skills, rows, chunksize=200):
            df.update(skills)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(
        {"n_docs": len(rows), "df": dict(sorted(df.items()))}, indent=1,
    ))
    print(f"Wrote {OUT} — {len(rows):,} JDs, {len(df)} skills")


if __name__ == "__main__":
    main()
