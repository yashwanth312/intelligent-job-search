# Intelligent Job Search

An AI-assisted job-search pipeline you run from your own machine. Every morning it scrapes job boards, filters out noise with a fast regex gate and a Claude screen that scores each job against **your** profile, writes the survivors to a Google Sheet, and generates a tailored resume and cover letter (PDF) for every job you mark **Apply**. It then tracks outcomes so you can see which sources, titles and projects actually get callbacks.

The only interface is a Google Sheet. There is no app to host.

> **This repo ships neutral defaults.** It will run out of the box, but the results only get good after you (1) write your own `profile.yaml` and (2) tune the **title gate** to the roles you want. Both are covered step by step below. Budget about an hour for first-time setup.

---

## Contents

1. [How it works](#how-it-works)
2. [What you need](#what-you-need)
3. [Setup, step by step](#setup-step-by-step)
4. [Write your profile.yaml](#write-your-profileyaml)
5. [Tune the title gate (do this before your first real run)](#tune-the-title-gate)
6. [Other settings to review](#other-settings-to-review)
7. [Daily workflow](#daily-workflow)
8. [Commands](#commands)
9. [Growing your company list](#growing-your-company-list)
10. [Feedback loop](#feedback-loop)
11. [Troubleshooting](#troubleshooting)
12. [Project layout](#project-layout)
13. [Development and tests](#development-and-tests)

---

## How it works

```
profile.yaml ───────────────────────────────────────────────┐
                                                            ▼
Scrape ──► Freshness ──► (H-1B check) ──► Stage 1 ──► Stage 2 ──► Google Sheet
7 sources   last 24h       optional        regex       Claude      Daily  = confidence >= 3
                                           title +     scores      Audit  = everything rejected
                                           keywords    vs profile  (SQLite keeps all of it)
                                                                         │ you set Status = Apply
                                                                         ▼
                              Resume + cover letter PDFs ◄── generate_materials.py
                              (best 3 projects picked per job)   │
                                                                 ▼
                                   Materials tab ──► Tracker tab ──► feedback reports
```

**Sources** (all async, run in parallel): Greenhouse, Lever and Ashby company boards (direct JSON APIs, token lists in `target_companies.yaml`), Workday tenants, LinkedIn / Indeed / Google via [python-jobspy](https://github.com/Bunsly/JobSpy), the monthly Hacker News "Who is hiring" thread, and RemoteOK. Direct company boards are fresher and less contested than LinkedIn, so grow that list over time ([below](#growing-your-company-list)).

**Pipeline phases** (`python main.py`):

| # | Phase | What happens |
|---|---|---|
| 1 | Init | Load config, profile, SQLite, and the last 5 days of seen jobs |
| 2 | Clear | Wipe the Daily and Audit tabs (Materials and Tracker persist) |
| 3 | Scrape | All sources in parallel; Workday/LinkedIn descriptions are fetched only for jobs that pass the title gate |
| 4 | Freshness | Drop anything older than `HOURS_OLD` (24h) |
| 5 | Sponsor check | **Optional, off by default.** Drops employers with no DOL H-1B filing history ([details](#visa-sponsorship-and-work-authorization)) |
| 6 | Stage 1 | Regex gate: title in/out lists, location exclusions, seniority, years of experience, clearance, must-have keywords |
| 7 | Persist | Everything is written to SQLite before the sheets are touched |
| 8 | Stage 2 | Claude reads each surviving JD against your profile and returns a **confidence (1-5)**, an **interview likelihood (0-100)**, concrete **risk flags** for every unmet requirement, and a **resume angle** |
| 9 | Write | Confidence at or above `DAILY_MIN_CONFIDENCE` (3) goes to **Daily**; the rest go to **Audit** with their score and reason. Jobs Stage 2 could not score stay on Daily with a blank confidence so `rescreen.py --failed-only` can retry them |

**Resume generation** makes one Claude call per job and returns the resume and cover letter together. A deterministic scorer (no AI call) first ranks your `projects` against the JD's skills and gives Claude only the best three, so every resume leads with your most relevant work. Claude may only use facts that are in your profile; metrics it cannot find there are not allowed to appear.

**Stage 2 is deliberately strict.** It measures your real years of experience from dated roles, counts a skill as met only with evidence (work experience beats a built project beats a certification beats a bare skills-list entry), rounds ties down, and never inflates for "potential". Expect many jobs to score low. An honest 2 saves you an application you could not win.

---

## What you need

- **Python 3.10+**
- **Claude Code CLI**, logged in. Stage 2 and generation shell out to it, so they run on your Claude subscription. Install: `npm install -g @anthropic-ai/claude-code`, then run `claude` once and sign in. It consumes your Claude usage (Stage 2 batches 8 jobs per call; each resume is one call), and a first run can take an hour or more.
- **A Google account** for the Sheet (and optionally Drive). You will create a free service account in step 3.
- **WeasyPrint's native libraries** for PDF output: built in on macOS/Linux with a package manager, a GTK installer on Windows ([Troubleshooting](#troubleshooting)). Without them the pipeline still works and saves each resume as HTML to print from a browser.

---

## Setup, step by step

### 1. Clone and install

```bash
git clone https://github.com/yashwanth312/intelligent-job-search.git
cd intelligent-job-search
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code
claude                             # sign in once, then exit
```

### 2. Create your config files

```bash
cp .env.example .env
cp profile.example.yaml profile.yaml
```

(Windows cmd: use `copy` instead of `cp`.) Both are gitignored, so neither leaves your machine.

Open `.env` and fill in `YOUR_NAME`, `YOUR_EMAIL`, `YOUR_PHONE`, `YOUR_LOCATION_FALLBACK`, and your LinkedIn / GitHub. These appear in the **resume header**. Keep them identical to `personal:` in your profile. Leave every other value at its default for now.

### 3. Google Sheets

The pipeline reads and writes a spreadsheet through a **service account**, a robot Google identity.

1. Go to <https://console.cloud.google.com/>, create a project (any name).
2. **APIs & Services → Library**: enable **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account**. Name it anything and finish.
4. Open the service account → **Keys → Add key → Create new key → JSON**. Save the downloaded file as **`credentials.json` in the repo root** (it is gitignored).
5. In <https://sheets.google.com>, create a new spreadsheet whose name **exactly matches** `SPREADSHEET_NAME` in `.env` (default `Intelligent Job Search`).
6. Click **Share** and add the service account's `client_email` (find it inside `credentials.json`) as an **Editor**.

> Create the sheet yourself and share it. If the pipeline has to create a sheet, the service account owns it and you cannot see it.

The pipeline creates and formats the tabs (Daily, Audit, Materials, Tracker) itself.

**Google Drive upload is optional.** Leave `GOOGLE_DRIVE_FOLDER_ID` empty and PDFs stay in `./output/<company>/<date>_<role>/`, with local paths in the Materials tab. To use Drive, create a folder, share it with the service account, and put the ID from its URL in `.env`. Be aware that service accounts have no storage of their own, so uploading into a folder in a personal My Drive commonly fails with a storage-quota error. Leaving the setting empty is the safe default.

### 4. Write your profile

Follow [Write your profile.yaml](#write-your-profileyaml). This is the most important step.

### 5. Verify the install

```bash
python scripts/check_setup.py --online
```

It checks Python packages, `.env`, the credentials file, that `profile.yaml` validates and builds both prompts, project skill tags, the Claude CLI, WeasyPrint, and (with `--online`) that your Sheet is reachable. Fix every `[FAIL]`, and read every `[WARN]`. Typical warnings at this stage are "profile still contains example text" and "config still has the neutral default titles", and both mean you are not done with steps 4 and 6.

### 6. Tune the title gate

Follow [Tune the title gate](#tune-the-title-gate). Skipping this is the most common reason for a noisy first run.

### 7. First run

```bash
python main.py
```

Open the **Daily** tab. Set **Status** to `Apply` on jobs you want (the dropdown is Apply / Skip), then:

```bash
python generate_materials.py
```

Start with a handful of Apply rows and read the resumes closely before sending anything. If a resume says something your profile does not support, fix the profile (Claude can only reflect what you wrote there).

---

## Write your profile.yaml

`profile.yaml` is your **vault**: the single source of truth for screening and generation. `profile.example.yaml` is a fully working, commented template using a fictional person, so copy it and replace every value. **Claude is instructed to use only facts that are in this file.** If something is vague here, it will be vague on the resume; if it is not here, it cannot appear.

Check your work at any point: `python scripts/check_setup.py`.

### Field by field

| Section | Required | Used for | Notes |
|---|---|---|---|
| `personal.name / email / phone / location` | yes | Resume header and cover-letter signoff | `location` is copied verbatim onto every resume (never the job's city) |
| `personal.visa` | no | Cover-letter closing | If non-empty, the cover letter ends with one neutral sentence built only from this text, e.g. `"F-1 OPT through June 2028"`. **Leave `""` to never mention work authorization.** |
| `personal.linkedin` | no | Resume header | |
| `education` | yes | Education section | Copied verbatim. `gpa` is optional |
| `experiences` | yes | Work history | Every experience appears on every resume (total years of experience is an ATS signal) unless you set `omit: true` |
| `experiences[].framings` | yes | Per-job bullet choice | See below |
| `experiences[].raw_context` | recommended | Source for fresh bullets | Free text: stack, scale, outcomes, **real numbers** |
| `experiences[].locked_title` | no | Title on every resume | Use when recruiters will cross-check your LinkedIn title |
| `projects` | recommended | Resume project section, skill evidence for Stage 2 | List more than 3 if you have them; the best 3 are picked per job |
| `portfolio_catalog` | no | Planned projects | Advanced. Leave `[]`. See [examples/portfolio_catalog](examples/portfolio_catalog/README.md) |
| `certifications` | no | Up to 3 chosen per resume | Active ones preferred. IDs and dates are copied verbatim |
| `training` | no | Courses and bootcamps | |
| `skills` | yes | Skills section | Grouped any way you like; categories are renamed and re-ordered per job using **only** items you list |
| `publications` | no | Publications section | Delete the key entirely if you have none (do not leave `[]`) |

### Framings: one job, several honest angles

A framing is an alternative way to present the **same** job. Name each key after the kind of role it suits, then write bullets that are true but emphasise different work:

```yaml
experiences:
  - company: "Acme Corp"
    period: "June 2023 – Present"
    framings:
      backend:                       # chosen for software / API roles
        title: "Software Engineer"
        bullets:
          - "Built FastAPI services handling 1.2M requests/day at p95 < 120 ms."
      devops:                        # chosen for platform / SRE roles
        title: "Software Engineer (Platform)"
        bullets:
          - "Moved deploys from manual SSH to GitHub Actions, cutting release time from 2 h to 15 min."
```

For each job the generator picks the framing whose bullets best match the posting. One framing is fine; two or three is better if your role genuinely spanned them. Stage 2 also names the framing key to lead with in its `suggested_angle`.

### Projects and skill tags

Each project needs `skills` tags so the scorer can match it to job descriptions. Tags are keys in `generation/skill_taxonomy.py`; list them with:

```bash
python -c "from generation.skill_taxonomy import SKILLS; print(sorted(SKILLS))"
```

Put the 2-4 skills the project proves best in `core`, secondary skills in `supporting`, passing mentions in `touch`. An untagged project can still be selected but scores poorly, and `check_setup.py` warns about it.

> **The built-in taxonomy covers cloud, infrastructure, DevOps, security, IT, backend and data/AI skills.** If your field is not covered (for example mobile or game development), add entries to `SKILLS` in `generation/skill_taxonomy.py` (key → regex of ways a JD names it), then optionally rebuild the rarity weights with `python scripts/build_skill_idf.py` once you have a few weeks of scraped jobs in `jobs.db`.

### Tips that matter

- **Put numbers in `raw_context`.** Claude cannot invent metrics, so a result you do not write down will not appear.
- **Be exact with titles and dates.** They are never altered.
- **Do not paste a resume.** Write what you did, with stack, scale and outcome. Claude writes the bullets.
- **Keep it honest.** Stage 2 uses this same file to score jobs, and overstated skills simply produce false confidence.
- **`.env` vs `profile.yaml`:** the resume *header* comes from `.env`, the *body* from `profile.yaml`. `check_setup.py` warns if the names differ.

---

## Tune the title gate

The title gate decides which job titles are **searched** (`TARGET_TITLES`) and which survive **Stage 1** (the keyword lists). It is the single biggest lever on result quality, and **the shipped defaults are a broad, generic software starting point on purpose**. Tune it to the roles you want before you trust the Daily tab.

### How the gate works

`screening/stage1.py → title_passes(title)`, case-insensitive and **whole-word**:

1. If the title contains any word in `EXCLUDE_TITLE_KEYWORDS` (senior, staff, manager, intern, new grad, ...), it is **dropped**.
2. If it contains an `ML_TITLE_KEYWORDS` word, it must **also** contain a `CORE_TITLE_KEYWORDS` word or an `ML_TITLE_LLM_EXEMPTIONS` word, otherwise it is **dropped**. (Empty by default, so this step is off.)
3. It must contain a `TITLE_DOMAIN_KEYWORDS` word (`CORE_TITLE_KEYWORDS + EXTRA_TITLE_KEYWORDS`) to **pass**, or else an `IT_IDENTITY_TITLE_KEYWORDS` word with no `IT_IDENTITY_SECURITY_BLOCKERS` word. (Also empty by default.)

Whole-word matching means `"security"` does **not** match `"cybersecurity"` (list both) and `"ai"` does not match `"maintenance"`. Use multi-word phrases when a bare word is too broad: `"data"` admits "Data Scientist", but `"data engineer"` does not.

### Edit these in `config.py`

| Setting | Purpose |
|---|---|
| `TARGET_TITLES` | One LinkedIn/Indeed/Google search per title × location. These must also pass the gate, which `tests/test_config.py` enforces |
| `CORE_TITLE_KEYWORDS` / `EXTRA_TITLE_KEYWORDS` | Words that admit a title |
| `EXCLUDE_TITLE_KEYWORDS` | Words that kill a title (seniority, non-software disciplines, ...) |
| `ML_TITLE_KEYWORDS`, `ML_TITLE_LLM_EXEMPTIONS` | Optional: keep pure-ML titles out unless they also name your domain |
| `IT_IDENTITY_TITLE_KEYWORDS`, `IT_IDENTITY_SECURITY_BLOCKERS` | Optional: a second admission family (sysadmin, identity, endpoint) |
| `REQUIRE_ONE_OF` | Words a **description** must mention (several of them) to pass Stage 1. Put your core skills here |
| `LOCATIONS` | Cities searched (runtime grows with titles × locations; `"United States"` and `"Remote"` are catch-alls) |
| `EXCLUDE_LOCATION_PATTERNS` | Countries and cities dropped (defaults exclude non-US; edit if you want other countries) |

### Ready-made recipes

[`examples/title_gate_recipes.py`](examples/title_gate_recipes.py) contains three complete, tested sets of the values above. Copy the one closest to your goal over the matching names in `config.py` and adjust.

- **`infra_and_ai`** is the strategy this project was tuned on (below).
- **`backend_software`** and **`data_engineering`** are sensible starting points that have not been tuned on outcome data.

Example, shifting the defaults to a **cloud / SRE / platform** search, taken from `infra_and_ai`:

```python
TARGET_TITLES = [
    "Cloud Engineer", "Infrastructure Engineer", "Systems Engineer",
    "Site Reliability Engineer", "Platform Engineer", "DevOps Engineer",
]
CORE_TITLE_KEYWORDS = [
    "cloud", "devops", "sre", "platform", "infrastructure", "reliability",
    "kubernetes", "observability", "systems", "mlops", "aws", "gcp", "azure",
    "terraform", "docker", "ansible", "automation", "linux",
]
EXTRA_TITLE_KEYWORDS = []                       # or ["ai", "genai", "llm", "llmops"] to keep AI engineering
REQUIRE_ONE_OF = ["aws", "gcp", "azure", "cloud", "kubernetes", "terraform", "devops",
                   "sre", "platform", "infrastructure", "ci/cd", "docker", "linux", "observability"]
```

### Keep one AI family but drop pure-ML titles

```python
EXTRA_TITLE_KEYWORDS    = ["ai", "genai", "generative", "agentic", "llm", "llmops"]
ML_TITLE_KEYWORDS       = ["ml", "machine learning", "deep learning"]
ML_TITLE_LLM_EXEMPTIONS = ["genai", "generative", "agentic", "agent", "agents", "llm", "llmops"]
```

"ML Platform Engineer" and "Founding AI/ML Engineer, Agents" still pass; "Machine Learning Engineer" and "AI/ML Engineer" are dropped.

### Add a sysadmin / identity family without admitting security roles

```python
IT_IDENTITY_TITLE_KEYWORDS    = ["systems administrator", "sysadmin", "windows", "active directory",
                                 "identity", "iam", "entra", "endpoint", "intune", "m365", "vmware"]
IT_IDENTITY_SECURITY_BLOCKERS = ["security", "cybersecurity", "cyber", "threat", "soc"]
```

### The tuning strategy behind the `infra_and_ai` recipe

Reuse the method, not just the values:

1. **Start broad, then let your own outcomes narrow it.** After a few weeks, run `python feedback_sync.py` and `python scripts/outcome_report.py` to see callback rates by job domain, source and month.
2. **Narrow only on evidence.** In the run this recipe came from, about 1,000 applications produced 7 callbacks, **all** in cloud / SRE / systems-and-infrastructure roles, while AI/ML-modelling (0 of 238), generic software engineering (0 of 128) and security-analyst roles (0 of 73) produced none. The gate was narrowed to the converting family. Small samples lie, so treat anything under a few hundred applications as a hint, not a verdict.
3. **Do not delete a family after one miss.** An AI-engineering family was dropped and restored when the narrowed gate silently excluded an "AI Engineer" role (really LLMOps / platform work) that sent an assessment. Prefer the optional gates above (for example `ML_TITLE_KEYWORDS`) to keep a shape you want and drop the shape you do not.
4. **Look at the Audit tab.** Every title the gate rejected is listed with the reason. If good jobs are being killed, add a word; if junk is getting through, add an exclusion.
5. **Prefer direct company boards to LinkedIn.** They are less crowded and fresher; see [Growing your company list](#growing-your-company-list).
6. **Seniority:** the defaults exclude senior/staff/lead/manager and campus-recruiting titles but keep "junior", "associate" and "entry level". Delete entries from `EXCLUDE_TITLE_KEYWORDS` if you target senior roles or are a new grad.

### Test a change in seconds

```bash
python -c "from screening.stage1 import title_passes as p; print([ (t, p(t)) for t in ['Platform Engineer','Senior SRE','AI/ML Engineer']])"
python -m pytest tests/test_config.py tests/test_stage1.py -q
```

`tests/test_config.py` fails if any `TARGET_TITLES` entry would be dropped by your own gate, which catches the "I search for a title I then throw away" mistake.

---

## Other settings to review

Set in `.env` (no code edit) or in `config.py`:

| Setting | Default | What it does |
|---|---|---|
| `SPONSORSHIP_FILTER_ENABLED` | `false` | Visa-sponsorship filtering. See [below](#visa-sponsorship-and-work-authorization) |
| `MIN_YOE_HARD_STOP` | `4` | A JD that *requires* this many years or more is dropped in Stage 1. Set to about your experience plus one; `99` disables |
| `TARGET_LEVEL` | `0-3 years / junior-to-mid` | The level Stage 2 judges you against. Edit it to match, e.g. `5-8 years / senior` |
| `SALARY_FLOOR` | `0` | Drop jobs whose stated maximum salary is below this (`0` = off) |
| `DAILY_MIN_CONFIDENCE` (config.py) | `3` | Stage 2 confidence needed to reach Daily; the rest go to Audit |
| `HOURS_OLD` (config.py) | `24` | Freshness window |
| `STAGE2_MODEL`, `RESUME_GENERATION_MODEL` (config.py) | Haiku / Sonnet | Raise `STAGE2_MODEL` to a Sonnet model for sharper screening at higher cost |
| `RESUME_VERIFICATION_ENABLED` (config.py) | `False` | Optional recruiter-simulation pass that regenerates weak resumes. Adds 2-3 Claude calls per job |
| `EXCLUDE_DESC_PATTERNS` (config.py) | clearance / citizenship phrases | See below |
| `CLAUDE_CLI` | auto-detected | Set only if `claude` is not found |
| `USER_LAPTOP_REPO_PATH` | this repo | Root used for file paths in the Materials tab |

### Visa sponsorship and work authorization

- **Need an employer to sponsor you** (for example F-1 OPT heading to H-1B): set `SPONSORSHIP_FILTER_ENABLED=true`. Phase 5 then drops employers with no H-1B filing history, Stage 1 drops JDs that say they will not sponsor, and Stage 2 reduces confidence by one for unverified employers. Put your status in `personal.visa` if you want it stated in cover letters. Also delete `"usc/gc"`, `"us citizen"`, `"green card"`, `"citizens only"` and similar from `EXCLUDE_TITLE_KEYWORDS` **only** if they do not apply to you; for most visa holders they should stay.
- **Do not need sponsorship** (citizen, green-card holder): leave it `false`, leave `personal.visa` empty, and remove the citizenship phrases from `EXCLUDE_TITLE_KEYWORDS` and `EXCLUDE_DESC_PATTERNS`. If you hold a security clearance, also remove the clearance phrases.
- **How the sponsor check works.** It is an **offline** lookup against the US Department of Labor's public LCA disclosure data (`data/h1b_filers.txt`, about 1.9 MB, shipped with the repo; prefix matching biased toward keeping a job when unsure). No network calls, no rate limits. The run summary prints the index age and flags it when older than `H1B_INDEX_STALE_DAYS` (150).
- **Refreshing the index** when DOL posts a new quarter: download the quarterly "LCA Programs (H-1B, H-1B1, E-3)" `.xlsx` files from <https://www.dol.gov/agencies/eta/foreign-labor/performance> **in a browser** (the site blocks scripted downloads), put the latest eight in `data/lca/` (gitignored), and run `python scripts/build_lca_index.py`.

---

## Daily workflow

```bash
python main.py                  # 1. scrape + screen   -> Daily and Audit tabs
# In the Daily tab: Status = Apply / Skip (dropdown). Read Risk Flags first.
python generate_materials.py    # 2. PDFs for every Apply row -> Materials tab
# Apply to the job; set Materials Status to "Applied".
python sync_applied.py          # 3. Materials(Applied) -> Tracker tab
# In Tracker: move Status through Reached out / Phone Screen / Interview / Offer / Rejected / No Response.
python feedback_sync.py         # 4. outcomes -> SQLite
python feedback_report.py       # 5. what is converting
```

**Daily tab columns:** Company, Job Title, Location, **Confidence** (1-5), **Status**, **Interview Score (%)**, **Risk Flags** (every unmet requirement, stated concretely), Apply Link, Posted, Source, AI Reasoning, **Suggested Angle** (which framing and projects to lead with, plus the five keywords the resume must surface), Match Signals, Sponsorship, Salary Range, Notes.

**Interview score** is Stage 2's estimate, on fit alone, of how likely a strict recruiter is to interview you from a truthful resume. It is not tied to callback history and never exceeds 90.

Each generated application is saved to `output/<company>/<date>_<role>/` as a resume PDF, a cover-letter PDF and `_metadata.json`. If PDF rendering fails, an `.html` fallback is written and the Materials row is flagged.

---

## Commands

| Command | Purpose |
|---|---|
| `python scripts/check_setup.py [--online]` | Verify a fresh install |
| `python main.py` | Daily scrape + screen |
| `python generate_materials.py` | Resume + cover letter PDFs for Apply rows |
| `python rescreen.py [--failed-only]` | Re-run Stage 2 on the Daily tab (`--failed-only` retries only unscored rows) |
| `python sync_applied.py` | Materials (Applied) → Tracker |
| `python feedback_sync.py` | Outcomes from Materials/Tracker → SQLite |
| `python feedback_report.py` | Callback rates by source, angle, confidence and project |
| `python scripts/outcome_report.py [--since D] [--split D]` | Callback rates by domain, source, month and project; `--split` compares before/after a date |
| `python update_profile.py` | Interactive helper to add projects/skills/certs to `profile.yaml` |
| `python scripts/build_skill_idf.py` | Rebuild the skill-rarity table from your scraped jobs (monthly) |
| `python scripts/replay_project_scorer.py` | See which 3 projects the scorer picks for past applications |
| `python scripts/project_usage.py` | Per-project usage and callbacks |
| `python scripts/build_lca_index.py` | Rebuild the H-1B employer index |
| `python scripts/discover_ats_boards.py --limit 4000 [--apply]` | Find more Greenhouse/Lever/Ashby boards |
| `python scripts/promote_workday_candidates.py [--dry-run]` | Validate and promote discovered Workday tenants |
| `python scripts/verify_*_tokens.py` | Check company tokens in `target_companies.yaml` |
| `pytest tests/ -v` | Run the test suite |

---

## Growing your company list

`target_companies.yaml` lists the Greenhouse, Lever, Ashby and Workday boards that are scraped directly. It ships with a few thousand companies. Every posting from a board is checked by the same title gate, so a large list costs little.

- **Add one by hand:** add `- token: acme` under the right ATS section (the token is the path segment in `boards.greenhouse.io/<token>`, `jobs.lever.co/<token>` or `jobs.ashbyhq.com/<token>`).
- **Discover at scale:** `python scripts/discover_ats_boards.py --limit 4000` slugifies every company name your database has ever seen and probes the public ATS APIs; add `--apply` to write the hits to `target_companies.yaml`, and `--min-infra 1` to keep only boards with at least one title that passes your gate. This needs a populated `jobs.db`, so run `main.py` for a week first.
- **Workday:** tenants seen on LinkedIn redirects are staged in `workday_candidates.yaml`; `scripts/promote_workday_candidates.py` promotes the ones that advertise titles your gate accepts and records rejects in `workday_rejected.yaml`.

---

## Feedback loop

Everything is stored in SQLite (`jobs.db`): `jobs` (every scraped job), `audit` (every rejection with its stage and reason, so you can see *why* days later), `feedback` (applications, the resume angle and projects used, and outcomes), and caches. Daily and Audit tabs are wiped each run, but nothing is lost.

After you have a few dozen applications with outcomes, use `outcome_report.py` and `feedback_report.py` to see which domains, sources and projects convert, and feed that back into the [title gate](#the-tuning-strategy-behind-the-infra_and_ai-recipe) and your profile.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing required config: YOUR_NAME ...` | Fill the personal lines in `.env` |
| `Claude CLI not found` | `npm install -g @anthropic-ai/claude-code`, run `claude` once to sign in, or set `CLAUDE_CLI` in `.env` |
| `SpreadsheetNotFound` | The sheet name must match `SPREADSHEET_NAME` exactly **and** be shared (Editor) with the service account's `client_email` |
| `403` / API not enabled | Enable the Sheets API and Drive API in your Google Cloud project |
| Resumes saved as `.html`, status "PDF Render Failed" | WeasyPrint's native libraries are missing. **macOS:** `brew install pango`. **Debian/Ubuntu:** `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`. **Windows:** install the [GTK3 runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases), restart the terminal, verify with `python -c "from weasyprint import HTML"`. Or print the HTML from a browser |
| Daily tab nearly empty | Open **Audit** to see why jobs were killed. Usually the title gate, `REQUIRE_ONE_OF`, `MIN_YOE_HARD_STOP`, or Stage 2 scoring low (which is honest, not a bug) |
| Daily tab full of irrelevant jobs | Tighten `CORE_TITLE_KEYWORDS` and `REQUIRE_ONE_OF`, add `EXCLUDE_TITLE_KEYWORDS`, or set `DAILY_MIN_CONFIDENCE = 4` |
| Rows with blank Confidence | Stage 2 failed for that job (timeout). `python rescreen.py --failed-only` |
| Stage 2 times out often | Lower `SCREENING_MAX_WORKERS` or `SCREENING_BATCH_SIZE`, or raise `STAGE2_TIMEOUT` |
| A resume claims something untrue | It cannot come from nowhere: search `profile.yaml` for the claim and correct or delete it |
| Run takes very long | Titles × locations drives LinkedIn time. Trim `LOCATIONS` and `TARGET_TITLES` |
| Everything on a 429 / blocked | LinkedIn rate limits; the run backs off and continues. Run less often or with fewer locations |

---

## Project layout

```
main.py                     daily pipeline            config.py          every tunable
generate_materials.py       resumes + cover letters   profile.example.yaml  profile template
rescreen.py                 re-run Stage 2            .env.example       secrets/personal template
sync_applied.py             Materials -> Tracker      target_companies.yaml  company boards
feedback_sync.py / feedback_report.py                 pipeline_ui.py     terminal progress UI
sources/        scrapers (one adapter per source, shared bounded fan-out for ATS boards)
screening/      stage1.py (regex), stage2.py (Claude), h1b_checker.py + lca_index.py (offline sponsor lookup)
generation/     claude_cli.py (isolated runner), resume_engine.py, project_scorer.py,
                skill_taxonomy.py, pdf_renderer.py, drive_uploader.py, ats.py, verifier.py
sheets/         Google Sheets tabs + formatting
models/         Pydantic models           db/            SQLite layer
prompts/        screening.md, application_materials.md (edit to change tone/rules)
scripts/        check_setup, reports, board discovery, index builders
examples/       title_gate_recipes.py, portfolio_catalog/
tests/          pytest suite (runs with no profile, .env or credentials)
```

Prompts are plain files in `prompts/`. `prompts/application_materials.md` holds the resume and cover-letter rules (banned phrases, structure, honesty rules); `prompts/screening.md` holds the Stage 2 scoring rules. Both read your facts from `profile.yaml`, so you can change tone without touching any person-specific data.

---

## Development and tests

```bash
pytest tests/ -v
```

The suite needs no profile, `.env`, credentials or database. It includes tests that guard the fresh-clone experience: every module imports, the example profile validates and builds both prompts, a full generation round-trip (Claude mocked) renders a resume, the documented title-gate recipes behave as the README says, and no personal identifiers appear in tracked files.

Every Claude call goes through `generation/claude_cli.run_claude`, which runs the CLI isolated from this repository's agent context (no project instructions, memory, hooks or saved transcript). Keep new call sites on it.
