"""Discover public ATS job boards and add them to target_companies.yaml.

Direct-ATS postings are fresher and far less contested than the same role on
LinkedIn, which supplied ~90% of applications in the 2026-04→09 cohort. The
board list was hand-curated until now, which capped it at a couple of hundred
companies; this finds them at scale instead.

Method: every company name the pipeline has ever seen is already in jobs.db.
Slugifying those names into candidate board tokens and probing the four public
ATS APIs turns that history into a board list — no external company database
needed, and the candidates are companies that demonstrably post jobs the
pipeline cares about. Measured hit rate is ~15-17% of slugs.

    greenhouse  https://boards-api.greenhouse.io/v1/boards/{token}/jobs
    lever       https://api.lever.co/v0/postings/{token}
    ashby       https://api.ashbyhq.com/posting-api/job-board/{token}

A board is kept only if it responds 200 AND currently lists at least one
posting. `--min-infra N` additionally requires N titles that pass Stage 1's
domain filter, which trades reach for relevance.

Run:  python scripts/discover_ats_boards.py --limit 4000
      python scripts/discover_ats_boards.py --limit 4000 --apply
      python scripts/discover_ats_boards.py --limit 4000 --min-infra 1 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sqlite3
import sys

import aiohttp
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config import TITLE_DOMAIN_KEYWORDS, EXCLUDE_TITLE_KEYWORDS  # noqa: E402

TARGET_YAML = _REPO_ROOT / "target_companies.yaml"
DB_PATH = _REPO_ROOT / "jobs.db"

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "lever": "https://api.lever.co/v0/postings/{}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
}

_DOMAIN_RES = [
    re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE)
    for k in TITLE_DOMAIN_KEYWORDS
]

_LEGAL_RE = re.compile(
    r"\b(inc|llc|corp|corporation|ltd|limited|co|plc|llp|lp|gmbh|the)\b\.?",
    re.IGNORECASE,
)


def _is_infra_title(title: str) -> bool:
    low = title.lower()
    if any(kw in low for kw in EXCLUDE_TITLE_KEYWORDS):
        return False
    return any(rx.search(title) for rx in _DOMAIN_RES)


def _slugs(name: str) -> set[str]:
    """Candidate board tokens for a company name.

    Tokens are usually the lowercased, unpunctuated company name, but boards
    registered under a display name keep its casing. Both shapes are generated
    and probed — a wrong-shaped guess just 404s.
    """
    cleaned = re.sub(r"[\(\[].*?[\)\]]", " ", name)
    cleaned = re.split(r"[|,]| - ", cleaned)[0]
    cleaned = _LEGAL_RE.sub(" ", cleaned)
    words = re.sub(r"[^A-Za-z0-9\s]", " ", cleaned).split()
    if not words:
        return set()

    joined = "".join(words)
    out = {
        joined.lower(),
        joined,
        "".join(w.capitalize() for w in words),
        words[0].lower(),
        words[0].capitalize(),
    }
    if len(words) >= 2:
        out.add((words[0] + words[1]).lower())
        out.add(words[0].capitalize() + words[1].capitalize())
    return {s for s in out if 3 <= len(s) <= 40}


def _titles_from(kind: str, payload) -> list[str]:
    if kind == "greenhouse":
        return [j.get("title", "") for j in (payload or {}).get("jobs", [])]
    if kind == "lever":
        return [j.get("text", "") for j in payload] if isinstance(payload, list) else []
    return [j.get("title", "") for j in (payload or {}).get("jobs", [])]


def _display_name(kind: str, token: str, payload) -> str:
    if kind == "ashby":
        name = (payload or {}).get("name")
        if name:
            return name
    return token


async def _probe(session, sem, kind: str, token: str) -> dict | None:
    async with sem:
        try:
            async with session.get(
                ENDPOINTS[kind].format(token),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json(content_type=None)
        except Exception:
            return None

    titles = [t for t in _titles_from(kind, payload) if t]
    if not titles:
        return None
    return {
        "kind": kind,
        "token": token,
        "name": _display_name(kind, token, payload),
        "total": len(titles),
        "infra": sum(1 for t in titles if _is_infra_title(t)),
    }


def _company_names(limit: int) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT company, COUNT(*) c FROM jobs WHERE company IS NOT NULL "
        "AND length(company) > 2 GROUP BY company ORDER BY c DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def _existing_tokens() -> dict[str, set[str]]:
    """Tokens already configured, lowercased.

    These APIs treat the board slug case-insensitively, so "OpenAI" and "openai"
    are the same board — comparing case-sensitively adds a second copy of a
    company already on the list and scrapes it twice every run.
    """
    data = yaml.safe_load(TARGET_YAML.read_text(encoding="utf-8")) or {}
    return {
        kind: {str(e["token"]).lower() for e in data.get(kind, []) if "token" in e}
        for kind in ENDPOINTS
    }


def _append(found: dict[str, list[dict]]) -> int:
    """Append discovered boards to their sections, creating sections as needed."""
    text = TARGET_YAML.read_text(encoding="utf-8")
    lines = text.split("\n")

    starts = {}
    for i, line in enumerate(lines):
        m = re.match(r"^([a-z_]+):\s*$", line)
        if m:
            starts[m.group(1)] = i
    order = sorted(starts.items(), key=lambda kv: kv[1])

    header = "  # ── Auto-discovered by scripts/discover_ats_boards.py ──"
    inserts: dict[int, list[str]] = {}
    new_sections: list[str] = []
    total = 0

    for kind, boards in found.items():
        if not boards:
            continue
        block = [header]
        for b in boards:
            # Always quote. Slugs like "8451" (84.51°) and "true" are otherwise
            # read back as an int and a bool, and every consumer expects a str.
            block += [
                f"- token: {json.dumps(str(b['token']))}",
                f"  name: {json.dumps(str(b['name']))}",
            ]
        total += len(boards)

        if kind not in starts:
            new_sections += ["", f"{kind}:"] + block
            continue

        idx = next(i for i, (s, _) in enumerate(order) if s == kind)
        end = order[idx + 1][1] if idx + 1 < len(order) else len(lines)
        while end > starts[kind] and lines[end - 1].strip() == "":
            end -= 1
        inserts[end] = block

    out: list[str] = []
    for i, line in enumerate(lines):
        if i in inserts:
            out += inserts[i]
        out.append(line)
    out += new_sections

    TARGET_YAML.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return total


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4000, help="companies to slugify")
    ap.add_argument("--min-infra", type=int, default=0,
                    help="require this many infra titles on the board right now")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--apply", action="store_true", help="write target_companies.yaml")
    ap.add_argument("--json-out", type=str, default="")
    args = ap.parse_args()

    known = _existing_tokens()
    all_known = set().union(*known.values())

    candidates: list[str] = []
    seen: set[str] = set()
    for name in _company_names(args.limit):
        for slug in _slugs(name):
            if slug.lower() in seen or slug.lower() in all_known:
                continue
            seen.add(slug.lower())
            candidates.append(slug)

    print(f"  {len(candidates):,} candidate tokens x {len(ENDPOINTS)} ATS "
          f"= {len(candidates) * len(ENDPOINTS):,} probes")

    sem = asyncio.Semaphore(args.concurrency)
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    ) as session:
        results = await asyncio.gather(
            *[_probe(session, sem, kind, tok)
              for tok in candidates for kind in ENDPOINTS]
        )

    hits = [r for r in results if r and r["infra"] >= args.min_infra]

    # One board per company per ATS: keep the token with the most postings.
    # Keyed on the resolved company name AND the lowercased token, so neither a
    # renamed board nor a casing variant slips through as a second entry.
    best: dict[tuple[str, str], dict] = {}
    for h in hits:
        for key in ((h["kind"], h["name"].lower()), (h["kind"], h["token"].lower())):
            if key not in best or h["total"] > best[key]["total"]:
                best[key] = h

    found: dict[str, list[dict]] = {k: [] for k in ENDPOINTS}
    emitted: set[tuple[str, str]] = set()
    for h in sorted(best.values(), key=lambda r: -r["infra"]):
        slot = (h["kind"], h["token"].lower())
        if h["token"].lower() in known[h["kind"]] or slot in emitted:
            continue
        emitted.add(slot)
        found[h["kind"]].append(h)

    print()
    for kind, boards in found.items():
        with_infra = sum(1 for b in boards if b["infra"] > 0)
        print(f"  {kind:16s} {len(boards):5,d} new boards "
              f"({with_infra:,} with infra roles today)")
    print(f"\n  TOTAL NEW: {sum(len(v) for v in found.values()):,}")

    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(found, indent=1))

    if args.apply:
        n = _append(found)
        print(f"\n  Wrote {n:,} boards to {TARGET_YAML.name}")
    else:
        print("\n  Dry run — re-run with --apply to write target_companies.yaml")


if __name__ == "__main__":
    asyncio.run(main())
