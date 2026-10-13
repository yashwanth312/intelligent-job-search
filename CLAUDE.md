# CLAUDE.md — Intelligent Job Search

Guidance for Claude Code when working in this repository. The README is the
user guide; this file is the short contributor map.

## Commands

```bash
pip install -r requirements.txt
python scripts/check_setup.py [--online]   # verify a new install
python main.py                             # scrape + screen -> Daily/Audit tabs
python generate_materials.py               # resumes + cover letters for Status=Apply
python rescreen.py [--failed-only]         # re-run Stage 2 on the Daily tab
python sync_applied.py                     # Materials(Applied) -> Tracker
python feedback_sync.py                    # outcomes -> SQLite
python feedback_report.py                  # callback rates by source/angle/confidence
python scripts/outcome_report.py [--since D] [--split D]
python scripts/build_lca_index.py          # rebuild the offline H-1B index
python scripts/build_skill_idf.py          # rebuild the skill rarity table
python scripts/replay_project_scorer.py    # check resume project picks
pytest tests/ -v
```

## Architecture

1. Profile vault (`profile.yaml`, gitignored; template: `profile.example.yaml`)
2. Scrapers (`sources/`): Greenhouse, Lever, Ashby, Workday, LinkedIn/Indeed/Google
   via JobSpy, HackerNews, RemoteOK. All async; adapters implement
   `sources.base.SourceAdapter`.
3. Screening (`screening/`): Stage 1 regex gate, optional offline H-1B check,
   Stage 2 Claude scoring (confidence 1-5, interview likelihood, risk flags).
4. Google Sheets UI (`sheets/`): Daily + Audit are wiped each run; Materials and
   Tracker persist. SQLite (`jobs.db`) is the source of truth.
5. Generation (`generation/`): one Claude CLI call returns resume + cover letter;
   WeasyPrint renders PDFs; `project_scorer.py` picks the 3 best projects per JD.
6. Feedback loop: SQLite outcome tracking and reports.

## Conventions

- Pydantic models at data boundaries (`models/`).
- Every Claude call goes through `generation/claude_cli.run_claude`, which
  isolates it from the repo (no CLAUDE.md, memory, hooks or saved transcript).
  New call sites must use it.
- Prompts are files in `prompts/`; placeholders look like `{{name}}`.
- `config.py` holds every tunable. Personal values belong in `.env` or
  `profile.yaml`, never in tracked files. `tests/test_fresh_clone.py` fails if
  personal identifiers or gitignored imports sneak in.
- The title gate has one entry point, `screening.stage1.title_passes`; the board
  adapters pre-filter with it so boards and Stage 1 cannot drift apart.
- Documented title-gate recipes live in `examples/title_gate_recipes.py` and are
  tested by `tests/test_title_recipes.py`. Change one, change the README.
