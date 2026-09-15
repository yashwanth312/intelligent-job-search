"""
============================================================
  INTELLIGENT JOB SEARCH CONFIG
  Edit this file to change search preferences and thresholds.
  Secrets live in .env — not here.
============================================================
"""

import os
import shutil
import sys
from dotenv import load_dotenv

load_dotenv()

# ── PERSONAL INFO ──────────────────────────────────────────
# Set these in .env — see .env.example
YOUR_NAME = os.getenv("YOUR_NAME", "")
YOUR_EMAIL = os.getenv("YOUR_EMAIL", "")
YOUR_PHONE = os.getenv("YOUR_PHONE", "")
YOUR_LOCATION_FALLBACK = os.getenv("YOUR_LOCATION_FALLBACK", "")
YOUR_LINKEDIN = os.getenv("YOUR_LINKEDIN", "")
YOUR_GITHUB = os.getenv("YOUR_GITHUB", "")

# ── GOOGLE INTEGRATIONS ───────────────────────────────────
GOOGLE_SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Intelligent Job Search")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# ── DATABASE ──────────────────────────────────────────────
DB_FILE = "jobs.db"

# ── TARGET JOB TITLES ─────────────────────────────────────
# Used as both LinkedIn/Indeed search queries AND Stage 1 title matching.
# Each title gets its own dedicated search so niche titles are never buried.
#
# This list deliberately excludes "Junior X" / "Associate X" variants:
# LinkedIn keyword search returns the same posting set regardless of those
# qualifiers (postings rarely put "Junior" in the title), so they were pure
# duplicate queries adding scrape time with no new postings. Seniority is
# already filtered post-scrape by EXCLUDE_TITLE_KEYWORDS below.
#
# Synonyms collapsed: SRE → "Site Reliability Engineer" (matches both),
# "Reliability Engineer" / "Observability Engineer" / "Kubernetes Engineer"
# are subsumed by SRE/Platform. "Cloud DevOps" / "AI DevOps" / "ML Platform"
# are subsumed by their broader peers.
# Narrowed to infrastructure on 2026-09-13 from five months of outcome data
# (1,003 applications, 7 callbacks — see the "Seven Callbacks" audit). Observed
# callback rate by the DOMAIN OF THE JOB APPLIED TO:
#
#     Cloud Engineer            4.35%  (2/46)
#     SRE / Reliability         2.20%  (2/91)
#     Systems / Infra / Platform 1.41% (2/142)
#     Security Engineer         0.87%  (1/115)   <- lone hit was infra-flavoured
#     AI/ML                     0.00%  (0/238)
#     Software Engineer         0.00%  (0/128)
#     DevOps (by job title)     0.00%  (0/85)
#     Security Analyst / GRC    0.00%  (0/73)
#
# Infra cluster 2.15% vs everything else 0.14% — a 15x difference on n=1,003.
# Security and standalone-AI search terms are dropped accordingly; MLOps stays
# as the one AI-adjacent entry because it is infrastructure work and is the one
# AI niche reported as under-supplied rather than oversubscribed.
#
# "DevOps Engineer" is retained despite 0/85 on the job-title cut: it is a SEARCH
# term, not an outcome bucket, and it is the widest net that surfaces cloud/SRE/
# platform reqs which do convert. Re-evaluate it once the next cohort lands.
TARGET_TITLES = [
    # Cloud / Infrastructure — best observed conversion
    "Cloud Engineer",
    "Cloud Infrastructure Engineer",
    "Infrastructure Engineer",
    "Systems Engineer",
    # Amazon's callback came from this exact title, which the old list never searched.
    "Systems Development Engineer",
    # Reliability / Platform
    "Site Reliability Engineer",
    "Platform Engineer",
    "Production Engineer",
    "Observability Engineer",
    # Broad feeder into all of the above
    "DevOps Engineer",
    # AI-adjacent, but infrastructure-shaped
    "MLOps Engineer",
]

