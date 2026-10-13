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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

# ── PERSONAL INFO ──────────────────────────────────────────
# Set these in .env — see .env.example
YOUR_NAME = os.getenv("YOUR_NAME", "")
YOUR_EMAIL = os.getenv("YOUR_EMAIL", "")
YOUR_PHONE = os.getenv("YOUR_PHONE", "")
YOUR_LOCATION_FALLBACK = os.getenv("YOUR_LOCATION_FALLBACK", "")
YOUR_LINKEDIN = os.getenv("YOUR_LINKEDIN", "")
YOUR_GITHUB = os.getenv("YOUR_GITHUB", "")

# Absolute path to this repo on your machine. Materials-tab file links are
# written as absolute paths under this root so they can be pasted into
# job-application upload dialogs. Leave unset to use the repo's own location
# (auto-detected); set it in .env only if you open the files from another
# machine or a synced folder.
USER_LAPTOP_REPO_PATH = os.getenv("USER_LAPTOP_REPO_PATH", "") or os.path.dirname(
    os.path.abspath(__file__)
)

# ── GOOGLE INTEGRATIONS ───────────────────────────────────
GOOGLE_SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Intelligent Job Search")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# ── DATABASE ──────────────────────────────────────────────
DB_FILE = "jobs.db"

# ── TARGET JOB TITLES ─────────────────────────────────────
# >>> TUNE THIS FIRST. See "Tune the title gate" in README.md. <<<
# Used as both LinkedIn/Indeed search queries AND Stage 1 title matching.
# Each title gets its own dedicated search so niche titles are never buried.
# Do not add "Junior X" / "Associate X" variants: LinkedIn returns the same
# postings regardless of those qualifiers, so they only add scrape time.
# Seniority is filtered after scraping by EXCLUDE_TITLE_KEYWORDS.
# These neutral defaults are a broad software starting point.
TARGET_TITLES = [
    "Software Engineer",
    "Backend Engineer",
    "Full Stack Engineer",
    "Data Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
]

# ── LOCATIONS ─────────────────────────────────────────────
# Each location is searched once per title on LinkedIn/Indeed/Google, so runtime
# grows with titles x locations. "United States" is a national catch-all that
# surfaces postings in secondary metros; "Remote" catches remote-only roles.
LOCATIONS = [
    "New York, NY",
    "San Francisco, CA",
    "Seattle, WA",
    "Austin, TX",
    "United States",
    "Remote",
]

# ── CLAUDE CLI ────────────────────────────────────────────
def _find_claude_cli() -> str:
    """Locate the Claude CLI binary, trying platform-specific install paths."""
    # Honor the CLAUDE_CLI env var first (the Stage 2
    # error message already tells users to set it), then a workspace shim
    # that survives reboots (npm global bin is outside the workspace).
    env_cli = os.environ.get("CLAUDE_CLI", "").strip()
    if env_cli and (shutil.which(env_cli) or os.path.isfile(env_cli)):
        return env_cli
    workspace_shim = os.path.expanduser("~/workspace/bin/claude")
    if os.path.isfile(workspace_shim):
        return workspace_shim
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
    "pakistan", "karachi", "islamabad", "lahore",
    "bangladesh", "dhaka", "chittagong",
    "sri lanka", "colombo",
    "nepal", "kathmandu",
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
    "iceland", "reykjavik",
    "greece",
    "turkey", "istanbul",
    "cyprus", "malta", "luxembourg",
    # Eastern Europe / Balkans / Baltics.
    # Bare "moscow"/"riga"/"belgrade" deliberately omitted: they collide with
    # real US places (Moscow ID, Riga MI, Belgrade MT) — the country-level
    # token still catches the normal "City, Country" format for those.
    "lithuania", "vilnius", "kaunas",
    "latvia",
    "estonia", "tallinn",
    "croatia", "zagreb", "split",
    "serbia", "novi sad",
    "bosnia and herzegovina", "sarajevo",
    "bulgaria", "sofia",
    "slovenia", "ljubljana",
    "ukraine", "kyiv",
    "belarus",
    "moldova", "chisinau",
    "north macedonia", "skopje",
    "montenegro", "podgorica",
    "albania", "tirana",
    # " russia" (leading space) not bare "russia" — bare substring-matches
    # "King of Prussia, PA, US".
    " russia",
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
    "jordan", "amman",
    "lebanon", "beirut",
    "iraq", "baghdad",
    "qatar", "doha",
    "kuwait",
    "bahrain",
    "oman",
    "nigeria", "abuja",
    "kenya", "nairobi",
    "morocco", "casablanca", "rabat",
    "ghana", "accra",
    "ethiopia", "addis ababa",
    "tunisia",
    "algeria", "algiers",
    "uganda", "kampala",
    "tanzania",
    "rwanda", "kigali",
    "senegal", "dakar",
    "zimbabwe", "harare",
    # Caucasus / Central Asia. Bare
    # "georgia" (country) omitted: collides with the US state — "tbilisi"
    # still catches the "City, Georgia" format for that country.
    "armenia", "yerevan",
    "azerbaijan", "baku",
    "tbilisi",
    "kazakhstan", "almaty", "astana",
    "kyrgyzstan", "bishkek",
    "uzbekistan", "tashkent",
    "tajikistan",
    "turkmenistan",
    # Canada (US companies often post CA roles separately)
    "canada", "toronto", "vancouver", "montreal", "ottawa", "waterloo",
    "burnaby", "calgary", "edmonton", "winnipeg", "quebec", "halifax",
    # Latin America
    "mexico", "brazil", "colombia", "bogota", "argentina", "buenos aires",
    "chile", "santiago", "costa rica", "guanajuato",
    "peru",
    "uruguay", "montevideo",
    "venezuela", "caracas",
    "ecuador", "quito",
    "bolivia",
    "paraguay",
    "guatemala",
    # ", panama" not bare "panama" — bare substring-matches
    # "Panama City, FL, US".
    ", panama",
    "el salvador",
    "honduras",
    "nicaragua",
    "dominican republic",
]

