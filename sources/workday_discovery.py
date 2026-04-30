"""Passive Workday tenant discovery from LinkedIn/Indeed job_url_direct fields.

Discovered tenants are written to `workday_candidates.yaml` (a staging file),
NOT directly to `target_companies.yaml`. A separate promotion script
(scripts/promote_workday_candidates.py) validates each candidate against
h1bdata.info + a live Workday API ping, then promotes survivors into
`target_companies.yaml` or rejects them into `workday_rejected.yaml`.

This gating keeps the active scrape list bounded — without it, every LinkedIn
result with a Workday redirect would balloon the active list (the original
behavior took us from 114 → 261 tenants in 2 days).
"""
from __future__ import annotations

import datetime as _dt
import logging
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_DEFAULT_TARGET_YAML = _REPO_ROOT / "target_companies.yaml"
_DEFAULT_CANDIDATES_YAML = _REPO_ROOT / "workday_candidates.yaml"
_DEFAULT_REJECTED_YAML = _REPO_ROOT / "workday_rejected.yaml"

logger = logging.getLogger(__name__)

# Matches: https://{tenant}.{wd_server}.myworkdayjobs.com[/{locale}]/{site}/...
_WORKDAY_RE = re.compile(
    r"^https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com"
    r"(?:/(?i:[a-z]{2}-[a-z]{2}))?/([^/?#]+)",
)


def extract_workday_tenant(url: str | None, company_name: str) -> dict | None:
    """Parse a myworkdayjobs.com URL and return {tenant, wd_server, site, name}.

    Returns None if the URL is not a Workday URL or cannot be parsed.
    """
    if not url or "myworkdayjobs.com" not in url.lower():
        return None
    m = _WORKDAY_RE.match(url)
    if not m:
        return None
    return {
        "tenant": m.group(1).lower(),
        "wd_server": m.group(2).lower(),
        "site": m.group(3),
        "name": company_name,
    }


def _load_rejected_tenants(
    rejected_yaml_path: str | pathlib.Path = _DEFAULT_REJECTED_YAML,
) -> set[str]:
    """Read workday_rejected.yaml and return the set of rejected tenant slugs."""
    path = pathlib.Path(rejected_yaml_path)
    if not path.exists():
        return set()
    try:
        from ruamel.yaml import YAML

        ryaml = YAML()
        with open(path) as f:
            data = ryaml.load(f) or {}
        return {r["tenant"] for r in (data.get("rejected") or []) if "tenant" in r}
    except Exception as e:
        logger.warning(f"Workday discovery: failed to read {path}: {e}")
        return set()


def _load_active_tenants(
    target_yaml_path: str | pathlib.Path = _DEFAULT_TARGET_YAML,
) -> set[str]:
    """Read target_companies.yaml and return the set of currently-scraped tenants."""
    path = pathlib.Path(target_yaml_path)
    if not path.exists():
        return set()
    try:
        from ruamel.yaml import YAML

        ryaml = YAML()
        with open(path) as f:
            data = ryaml.load(f) or {}
        return {c["tenant"] for c in (data.get("workday") or []) if "tenant" in c}
    except Exception as e:
        logger.warning(f"Workday discovery: failed to read {path}: {e}")
        return set()


def save_candidates(
    discoveries: list[dict],
    candidates_yaml_path: str | pathlib.Path = _DEFAULT_CANDIDATES_YAML,
    target_yaml_path: str | pathlib.Path = _DEFAULT_TARGET_YAML,
    rejected_yaml_path: str | pathlib.Path = _DEFAULT_REJECTED_YAML,
) -> tuple[int, int]:
    """Save discovered Workday tenants to the candidates staging file.

    Returns (newly_queued, repeat_sightings_updated). Tenants already active
    in target_companies.yaml or already in workday_rejected.yaml are skipped.
    For repeat candidates, n_seen and last_seen are updated so promotion
    can prefer tenants we've seen across multiple runs.
    """
    if not discoveries:
        return 0, 0

    try:
        from ruamel.yaml import YAML

        ryaml = YAML()
        ryaml.preserve_quotes = True

        active_tenants = _load_active_tenants(target_yaml_path)
        rejected_tenants = _load_rejected_tenants(rejected_yaml_path)

        # Load existing candidates (or start fresh)
        candidates_path = pathlib.Path(candidates_yaml_path)
        if candidates_path.exists():
            with open(candidates_path) as f:
                cdata = ryaml.load(f) or {}
        else:
            cdata = {}
        if "candidates" not in cdata or cdata["candidates"] is None:
            cdata["candidates"] = []

        existing_by_tenant: dict[str, dict] = {
            c["tenant"]: c for c in cdata["candidates"] if "tenant" in c
        }

        today = _dt.date.today().isoformat()
        newly_queued = 0
        repeats = 0
        skipped_active = 0
        skipped_rejected = 0
        seen_in_batch: set[str] = set()

        for d in discoveries:
            if not all(k in d for k in ("tenant", "wd_server", "site", "name")):
                logger.warning(f"Workday discovery: skipping malformed entry: {d}")
                continue
            tenant = d["tenant"]

            if tenant in active_tenants:
                skipped_active += 1
                continue
            if tenant in rejected_tenants:
                skipped_rejected += 1
                continue
            if tenant in seen_in_batch:
                continue
            seen_in_batch.add(tenant)

            if tenant in existing_by_tenant:
                # Repeat sighting — bump counters
                existing = existing_by_tenant[tenant]
                existing["n_seen"] = int(existing.get("n_seen", 1)) + 1
                existing["last_seen"] = today
                repeats += 1
            else:
                cdata["candidates"].append({
                    "tenant": tenant,
                    "name": d["name"],
                    "wd_server": d["wd_server"],
                    "site": d["site"],
                    "first_seen": today,
                    "last_seen": today,
                    "n_seen": 1,
                    "promotion_attempts": 0,
                    "last_attempt": None,
                })
                newly_queued += 1

        if newly_queued > 0 or repeats > 0:
            candidates_path.parent.mkdir(parents=True, exist_ok=True)
            with open(candidates_path, "w") as f:
                ryaml.dump(cdata, f)

        if skipped_active or skipped_rejected:
            logger.info(
                f"Workday discovery: skipped {skipped_active} active + "
                f"{skipped_rejected} rejected tenants"
            )
        return newly_queued, repeats
    except Exception as e:
        logger.error(
            f"Workday discovery: failed to update candidates file "
            f"{candidates_yaml_path}: {e}"
        )
        return 0, 0


