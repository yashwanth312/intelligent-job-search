"""Passive Workday tenant discovery from LinkedIn/Indeed job_url_direct fields."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Matches: https://{tenant}.{wd_server}.myworkdayjobs.com[/{locale}]/{site}/...
_WORKDAY_RE = re.compile(
    r"^https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com"
    r"(?:/[a-z]{2}-[A-Z]{2})?/([^/?#]+)",
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


def save_new_companies(
    discoveries: list[dict],
    yaml_path: str = "target_companies.yaml",
) -> int:
    """Append entries not already present (by tenant) to the workday: section
    of target_companies.yaml. Returns the count of newly added companies.
    Uses ruamel.yaml to preserve existing comments and formatting.
    """
    if not discoveries:
        return 0
    try:
        from ruamel.yaml import YAML

        ryaml = YAML()
        ryaml.preserve_quotes = True

        with open(yaml_path) as f:
            data = ryaml.load(f) or {}

        if "workday" not in data:
            data["workday"] = []

        existing_tenants: set[str] = {c["tenant"] for c in data["workday"]}
        added = 0
        seen_in_batch: set[str] = set()
        for d in discoveries:
            tenant = d["tenant"]
            if tenant not in existing_tenants and tenant not in seen_in_batch:
                data["workday"].append(d)
                seen_in_batch.add(tenant)
                added += 1

        if added > 0:
            with open(yaml_path, "w") as f:
                ryaml.dump(data, f)

        return added
    except Exception as e:
        logger.error(f"Workday discovery: failed to update {yaml_path}: {e}")
        return 0
