"""Replace raw board tokens used as company names with real company names.

`discover_ats_boards.py` fell back to the token when an API gave no company
name, so auto-discovered entries landed as `name: northpointtechnology`. That
name is not just cosmetic — it is what the pipeline writes into the Daily and
Materials sheets, what the H-1B sponsor lookup queries, and what the generated
cover letter addresses. A lowercased slug matches no LCA filer and reads badly
in a letter.

Greenhouse exposes the real name at /v1/boards/{token} ("northpointtechnology"
-> "North Point Technology"). Ashby and Lever publish no company name anywhere
in their public payloads, so those fall back to a humanized token, which is
still far better than the raw slug.

Only entries whose name still equals their token are touched; hand-curated
names are left alone.

Run:  python scripts/repair_board_names.py            (dry run)
      python scripts/repair_board_names.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import re
import sys

import aiohttp
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

TARGET_YAML = _REPO_ROOT / "target_companies.yaml"
GREENHOUSE_BOARD = "https://boards-api.greenhouse.io/v1/boards/{}"

# Tokens are usually the company name with separators stripped. Split on
# camelCase and digit boundaries so "AristaNetworks" -> "Arista Networks".
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _humanize(token: str) -> str:
    parts = _CAMEL_RE.split(token)
    words = [w for p in parts for w in re.split(r"[-_]", p) if w]
    if not words:
        return token
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)


async def _greenhouse_name(session, sem, token: str) -> str | None:
    async with sem:
        try:
            async with session.get(
                GREENHOUSE_BOARD.format(token),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except Exception:
            return None
    name = (data or {}).get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()

    data = yaml.safe_load(TARGET_YAML.read_text(encoding="utf-8")) or {}

    # Only rows still carrying the token as their name.
    todo: list[tuple[str, str]] = []
    for kind in ("greenhouse", "lever", "ashby"):
        for entry in data.get(kind, []):
            token, name = str(entry.get("token", "")), str(entry.get("name", ""))
            if token and token == name:
                todo.append((kind, token))

    print(f"  {len(todo):,} board(s) still named after their token")
    if not todo:
        return

    gh = [t for k, t in todo if k == "greenhouse"]
    sem = asyncio.Semaphore(args.concurrency)
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    ) as session:
        gh_names = await asyncio.gather(
            *[_greenhouse_name(session, sem, t) for t in gh]
        )

    resolved: dict[str, str] = {}
    n_api = 0
    for token, name in zip(gh, gh_names):
        if name:
            resolved[token] = name
            n_api += 1
        else:
            resolved[token] = _humanize(token)
    for kind, token in todo:
        resolved.setdefault(token, _humanize(token))

    changed = {t: n for t, n in resolved.items() if n != t}
    print(f"  resolved {n_api:,} real names from the Greenhouse board API")
    print(f"  humanized the remaining {len(resolved) - n_api:,}")
    print(f"  {len(changed):,} name(s) will change\n")
    for token, name in list(changed.items())[:20]:
        print(f"     {token:34s} -> {name}")

    if not args.apply:
        print("\n  Dry run — re-run with --apply to write target_companies.yaml")
        return

    # Rewrite line-wise so comments and layout survive.
    lines = TARGET_YAML.read_text(encoding="utf-8").split("\n")
    out: list[str] = []
    current_token: str | None = None
    n_written = 0
    for line in lines:
        m = re.match(r'^- token:\s*"?([^"\s]+)"?\s*$', line)
        if m:
            current_token = m.group(1)
            out.append(line)
            continue
        nm = re.match(r'^(\s+name:\s*)"?(.*?)"?\s*$', line)
        if nm and current_token and nm.group(2) == current_token:
            new = changed.get(current_token)
            if new:
                out.append(f'{nm.group(1)}"{new}"')
                n_written += 1
                continue
        out.append(line)

    TARGET_YAML.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"\n  Rewrote {n_written:,} name(s) in {TARGET_YAML.name}")


if __name__ == "__main__":
    asyncio.run(main())
