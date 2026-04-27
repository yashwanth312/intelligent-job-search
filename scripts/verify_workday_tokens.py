#!/usr/bin/env python
"""Verify Workday career board configs and print ready-to-paste YAML.

Usage:
  # Validate all workday: entries in target_companies.yaml
  python scripts/verify_workday_tokens.py

  # Parse and validate one or more careers-page URLs
  python scripts/verify_workday_tokens.py https://crowdstrike.wd5.myworkdayjobs.com/CrowdStrikeCareers
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiohttp
import yaml

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from sources.workday_discovery import extract_workday_tenant

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}


async def check_company(session: aiohttp.ClientSession, entry: dict) -> None:
    tenant = entry["tenant"]
    wd_server = entry["wd_server"]
    site = entry["site"]
    name = entry.get("name", tenant)
    url = (
        f"https://{tenant}.{wd_server}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/jobs"
    )
    body = {"searchText": "engineer", "limit": 1, "offset": 0, "appliedFacets": {}}

    try:
        async with session.post(
            url, json=body, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                total = data.get("total", 0)
                print(f"  OK  {name:30s}  {total:>5d} jobs  (tenant={tenant}, {wd_server}, site={site})")
                print(f"       YAML block:")
                print(f"         - tenant: {tenant}")
                print(f"           wd_server: {wd_server}")
                print(f"           site: {site}")
                print(f"           name: {name}")
            else:
                print(f" FAIL {name:30s}  HTTP {resp.status}  ({url})")
    except Exception as e:
        print(f" FAIL {name:30s}  {e}")


async def main(args: list[str]) -> None:
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        if args:
            # Validate URLs passed as arguments
            for raw_url in args:
                company_name = raw_url.split(".")[0].replace("https://", "").capitalize()
                entry = extract_workday_tenant(raw_url, company_name)
                if not entry:
                    print(f" SKIP {raw_url}  — could not parse as Workday URL")
                    continue
                await check_company(session, entry)
        else:
            # Validate all existing workday: entries in target_companies.yaml
            data = yaml.safe_load(Path("target_companies.yaml").read_text()) or {}
            companies = data.get("workday", [])
            if not companies:
                print("No workday: entries found in target_companies.yaml")
                return
            print(f"Checking {len(companies)} Workday entries...\n")
            tasks = [check_company(session, c) for c in companies]
            await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