# ── TITLE EXCLUSIONS ──────────────────────────────────────
# Word-boundary match against the job title; a hit drops the job in Stage 1.
EXCLUDE_TITLE_KEYWORDS = [
    # Seniority / employment type. Remove entries here if you are targeting
    # senior roles. "contract" is deliberately not listed: contract-to-hire is
    # a common early-career entry path.
    "senior", "sr.", "sr ", "lead", "staff", "principal",
    "manager", "director", "vp ", "vp,", "vice president", "head of",
    "intern", "internship",
    "part-time", "part time", "freelance", "temporary",
    # Mass-intake university programs. Delete these if you ARE a new grad.
    "new grad", "new graduate", "new college grad", "college graduate",
    "university graduate", "university recruiting", "campus hire",
    "early career", "rotational program", "returnship",
    # Non-software engineering disciplines (industrial/hardware)
    "electrical engineer", "mechanical engineer", "civil engineer",
    "controls engineer", "building automation", "hvac",
    "asic", "fpga",
    # Industrial/plant-floor work that slips through on broad words like
    # "automation" and "systems".
    "marketing automation", "sales automation", "automation technician",
    "technician", "quality systems", "thermal", "mechatronics", "plc ",
    "scada", "field service", "manufacturing", "warehouse", "machinist",
    "maintenance", "calibration", "tooling",
    # Work-authorization hard stops written into the TITLE (staffing firms do
    # this constantly). Only useful if you cannot meet them; delete them if
    # you are a US citizen / green-card holder.
    "usc/gc", "usc only", "gc only", "us citizen", "green card",
    "citizens only", "no c2c", "w2 only", "clearance",
    # Non-IC / pre-sales roles
    "solutions architect", "presales", "pre-sales",
    # IT support
    "desktop support", "direct support",
]

# ── TITLE DOMAIN KEYWORDS ─────────────────────────────────
# >>> TUNE THIS SECOND. See "Tune the title gate" in README.md. <<<
# A title must contain at least one of these (word-boundary match) to survive
# Stage 1. Matching is \bword\b, so compound forms must be listed explicitly:
# "security" does NOT match "cybersecurity". Short tokens (ai, ml, it, sre)
# rely on the word boundary to avoid false positives ("ai" must not match
# "maintenance"). Do NOT switch this to substring matching for that reason.
CORE_TITLE_KEYWORDS = [
    "software", "backend", "back-end", "frontend", "front-end",
    "full stack", "full-stack", "fullstack", "web", "api",
    "data", "cloud", "devops", "platform", "infrastructure",
    "reliability", "sre", "systems", "developer",
]

# A second bucket for a specialty you want to keep separately tunable (for
# example AI words: "ai", "genai", "llm"). Empty by default.
EXTRA_TITLE_KEYWORDS: list[str] = []

TITLE_DOMAIN_KEYWORDS = CORE_TITLE_KEYWORDS + EXTRA_TITLE_KEYWORDS