# ── LOCATIONS ─────────────────────────────────────────────
# Cast the widest net across US tech hubs. 24h freshness filter
# keeps volume sane even with 18 locations. "United States" is a
# national catch-all on LinkedIn/Indeed that surfaces postings in
# secondary metros (Miami, Tampa, Houston, Phoenix, Charlotte, etc.)
# the city-specific queries miss; dedup absorbs the overlap.
LOCATIONS = [
    "Chicago, IL",
    "New York, NY",
    "Seattle, WA",
    "Austin, TX",
    "Boston, MA",
    "Denver, CO",
    "Philadelphia, PA",
    "Washington, DC",
    "San Francisco, CA",
    "San Jose, CA",
    "Los Angeles, CA",
    "Atlanta, GA",
    "Raleigh, NC",
    "Minneapolis, MN",
    "Dallas, TX",
    "Portland, OR",
    "United States",
    "Remote",
]

# ── CLAUDE CLI ────────────────────────────────────────────
def _find_claude_cli() -> str:
    """Locate the Claude CLI binary, trying platform-specific install paths."""
    found = shutil.which("claude")
    if found:
        return found

    if sys.platform == "win32":
        # npm installs global packages to %APPDATA%\npm on Windows.
        # This directory is often missing from PATH even though npm added it.
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        for candidate in [
            os.path.join(appdata, "npm", "claude.cmd"),
            os.path.join(appdata, "npm", "claude"),
            os.path.join(localappdata, "Programs", "claude", "claude.exe"),
            os.path.join(localappdata, "AnthropicClaude", "claude.exe"),
        ]:
            if os.path.isfile(candidate):
                return candidate
    else:
        for candidate in [
            os.path.expanduser("~/.local/bin/claude"),
            os.path.expanduser("~/.npm-global/bin/claude"),
            "/usr/local/bin/claude",
        ]:
            if os.path.isfile(candidate):
                return candidate

    return "claude"  # last-resort; will fail with a clear error at runtime


CLAUDE_CLI = _find_claude_cli()

# ── SCRAPER SETTINGS ──────────────────────────────────────
# RESULTS_PER_SEARCH: per-query cap for JobSpy. With HOURS_OLD=24 the
# realistic return per (site, query, location) is often much lower,
# so a larger cap costs little and widens the net.
RESULTS_PER_SEARCH = 50
HOURS_OLD = 24  # Enforced across ALL sources via sources/orchestrator.filter_fresh_jobs
SCRAPER_WORKERS = 8
STALE_JOB_DAYS = 5

# ── LOCATION EXCLUSIONS ───────────────────────────────────
# Substring match against job.location (case-insensitive). Catches non-US
# postings from Greenhouse/Lever/Ashby which scrape ALL company jobs regardless
# of location. LinkedIn/Indeed are already filtered by US city queries, but
# Greenhouse can return "Hybrid - Bangalore, India" for a US company's India office.
EXCLUDE_LOCATION_PATTERNS = [
    # South Asia
    "india", "bangalore", "bengaluru", "hyderabad", "mumbai", "chennai",
    "pune", "delhi", "kolkata", "noida", "gurugram", "gurgaon",
    "ahmedabad", "coimbatore", "kochi", "trivandrum", "nagpur", "indore",
    "thane",
    # Europe
    # NOTE: deliberately no bare "vienna"/"melbourne"/"manchester"/"rome"/
    # "athens"/"cairo"/"geneva" — each collides with a real US city
    # (Vienna VA, Melbourne FL, Manchester NH, Rome GA/NY, Athens GA/OH,
    # Cairo GA, Geneva NY/IL). The country-level token still catches the
    # normal "Country - City" Workday format; only a bare city with no
    # country prefix slips through, which is an acceptable trade-off
    # against wrongly dropping a real US posting.
    "united kingdom", " uk,", ", uk", "london", "edinburgh",
    "glasgow", "belfast", "ireland", "dublin",
    "germany", "berlin", "munich", "frankfurt", "hamburg", "stuttgart",
    "cologne", "dusseldorf", "manching", "donauwörth",
    "france", "paris", "toulouse", "lyon", "nice", "marseille",
    "netherlands", "amsterdam", "hoofddorp",
    "sweden", "stockholm", "poland", "warsaw", "gdansk", "krakow",
    "spain", "madrid", "barcelona", "getafe",
    "italy", "milan",
    "portugal", "lisbon",
    "romania", "bucharest",
    "hungary", "budapest",
    "czech", "prague",
    "slovakia",
    "austria",
    "belgium", "brussels",
    "switzerland", "zurich",
    "denmark", "copenhagen",
    "norway", "oslo",
    "finland", "helsinki",
    "greece",
    "turkey", "istanbul",
    # APAC
    "singapore", "australia", "sydney", "adelaide", "japan", "tokyo",
    "china", "beijing", "shanghai", "hong kong",
    "taiwan", "taipei",
    "philippines", "manila", "taguig",
    "vietnam", "ho chi minh",
    "malaysia", "kuala lumpur", "penang",
    "thailand", "bangkok",
    "indonesia", "jakarta",
    "south korea", "seoul",
    "new zealand", "auckland", "wellington",
    # Middle East / Africa
    "israel", "tel aviv",
    "saudi arabia", "riyadh",
    "united arab emirates", "dubai", "abu dhabi",
    "egypt",
    "south africa",
    # Canada (US companies often post CA roles separately)
    "canada", "toronto", "vancouver", "montreal", "ottawa", "waterloo",
    "burnaby", "calgary", "edmonton", "winnipeg", "quebec", "halifax",
    # Latin America
    "mexico", "brazil", "colombia", "bogota", "argentina", "buenos aires",
    "chile", "santiago", "costa rica", "guanajuato",
]

