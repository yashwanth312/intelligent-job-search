"""Offline index of H-1B employers, built from DOL LCA disclosure files.

Replaced the live h1bdata.info lookup on 2026-10-09. That site began answering
"0 records found" for Microsoft, IBM, Google and JPMorganChase (throttling, as
far as could be told), and the checker could not tell that page from a real
miss, so it cached those employers as non-sponsors and dropped every posting.

The index is a sorted list of compact employer keys (lowercase alphanumerics,
legal suffix stripped). scripts/build_lca_index.py writes it from the quarterly
xlsx files; refresh it when DOL publishes a new quarter.
"""
from __future__ import annotations

import bisect
import pathlib
import re
from collections.abc import Iterable

DEFAULT_INDEX_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "h1b_filers.txt"

# Queries shorter than this match a filer only exactly: "ey" as a prefix would
# hit every "ey..." filer. Three letters prefix-match on purpose: DRW and CGI
# file as "DRW Holdings" and "CGI Technologies and Solutions", and the stray
# hits ("amd" -> "amdocs") only ever keep a job.
_MIN_PREFIX_LEN = 3

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def compact(text: str) -> str:
    """Lowercase and drop everything but letters and digits.

    Collapsing spaces as well as punctuation is what lets the job-board string
    "JPMorganChase" meet the filer "JPMORGAN CHASE & CO." — h1bdata's prefix
    search, which kept the spaces, missed it.
    """
    return _NON_ALNUM_RE.sub("", text.lower())


class LcaIndex:
    def __init__(self, keys: Iterable[str], *, built: str | None = None,
                 sources: Iterable[str] = ()) -> None:
        self._keys = sorted({k for k in keys if k})
        self._exact = set(self._keys)
        self.built = built
        self.sources = list(sources)

    def __len__(self) -> int:
        return len(self._keys)

    def matches(self, query: str) -> bool:
        """True if any filer key starts with this compact query (exactly equals
        it, for short queries). Prefix matching mirrors h1bdata.info and leans
        toward KEEP: a false hit costs one Stage 2 screen, a false miss drops
        the employer."""
        if not query:
            return False
        if len(query) < _MIN_PREFIX_LEN:
            return query in self._exact
        i = bisect.bisect_left(self._keys, query)
        return i < len(self._keys) and self._keys[i].startswith(query)

    def save(self, path: pathlib.Path) -> None:
        lines = [f"# built {self.built or ''}"]
        lines += [f"# source {s}" for s in self.sources]
        lines += self._keys
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path = DEFAULT_INDEX_PATH) -> "LcaIndex | None":
        """Read an index file. Missing or empty -> None, so the caller can't
        mistake "no data" for "no employer sponsors"."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        built, sources, keys = None, [], []
        for line in text.splitlines():
            if line.startswith("# built "):
                built = line[len("# built "):].strip() or None
            elif line.startswith("# source "):
                sources.append(line[len("# source "):].strip())
            elif line and not line.startswith("#"):
                keys.append(line)
        index = cls(keys, built=built, sources=sources)
        return index if len(index) else None
