"""Quick dry-run: feed 2 dummy jobs directly into Stage 2 and print results."""
import sys
from models.job import RawJob
from screening.stage2 import Stage2Screen

JOBS = [
    RawJob(
        title="Backend Engineer",
        company="Anthropic",
        location="San Francisco, CA",
        url="https://example.com/job/1",
        source="dry-run",
        description=(
            "We are looking for a Backend Engineer to build scalable infrastructure "
            "for our AI systems. You will work on Python services, distributed systems, "
            "and cloud infrastructure (AWS). 3+ years experience required. "
            "H1B sponsorship available."
        ),
    ),
    RawJob(
        title="Senior Staff Principal Architect",
        company="SomeCorp",
        location="Dallas, TX",
        url="https://example.com/job/2",
        source="dry-run",
        description=(
            "15+ years required. Must be a US citizen or permanent resident. "
            "Lead a team of 50 engineers across 3 time zones. "
            "Requires extensive C++ and COBOL experience."
        ),
    ),
]

def main() -> None:
    screener = Stage2Screen(profile_path="profile.yaml")
    try:
        screener.validate_cli()
        print("OK: Claude CLI found\n")
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Screening {len(JOBS)} jobs via Stage 2...\n")
    results = screener.screen_batch(JOBS)

    if not results:
        print("FAIL: Stage 2 returned no results -- likely a CLI error. Check logs above.", file=sys.stderr)
        sys.exit(1)

    for job in results:
        print(f"{'='*60}")
        print(f"  {job.title} @ {job.company}")
        print(f"  Verdict:    {job.verdict.value}  (confidence {job.confidence}/5)")
        print(f"  Reasoning:  {job.reasoning}")
        if job.match_signals:
            print(f"  Signals:    {', '.join(job.match_signals)}")
        if job.risk_flags:
            print(f"  Risks:      {', '.join(job.risk_flags)}")
    print(f"{'='*60}")
    print(f"\nOK: Stage 2 working -- {len(results)}/{len(JOBS)} jobs returned verdicts.")

if __name__ == "__main__":
    main()