# ── TITLE EXCLUSIONS ──────────────────────────────────────
EXCLUDE_TITLE_KEYWORDS = [
    # Seniority / employment type
    # NOTE: "contract"/"contractor" deliberately NOT excluded — contract-to-hire
    # is a primary entry path into DevOps/security for early-career candidates.
    "senior", "sr.", "sr ", "lead", "staff", "principal",
    "manager", "director", "vp ", "vp,", "vice president", "head of",
    "intern", "internship",
    "part-time", "part time", "freelance", "temporary",
    # Mass-intake university funnels. These reqs draw thousands of applicants,
    # close within days, and returned 0 callbacks across the 2026-04→09 cohort.
    # NOTE: "junior", "associate" and "entry level" are deliberately NOT here —
    # they are the right level for this candidate, and their 0-for-106 record is
    # within noise at a 0.7% base rate (expected ~0.7 callbacks). Only the
    # structured campus programs are excluded.
    "new grad", "new graduate", "new college grad", "college graduate",
    "university graduate", "university recruiting", "campus hire",
    "early career", "rotational program", "returnship",
    # Non-software engineering disciplines (industrial/hardware)
    "electrical engineer", "mechanical engineer", "civil engineer",
    "controls engineer", "building automation", "hvac",
    "asic", "fpga",
    # Industrial/plant-floor work that slips through on the "automation" and
    # "systems" domain keywords — "Automation Technician", "Quality Systems
    # Engineer", "Thermal Systems Engineer" are none of them software roles.
    "marketing automation", "sales automation", "automation technician",
    "technician", "quality systems", "thermal", "mechatronics", "plc ",
    "scada", "field service", "manufacturing", "warehouse", "machinist",
    "maintenance", "calibration", "tooling",
    # Work-authorization hard stops written into the TITLE, which the
    # description-level EXCLUDE_DESC_PATTERNS never sees. Staffing firms put
    # these in titles constantly ("DevOps Engineer (USC/GC Only)"), and they
    # are absolute disqualifiers for an F-1 candidate.
    "usc/gc", "usc only", "gc only", "us citizen", "green card",
    "citizens only", "no c2c", "w2 only", "clearance",
    # Non-IC / pre-sales roles
    "solutions architect", "presales", "pre-sales",
    # IT support
    "desktop support", "direct support",
    # Non-engineering analyst roles
]

