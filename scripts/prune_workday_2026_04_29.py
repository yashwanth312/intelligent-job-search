"""One-shot Workday tenant prune (run on 2026-04-29).

Splits target_companies.yaml's `workday:` list into:
  - KEEP: ~30 verified tech-native H-1B sponsors (stay in target_companies.yaml)
  - REJECT: everyone else (moved to workday_rejected.yaml with reason codes)

Re-running is idempotent: any tenant not in KEEP_TENANTS gets re-rejected.
After running, target_companies.yaml's workday section is the curated keep list,
and workday_rejected.yaml is the consolidated reject list with metadata.

The companion change to sources/workday_discovery.py reads workday_rejected.yaml
to skip auto-rediscovering rejected tenants.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_YAML = REPO_ROOT / "target_companies.yaml"
REJECTED_YAML = REPO_ROOT / "workday_rejected.yaml"
TODAY = dt.date.today().isoformat()

# ── KEEP list ──────────────────────────────────────────────────────────────
# Tech-native companies known to sponsor H-1B for cloud/devops/security/data
# roles. Curated by hand on 2026-04-29 from the 261-tenant pre-prune list.
KEEP_TENANTS: set[str] = {
    # Security
    "crowdstrike", "trendmicro", "forcepoint", "darktrace",
    # Cloud / SaaS / Comms
    "salesforce", "zoom", "workday", "redhat", "cloudera", "ringcentral",
    "servicetitan", "pluralsight", "autodesk", "aspentech",
    # AI / HW / Semis
    "nvidia", "intel", "marvell", "nxp", "analogdevices", "cadence",
    "kla", "sec", "formfactor", "viavisolutions", "connect",
    # Industrial software / Sci instruments / Robotics
    "agilent", "symbotic", "sonos",
    # Fintech / Data
    "visa", "thomsonreuters", "broadridge", "morningstar", "fico", "nasdaq",
    # Adtech
    "ibotta",
}

# ── Reject reason buckets ──────────────────────────────────────────────────
# Tenants not listed here default to "industry_mismatch".
DEAD_BOARDS: set[str] = {
    "broadcom",         # site:es returns 404 (per pipeline observations 2026-04-27)
    "osv-rubicon",      # Magnite — board requires auth (422)
    "smithnephew",      # JSON parse error (empty response body)
}
DEFENSE_CLEARANCE: set[str] = {
    "blueorigin", "draper", "aero", "sierraspace", "snc", "nwis",
    "starfish", "maxar", "flir", "radiancetech", "evergreenix",
}
LOW_H1B_SPONSORSHIP: set[str] = {
    # Banks/insurance/asset mgmt — sponsor for finance, rarely for cloud/devops
    "bmo", "bbva", "mufgub", "keybank", "td", "cibc", "tiaa",
    "fifththird", "ntrs", "manulife", "wellington", "statestreet",
    "troweprice", "godirect", "axos", "texascapitalbank", "raymondjames",
    "finra", "datasite", "corebridgefinancial", "jackson", "q2ebanking",
    "lendingclub", "worldpay", "db", "insperity", "sbcos", "earlywarning",
    "newrez", "highmarkhealth", "theocc",
    # Law firms — don't sponsor tech
    "hklaw", "cooley", "stblaw", "goodwinprocter", "cambridgeassociates",
    # IT distributors / resellers / consulting — local hire bias
    "shi", "ingrammicro", "btisolutions", "cliftonlarsonallen",
    "appliedis", "redriver",
}


def reason_for(tenant: str) -> str:
    if tenant in DEAD_BOARDS:
        return "dead_board"
    if tenant in DEFENSE_CLEARANCE:
        return "defense_clearance"
    if tenant in LOW_H1B_SPONSORSHIP:
        return "low_h1b_sponsorship"
    return "industry_mismatch"


def main() -> None:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # avoid wrapping

    with open(TARGET_YAML) as f:
        data = yaml.load(f)

    workday_all: list[dict] = list(data.get("workday") or [])
    keep: list[dict] = []
    reject: list[dict] = []

    seen_keep: set[str] = set()
    for entry in workday_all:
        tenant = entry.get("tenant")
        if not tenant:
            continue
        if tenant in KEEP_TENANTS:
            if tenant in seen_keep:
                continue  # de-dupe
            seen_keep.add(tenant)
            keep.append(entry)
        else:
            reject.append({
                "tenant": tenant,
                "name": entry.get("name", tenant),
                "wd_server": entry.get("wd_server"),
                "site": entry.get("site"),
                "reason": reason_for(tenant),
                "rejected_on": TODAY,
            })

    # ── Write back the pruned target_companies.yaml ──
    data["workday"] = keep
    with open(TARGET_YAML, "w") as f:
        yaml.dump(data, f)

    # ── Merge with existing workday_rejected.yaml (preserve prior rejects) ──
    existing_rejects: list[dict] = []
    if REJECTED_YAML.exists():
        with open(REJECTED_YAML) as f:
            prior = yaml.load(f) or {}
        existing_rejects = list(prior.get("rejected") or [])

    by_tenant: dict[str, dict] = {r["tenant"]: r for r in existing_rejects}
    for r in reject:
        by_tenant[r["tenant"]] = r  # newer entry wins

    merged_rejects = sorted(by_tenant.values(), key=lambda r: r["tenant"])

    out = {
        "# Workday tenants rejected from active scraping. Auto-discovery skips these.": None,
        "# Reason codes: industry_mismatch | low_h1b_sponsorship | defense_clearance | dead_board": None,
        "rejected": merged_rejects,
    }
    # ruamel doesn't render keys-without-values cleanly — write the header
    # comment block manually then dump just the data.
    header = (
        "# Workday tenants rejected from active scraping on or before "
        f"{TODAY}.\n"
        "# Auto-discovery (sources/workday_discovery.py) skips any tenant in this file.\n"
        "# Reason codes:\n"
        "#   industry_mismatch    — wrong industry (healthcare, govt, edu, industrial, retail, etc.)\n"
        "#   low_h1b_sponsorship  — sponsors rarely / not for cloud-devops roles\n"
        "#   defense_clearance    — most roles require US-citizen clearance F1 cannot hold\n"
        "#   dead_board           — Workday board returns 404 / 422 / parse errors\n"
        "#\n"
        "# To restore a tenant: remove its entry here and add it to the\n"
        "# workday section of target_companies.yaml.\n"
    )
    with open(REJECTED_YAML, "w") as f:
        f.write(header)
        yaml.dump({"rejected": merged_rejects}, f)

    print(f"Pruned workday tenants:")
    print(f"  KEEP: {len(keep)}  (out of {len(workday_all)} total in target_companies.yaml)")
    print(f"  REJECT (this run): {len(reject)}")
    print(f"  REJECT (cumulative in workday_rejected.yaml): {len(merged_rejects)}")
    keep_tenants_in_yaml = {e['tenant'] for e in keep}
    missing = KEEP_TENANTS - keep_tenants_in_yaml
    if missing:
        print(f"  WARNING — KEEP_TENANTS not found in source YAML: {sorted(missing)}")


if __name__ == "__main__":
    main()
