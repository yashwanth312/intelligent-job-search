# Workday Adapter — Design Spec
**Date:** 2026-04-27
**Status:** Approved

---

## Problem

The pipeline's direct-API sources (Greenhouse, Lever, Ashby) cover ~106 companies. Many of the
largest H-1B-sponsoring tech companies — Microsoft, Salesforce, ServiceNow, CrowdStrike, Palo
Alto Networks, Okta, Cisco, Adobe, Zoom, Splunk — use Workday as their ATS and are currently
only reachable via LinkedIn/Indeed, where the 50-result cap and 24h freshness window leave gaps.

Adding a `WorkdayAdapter` gives the pipeline direct access to these companies' full job boards,
the same way `GreenhouseAdapter` does for Greenhouse-hosted companies.

---

## Goals

1. Scrape job listings from Workday-hosted career boards for a curated list of H-1B sponsors.
2. Search each company with every `TARGET_TITLE` so niche roles are never buried in ranked
   results.
3. Auto-discover new Workday companies passively from LinkedIn/Indeed results — no manual URL
   lookup required to grow the list.
4. Fit the existing `SourceAdapter` protocol so no changes are needed downstream (screening,
   Sheets, DB, backfill all work unchanged).

---

## Workday API

Workday exposes a semi-public JSON API on every company's career subdomain.

**Search endpoint:**
```
POST https://{tenant}.{wd_server}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

Body: {"searchText": "Cloud Engineer", "limit": 20, "offset": 0, "appliedFacets": {}}
```

**Response shape:**
```json
{
  "total": 45,
  "jobPostings": [
    {
      "title": "Cloud Engineer",
      "externalPath": "job/Redmond-WA/Cloud-Engineer_JR12345",
      "locationsText": "Redmond, Washington",
      "postedOn": "2026-04-25",
      "timeType": "Full time"
    }
  ]
}
```

**Key properties:**
- `wd_server` varies per company (wd1, wd3, wd5, wd12) — must be read from the company's
  actual careers URL, never guessed.
- No auth required for public job boards.
- `postedOn` is a YYYY-MM-DD date string.
- Full job descriptions are not returned by the search endpoint — the public job page URL is
  constructed from `externalPath` and handed off to the existing backfill system.
- Rate limiting: 429 responses occur under rapid fire; 1.5s inter-request delay within a tenant
  is sufficient. Exponential backoff (30s → 60s → 120s, max 3 retries) handles transient 429s.

---

## Architecture

### New files

#### `sources/workday.py` — WorkdayAdapter

Implements `SourceAdapter`. Receives `titles` (TARGET_TITLES) and `locations` (unused —
Workday searches are company-scoped, not location-scoped).

```
scrape(titles, locations):
  Run _scrape_company(company, titles) for all companies in parallel (asyncio.gather)

_scrape_company(company, titles):
  For each title in titles (sequential, 1.5s delay between requests):
    POST /wday/cxs/{tenant}/{site}/jobs  {searchText: title, limit: 20, offset: 0}
    total = response["total"]
    Collect jobPostings from page 1
    While offset + 20 < total:
      offset += 20
      POST again with new offset
      Append jobPostings
  Convert each posting to RawJob:
    title         = posting["title"]
    company       = company["name"]
    location      = posting["locationsText"]
    description   = None  (backfill handles this)
    url           = https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}/{externalPath}
    source        = "workday-{tenant}"
    posted_at     = parse_iso(posting["postedOn"])
  On 429: sleep 30s * (2 ** attempt), retry up to 3 times
  On non-200 other than 429: log warning, return []
```

Parallelism model: companies run concurrently; titles within a company run sequentially. This
keeps per-tenant request rate well within safe limits while maximising throughput across
companies.

#### `sources/workday_discovery.py` — passive discovery

Two public functions:

```python
def extract_workday_tenant(url: str, company_name: str) -> dict | None:
    """
    Parse a myworkdayjobs.com URL and return:
      {tenant, wd_server, site, name}
    Returns None if url is not a Workday URL or cannot be parsed.
    """

def save_new_companies(
    discoveries: list[dict],
    yaml_path: str = "target_companies.yaml",
) -> int:
    """
    Append entries not already present (matched by tenant) to the workday:
    section of target_companies.yaml. Returns count of newly added companies.
    Preserves all existing yaml content and comments via ruamel.yaml.
    """
```

URL pattern matched:
```
https://{tenant}.{wd_server}.myworkdayjobs.com[/{locale}]/{site}/...
```
Regex:
```
^https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com(?:/[a-z]{2}-[A-Z]{2})?/([^/?#]+)
```

### Modified files

#### `sources/linkedin_indeed.py`

`_scrape_one` already holds the raw JobSpy DataFrame before converting to `RawJob` objects.
After building the jobs list, scan the `job_url_direct` column for `myworkdayjobs.com` matches.
Store discovered tenants in `self._discovered: dict[str, dict]` (keyed by tenant to dedup).
Expose via read-only property `discovered_workday_companies -> list[dict]`.

Thread safety: `_scrape_one` runs in a `ThreadPoolExecutor`. Use a `threading.Lock` when
writing to `self._discovered`.

#### `main.py`