# ── TITLE DOMAIN KEYWORDS ─────────────────────────────────
# A title must contain at least one of these (word-boundary match) to survive
# Stage 1. Matching is \bword\b, so multi-word/compound forms must be listed
# EXPLICITLY: "security" does NOT match "cybersecurity" (no word boundary
# inside the compound), so "cybersecurity" is its own entry. Likewise "cyber"
# alone won't match "cybersecurity". Short tokens (ai, ml, it, soc, noc, grc,
# iam) rely on the word boundary to avoid false positives — e.g. "ai" must not
# match "maintenance". Do NOT switch this to substring matching for that reason.
#
# Narrowed to infrastructure on 2026-09-13 (see TARGET_TITLES for the outcome
# data). The standalone security and AI words are gone. That does NOT blanket-ban
# those jobs — it means they now have to carry an infrastructure word too, which
# is exactly the profile that converted: "Applied Cloud and AI Engineer"
# (Millennium, interview) still passes on "cloud"; "Software Security Engineer,
# Distributed Systems" (Salesforce, interview) still passes on "systems"; bare
# "Security Analyst" (0/73) and "AI Engineer" (part of 0/238) no longer do.
TITLE_DOMAIN_KEYWORDS = [
    # Cloud / infra / DevOps / SRE
    "cloud", "devops", "devsecops", "sre", "platform", "infrastructure",
    "reliability", "kubernetes", "observability", "systems",
    "network", "networking",
    # Infra-shaped AI only. Bare "ai" is deliberately absent: an AI title now has
    # to also name cloud/platform/infrastructure/systems to survive Stage 1.
    "mlops",

    # Cloud/IaC/CI-CD tool names — already trusted in REQUIRE_ONE_OF for
    # descriptions but missing here, so titles like "AWS Engineer" or
    # "Terraform Engineer" were being dropped before Stage 2 ever saw them.
    "aws", "gcp", "azure", "terraform", "k8s", "ci/cd",
    "docker", "jenkins", "ansible",
    # Observability / config-mgmt tool names, same rationale.
    "prometheus", "grafana", "helm", "vault",
    # Catches "Automation Engineer" / "Linux Engineer" / "Linux Administrator"
    # titles that carry no other domain word.
    "automation", "linux",
]

# ── SPONSORSHIP FILTER (master toggle — pluggable) ────────
# Enabled: target only companies likely to sponsor in the future even though
# the candidate is work-authorized (F1 OPT) through June 2028. When True:
#   • Phase 5 runs h1bdata.info sponsor check and drops no-history companies
#   • Stage 1 hard-stops JDs that explicitly say "we don't sponsor"
#   • Stage 2 treats explicit no-sponsor JD language as a SKIP disqualifier
#     and reduces confidence by 1 for unverified companies
# Flip to False to skip all sponsorship checks (saves run time).
SPONSORSHIP_FILTER_ENABLED = True

# ── DESCRIPTION HARD-STOP PATTERNS ────────────────────────
# ALWAYS enforced, independent of the sponsorship toggle. Clearance and
# US-citizenship requirements are hard disqualifiers for an F1 candidate
# regardless of whether sponsorship is needed.
#
# Years-of-experience requirements used to be enumerated here too (a
# per-number literal-substring list: "5+ years", "4-6 years", etc.) but that
# approach silently broke on two real-world phrasings:
#   1. jobspy renders LinkedIn/Indeed descriptions as Markdown, which
#      backslash-escapes every hyphen ("4\-6 years"), so none of the range
#      patterns ever matched those postings.
#   2. Bare "N years of experience" (no "+", "minimum", or "at least"
#      qualifier) wasn't covered by any pattern at all, despite being the
#      single most common phrasing in real JDs.
# YOE matching now lives in screening/stage1.py as regex (see
# MIN_YOE_HARD_STOP below) so it tolerates escaped/unicode dash variants and
# any N instead of a hardcoded per-number list.
EXCLUDE_DESC_PATTERNS = [
    # Clearance / citizenship hard stops
    "active clearance", "security clearance required",
    "clearance required", "top secret", "ts/sci",
    "secret clearance", "dod clearance", "dod secret",
    "government clearance", "federal clearance",
    "must hold a clearance", "must have clearance",
    "must be a us citizen", "us citizenship required",
    "citizenship is required", "only us citizens",
    "citizens only", "must be a citizen",
]

# ── YEARS-OF-EXPERIENCE HARD-STOP THRESHOLD ───────────────
# A hard requirement of this many years or more is a hard disqualifier —
# target level is 0-3 yrs / junior-to-mid (see prompts/screening.md).
# "Preferred"/"nice to have" YOE mentions are intentionally NOT hard-stopped
# here; only requirement-shaped phrasing is: "N+ years", "N or more years",
# "at least/minimum N years", a numeric range ("A-B years"/"A to B years"),
# or bare "N years [...] experience". See screening/stage1.py for the regex.
MIN_YOE_HARD_STOP = 4

# ── SPONSORSHIP-AVAILABILITY HARD-STOPS (toggle-gated) ────
# Applied in Stage 1 only when SPONSORSHIP_FILTER_ENABLED is True.
# Stage 2 catches subtler phrasings not covered here.
SPONSORSHIP_DESC_PATTERNS = [
    "no sponsorship", "cannot sponsor", "will not sponsor",
    "sponsorship is not available", "does not sponsor",
    "no visa sponsorship", "visa sponsorship not available",
    "without employer sponsorship", "without sponsorship",
    "sponsorship not provided", "sponsorship not available",
    "not able to sponsor", "unable to sponsor",
    "must be authorized to work without",
]