# ── OPTIONAL TITLE FAMILIES (empty = disabled) ────────────
# ML titles need a second word. A title containing any ML_TITLE_KEYWORDS word
# is admitted only if it ALSO carries a CORE_TITLE_KEYWORDS word or an
# ML_TITLE_LLM_EXEMPTIONS word. Use this to keep pure-modelling roles out while
# keeping ML platform / MLOps roles in. Example in README.md.
ML_TITLE_KEYWORDS: list[str] = []
ML_TITLE_LLM_EXEMPTIONS: list[str] = []

# A second admission family for titles that carry none of the domain words
# above, e.g. IT / sysadmin / identity titles. A title in this family passes
# only if it has none of IT_IDENTITY_SECURITY_BLOCKERS. Example in README.md.
IT_IDENTITY_TITLE_KEYWORDS: list[str] = []
IT_IDENTITY_SECURITY_BLOCKERS: list[str] = []

# ── SPONSORSHIP FILTER (master toggle) ────────────────────
# OFF by default. Turn it ON (SPONSORSHIP_FILTER_ENABLED=true in .env) only if
# you need an employer to sponsor a work visa. When True:
#   • Phase 5 checks employers against DOL LCA (H-1B) filings and drops
#     employers with no filing history (offline index, data/h1b_filers.txt)
#   • Stage 1 hard-stops JDs that explicitly say "we don't sponsor"
#   • Stage 2 treats explicit no-sponsor JD language as a disqualifier and
#     reduces confidence by 1 for unverified companies
SPONSORSHIP_FILTER_ENABLED = _env_bool("SPONSORSHIP_FILTER_ENABLED", False)

# ── DESCRIPTION HARD-STOP PATTERNS ────────────────────────
# ALWAYS enforced, independent of the sponsorship toggle. They assume you hold
# no security clearance and are not a US citizen. If you DO hold a clearance
# or are a citizen, set this list to [] to see those jobs.
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
# A hard requirement of this many years or more is a hard disqualifier.
# Set it near your own experience + 1. Use 99 to disable. Also describe your
# level in TARGET_LEVEL below so Stage 2 judges consistently.
# "Preferred"/"nice to have" YOE mentions are intentionally NOT hard-stopped
# here; only requirement-shaped phrasing is: "N+ years", "N or more years",
# "at least/minimum N years", a numeric range ("A-B years"/"A to B years"),
# or bare "N years [...] experience". See screening/stage1.py for the regex.
MIN_YOE_HARD_STOP = int(os.getenv("MIN_YOE_HARD_STOP", "4"))

# How Stage 2 describes the level you target. Filled into prompts/screening.md.
TARGET_LEVEL = os.getenv("TARGET_LEVEL", "0-3 years / junior-to-mid")

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
# A description must mention several of these to pass Stage 1. Put your own
# core skills here (lowercase). Neutral defaults below.
REQUIRE_ONE_OF = [
    "python", "java", "javascript", "typescript", "go", "sql", "api",
    "aws", "gcp", "azure", "cloud", "kubernetes", "docker", "terraform",
    "ci/cd", "linux", "react", "node", "microservices", "devops",
    "data pipeline", "machine learning",
]

# ── SALARY FLOOR ──────────────────────────────────────────
# Drop jobs whose stated maximum salary is below this. 0 disables the check.
SALARY_FLOOR = int(os.getenv("SALARY_FLOOR", "0"))

# ── SCREENING SETTINGS ────────────────────────────────────
# Minimum Stage 2 confidence for a job to be written to the Daily tab; below
# it the job goes to the Audit tab with its score and reasoning. Defaults to 3.
# There are no verdicts — confidence, interview
# score and risk flags are the screening output. Unscored jobs (Stage 2
# failure) still go to Daily, blank confidence, for `rescreen.py --failed-only`.
DAILY_MIN_CONFIDENCE = 3
SCREENING_BATCH_SIZE = 8            # JDs per Claude CLI invocation — prompt goes via stdin not argv, so no 32KB limit concern
# Batches used to run strictly sequentially: measured 10-22 batches/run
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
# claude_usage over the 400 most recent screening calls (measured on a real run):
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
# in one measured run, 22/32 batches (204/253 jobs) timed out on both attempts and were
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
# DOL posts LCA disclosure data quarterly; past this age the run summary
# flags data/h1b_filers.txt for a rebuild (scripts/build_lca_index.py).
H1B_INDEX_STALE_DAYS = 150

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