After Phase 3 (scraping), read `linkedin_indeed_adapter.discovered_workday_companies`, call
`save_new_companies(discoveries)`, and log the count and names of any newly added companies.

`build_adapters()` gains a `workday` branch:
```python
wd = companies.get("workday", [])
if wd:
    adapters.append(WorkdayAdapter(companies=wd))
    display.append(("workday", f"Workday ({len(wd)} co)"))
```

`build_adapters()` return type changes from `tuple[list, list[tuple]]` to
`tuple[list, list[tuple], LinkedInIndeedAdapter]` — the adapter instance is the third
element so `run_pipeline` can read `discovered_workday_companies` from it after Phase 3
without searching through the adapter list.

#### `target_companies.yaml`

New `workday:` section. Each entry:
```yaml
workday:
  - tenant: microsoft
    wd_server: wd5
    site: External_Careers
    name: Microsoft
```

Initial seed list (all verified against live API during implementation):
Microsoft, Salesforce, ServiceNow, CrowdStrike, Palo Alto Networks, Okta, Cisco, Adobe,
Zoom, Splunk, Workday, Box.

### New script

#### `scripts/verify_workday_tokens.py`

```
Usage: python scripts/verify_workday_tokens.py [careers-page-url ...]

For each URL argument:
  - Parse tenant/wd_server/site
  - POST a test search (searchText="engineer", limit=1)
  - Print: OK / FAIL and job count
  - Print ready-to-paste YAML block on success

With no arguments: validate all existing workday: entries in target_companies.yaml.
```

---

## Data Flow

```
Phase 3: Scrape (parallel)
  ├── GreenhouseAdapter     (unchanged)
  ├── LeverAdapter          (unchanged)
  ├── AshbyAdapter          (unchanged)
  ├── LinkedInIndeedAdapter (+ populates discovered_workday_companies)
  ├── HackerNewsAdapter     (unchanged)
  ├── RemoteOKAdapter       (unchanged)
  └── WorkdayAdapter        (NEW — reads workday: from target_companies.yaml)

After Phase 3 (NEW):
  linkedin_indeed_adapter.discovered_workday_companies
    → workday_discovery.save_new_companies()
    → target_companies.yaml updated for next run

Phases 4–9: unchanged
  Workday jobs flow through freshness filter, backfill, Stage 1, Stage 2,
  Sheets write, and SQLite exactly like Greenhouse jobs.
```

---

## Company Growth Model

**Initial seed:** 12 manually verified companies added at implementation time.

**Ongoing growth (automatic):**
Every run, `LinkedInIndeedAdapter` scans `job_url_direct` values. When a new company's
application URL points to Workday, it is extracted and appended to `target_companies.yaml`.
No user action required. Growth rate depends on how many new companies surface in
LinkedIn/Indeed results over time.

**Manual additions:**
Run `scripts/verify_workday_tokens.py <careers-url>` to validate and get the YAML block, then
paste it into `target_companies.yaml`. Or add manually following the four-field schema.

---

## Error Handling

| Condition | Behaviour |
|---|---|
| 429 from Workday | Exponential backoff: 30s, 60s, 120s. After 3 failures, log error and skip that (company, title) pair. |
| Non-200 (404, 500) | Log warning with company name and title, return empty list for that pair. Continue with remaining titles. |
| Empty `jobPostings` | Normal — company has no matches for that title. No log noise. |
| Malformed JSON | Log warning, return empty list for that pair. |
| Discovery: unparseable URL | Silently skip — not all `job_url_direct` values are Workday. |
| Discovery: yaml write fails | Log error, do not crash the pipeline — discovery is best-effort. |

---

## Testing

### `tests/test_workday.py`
- `test_scrape_converts_response_to_raw_jobs` — mock aiohttp POST, verify RawJob fields
- `test_pagination_fetches_all_pages` — mock response with total=45, verify 3 POST calls
- `test_429_triggers_backoff_and_retries` — mock 429 then 200, verify retry logic
- `test_non_200_returns_empty_list` — mock 404, verify no exception raised
- `test_job_url_construction` — verify URL built correctly from tenant/wd_server/site/externalPath

### `tests/test_workday_discovery.py`
- `test_extract_valid_workday_url` — parse standard URL, verify all three fields
- `test_extract_url_with_locale` — parse URL containing `en-US` locale segment
- `test_extract_non_workday_url_returns_none` — LinkedIn URL, verify None
- `test_save_new_companies_adds_to_yaml` — write to temp yaml, verify entry added
- `test_save_new_companies_skips_existing_tenant` — duplicate tenant, verify not added twice

---

## Dependencies

No new packages required. Uses `aiohttp` (already in requirements.txt) for API calls and
`ruamel.yaml` for comment-preserving yaml writes.

Check `ruamel.yaml` is in `requirements.txt`; add it if missing (`ruamel.yaml>=0.17`).

---

## Out of Scope

- Fetching job descriptions inline from Workday's detail endpoint — the existing backfill
  system handles this via the public job page URL.
- Location filtering within Workday searches — Workday's `appliedFacets` supports location
  filters but adds per-company complexity. Stage 1 and Stage 2 already handle irrelevant
  locations downstream.
- Workday authentication / internal job boards — only public boards are targeted.