# ── MUST-HAVE KEYWORDS ────────────────────────────────────
REQUIRE_ONE_OF = [
    "aws", "gcp", "azure", "cloud", "kubernetes", "k8s", "terraform",
    "devops", "security", "iam", "sre", "platform", "infrastructure",
    "ci/cd", "docker", "jenkins", "github actions", "ansible",
    "prometheus", "grafana", "helm", "vault", "linux", "automation",
    "mlops", "ai", "machine learning", "ml pipeline", "observability",
]

# ── SALARY FLOOR ──────────────────────────────────────────
SALARY_FLOOR = 80_000

# ── SCREENING SETTINGS ────────────────────────────────────
# Not read by any code path — the actual cutoff is enforced by Claude itself
# via the confidence scale/verdict bands spelled out in prompts/screening.md
# (APPLY 3-5, MAYBE 2, SKIP 1+disqualifier). Kept here as documentation of
# that value and asserted >= 1 by tests/test_config.py; change both together.
SCREENING_CONFIDENCE_THRESHOLD = 3  # Minimum confidence for APPLY verdict
SCREENING_BATCH_SIZE = 8            # JDs per Claude CLI invocation — prompt goes via stdin not argv, so no 32KB limit concern
# Batches ran strictly sequentially until 2026-09-09: measured 10-22 batches/run
# at ~100-240s each (thinking stays on for screening — see claude_cli.run_claude's
# disable_thinking docstring), so Stage 2 alone was taking 27-63 minutes while
# scraping (~30min) and generation (~5min, thinking off) got fast. Batches are
# independent, stateless CLI calls — same concurrency pattern already proven
# safe in generate_materials.py's ThreadPoolExecutor(max_workers=5).
SCREENING_MAX_WORKERS = 5
STAGE2_MODEL = "claude-haiku-4-5-20251001"  # Switch to claude-sonnet-4-6 for higher precision
# Caps (does NOT disable) extended thinking per Stage 2 batch call, via
# MAX_THINKING_TOKENS — see claude_cli.run_claude's thinking_budget_tokens
# docstring. Thinking stays fully ON for screening (disable_thinking=0 was
# measured at a 37% verdict-flip rate, skewed lenient — unacceptable) but
# was otherwise unbounded, billing whatever the model chose to think.
# Chosen from the real per-call output_tokens distribution logged in
# claude_usage over the 400 most recent screening calls (2026-09-11):
#   p50=11,277  p60=11,907  p70=12,693  p75=13,193  p80=13,930  p90=16,077  max=21,261
# 12,000 sits just above the p50-p60 band, so the *typical* batch is
# completely unaffected — only the upper ~35-40% of calls (the ones already
# thinking longer than most) get capped, for an estimated ~9% aggregate
# token reduction. This is intentionally conservative: quality > cost here,
# so the cap trims the tail rather than compressing the median. Re-check
# usage_report.py after a few runs and lower this only if verdict quality
# holds up — raise it back toward 16-21k (or drop the cap entirely) if
# flip-rate/quality looks off.
STAGE2_THINKING_BUDGET_TOKENS = 12_000
# Measured wall time per batch (with thinking left on — see claude_cli.run_claude's
# disable_thinking docstring) is ~100-150s, so the old 150s ceiling was a coin-flip:
# on 2026-09-08, 22/32 batches (204/253 jobs) timed out on both attempts and were
# silently defaulted to MAYBE with no real screening. Give real headroom, same fix
# already applied to RESUME_GENERATION_TIMEOUT below.
STAGE2_TIMEOUT = 300                # seconds per Stage 2 screening call (batch of SCREENING_BATCH_SIZE jobs)
H1B_CACHE_TTL_DAYS = 30             # Days before re-checking a CONFIRMED sponsor
# Negatives expire far sooner than positives on purpose. A cached True is a fact
# about filing history; a cached False only means "no query form we tried matched",
# which is also what a renamed entity or a decorated job-board company string looks
# like. A wrong negative silently drops every posting from that employer, so it
# gets days to self-heal rather than a month.
H1B_NEGATIVE_CACHE_TTL_DAYS = 7

# ── RESUME VERIFICATION (interview-likelihood gate) ───────
# After a resume + cover letter are generated, a Claude "senior technical
# recruiter" pass scores interview likelihood (0-100) and lists concrete,
# actionable gaps. If the score is below RESUME_INTERVIEW_SCORE_THRESHOLD the
# materials are regenerated with that feedback — up to RESUME_MAX_REVISIONS
# extra attempts — and the highest-scoring version is kept. Each pass costs
# additional Claude CLI calls, so the revision budget is capped.
RESUME_VERIFICATION_ENABLED = False     # Disabled: each job requires 3-4 Sonnet calls (verify+regenerate+verify)
                                        # that add ~90 min for 7 resumes with no viable path to 90% for conf<4.
                                        # First-pass quality is instead maximised by richer Stage 2 angle output
                                        # and a mandatory keyword self-check baked into the generation prompt.
                                        # Local keyword-coverage (free, no Claude call) is logged as the score.
RESUME_INTERVIEW_SCORE_THRESHOLD = 90   # Unused while verification is off; kept for easy re-enable
RESUME_MAX_REVISIONS = 1                # Unused while verification is off; kept for easy re-enable

# Resume + cover letter generation is a single heavy Sonnet call: full
# profile.yaml + JD through a long, self-checking prompt. Measured solo wall time
# is ~300s, so the old 300s ceiling was a coin-flip — calls that ran a hair long
# were killed and counted as "claude_failed". Give them real headroom. Jobs run
# sequentially, so this is a per-job ceiling, not a multiplier on the run.
RESUME_GENERATION_MODEL = "claude-sonnet-4-6"
RESUME_GENERATION_TIMEOUT = 600         # seconds per generation/revision call
RESUME_VERIFIER_TIMEOUT = 300           # seconds per recruiter-sim verify call

# ── DAILY TAB COLUMNS ─────────────────────────────────────
# Risk Flags sits right after Status so visa/clearance/seniority
# concerns are visible without scrolling. Sponsorship is a dedicated
# column derived from h1b_sponsor_verified + source — replaces the old
# `no_h1b_history` risk flag.
DAILY_HEADERS = [
    "Company", "Job Title", "Location", "Confidence", "Status", "Interview Score (%)",
    "Risk Flags", "Apply Link", "Posted", "Source", "AI Reasoning", "Suggested Angle",
    "Match Signals", "Sponsorship", "Salary Range", "Notes",
]

# ── AUDIT TAB COLUMNS ─────────────────────────────────────
AUDIT_HEADERS = [
    "Company", "Job Title", "Killed At", "Reason", "Source", "Apply Link",
]

# ── MATERIALS TAB COLUMNS ─────────────────────────────────
# Queue of generated resumes/CLs. Status: Ready to Apply → Applied → Skipped.
MATERIALS_HEADERS = [
    "Date Generated", "Company", "Job Title", "Location",
    "Resume Link", "Cover Letter Link", "Apply Link",
    "Angle Used", "Screen Confidence", "Source",
    "Status", "Notes",
]

# ── TRACKER TAB COLUMNS ───────────────────────────────────
# Pipeline for actually-applied jobs. Populated by sync_applied.py.
TRACKER_HEADERS = [
    "Date Applied", "Company", "Job Title", "Location",
    "Apply Link", "Status", "Follow-up Date", "Follow-up Sent", "Notes",
    "Confidence",
]

# Keep for any legacy references
APPLIED_HEADERS = MATERIALS_HEADERS

# ── STARTUP VALIDATION ────────────────────────────────────
def validate_required_config() -> None:
    """Raise SystemExit with a clear message if required config is missing."""
    from pathlib import Path
    missing = []
    if not YOUR_NAME.strip():
        missing.append("YOUR_NAME (set in .env)")
    if not YOUR_EMAIL.strip():
        missing.append("YOUR_EMAIL (set in .env)")
    if not Path(GOOGLE_SHEETS_CREDS_FILE).exists():
        missing.append(f"GOOGLE_SHEETS_CREDS_FILE={GOOGLE_SHEETS_CREDS_FILE!r} (file not found)")
    if missing:
        raise SystemExit(
            "Missing required config:\n" + "\n".join(f"  • {m}" for m in missing)
        )
