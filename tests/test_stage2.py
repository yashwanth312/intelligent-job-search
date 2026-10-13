import pytest
import json
import threading
from screening.stage2 import Stage2Screen


MOCK_CLAUDE_OUTPUT = json.dumps([
    {
        "fingerprint": "google||cloud engineer",
        "confidence": 4,
        "reasoning": "Strong match: AWS + K8s experience aligns well",
        "match_signals": ["AWS", "Kubernetes", "Terraform"],
        "risk_flags": [],
        "suggested_angle": "AI Infrastructure",
        "interview_likelihood": 55,
    }
])


class TestStage2Screen:
    def test_parse_claude_response(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        results = screen._parse_response(MOCK_CLAUDE_OUTPUT)
        assert len(results) == 1
        assert results[0]["confidence"] == 4
        assert results[0]["interview_likelihood"] == 55

    def test_parse_handles_invalid_json(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        results = screen._parse_response("not valid json at all")
        assert results == []

    def test_parse_handles_json_in_markdown(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        wrapped = f"```json\n{MOCK_CLAUDE_OUTPUT}\n```"
        results = screen._parse_response(wrapped)
        assert len(results) == 1


def test_unscored_job_does_not_inject_no_h1b_history_flag():
    """no_h1b_history was a risk flag; sponsorship now has its own column."""
    from models.job import RawJob
    from screening.stage2 import Stage2Screen

    job = RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        source="linkedin",
        h1b_sponsor_verified=False,  # would have triggered the flag previously
    )
    screened = Stage2Screen()._unscored(job)
    assert "no_h1b_history" not in screened.risk_flags


def test_screen_batch_warns_on_partial_response():
    """When Claude returns fewer jobs than submitted, a WARNING is logged naming the missing jobs."""
    from unittest.mock import patch
    from models.job import RawJob

    jobs = [
        RawJob(title="Cloud Engineer", company="Acme", location="Remote",
               url="https://a.com", source="linkedin"),
        RawJob(title="DevOps Engineer", company="Beta", location="Remote",
               url="https://b.com", source="linkedin"),
    ]
    # Only the first job is returned by Claude
    partial = [{
        "index": 0,
        "fingerprint": jobs[0].fingerprint,
        "confidence": 4, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=partial), \
         patch.object(screen, "_build_system_prompt", return_value="system"), \
         patch("screening.stage2.logger") as mock_log:
        result = screen.screen_batch(jobs)

    assert mock_log.warning.call_count >= 1
    msg = mock_log.warning.call_args[0][0]
    assert "1/2 returned" in msg
    assert "DevOps Engineer" in msg
    assert len(result) == 2  # both jobs still in output (one scored, one unscored)
    assert result[1].confidence is None


def test_screen_batch_carries_interview_likelihood_into_screened_job():
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "fingerprint": job.fingerprint,
        "confidence": 4, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
        "interview_likelihood": 62,
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=claude_result):
        result = screen.screen_batch([job])

    assert result[0].interview_likelihood == 62


def test_screen_batch_defaults_interview_likelihood_to_none_when_absent():
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "fingerprint": job.fingerprint,
        "confidence": 4, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=claude_result):
        result = screen.screen_batch([job])

    assert result[0].interview_likelihood is None


class TestStage2SystemPromptSplit:
    def test_system_prompt_contains_profile_not_jobs_section(self, tmp_path):
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        screen = Stage2Screen(profile_path=str(profile))

        sys_prompt = screen._build_system_prompt()

        assert "Test Candidate" in sys_prompt
        assert "{{profile}}" not in sys_prompt
        assert "{{sponsorship_policy}}" not in sys_prompt
        assert "## Jobs to Screen" not in sys_prompt

    def test_system_prompt_is_memoized(self, tmp_path):
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        screen = Stage2Screen(profile_path=str(profile))
        assert screen._build_system_prompt() is screen._build_system_prompt()

    def test_screen_one_batch_passes_system_prompt_and_indexed_jobs(self, tmp_path):
        from unittest.mock import patch
        from models.job import RawJob

        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        screen = Stage2Screen(profile_path=str(profile))
        jobs = [
            RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                   url="https://a.com", source="linkedin"),
            RawJob(title="DevOps Engineer", company="Beta", location="Remote",
                   url="https://b.com", source="linkedin"),
        ]

        with patch("screening.stage2.run_claude", return_value=None) as mock_run:
            screen._screen_one_batch(jobs)

        _args, kwargs = mock_run.call_args
        assert "Test Candidate" in kwargs["system_prompt"]
        dynamic_prompt = mock_run.call_args.args[0]
        assert "Test Candidate" not in dynamic_prompt
        assert '"index": 0' in dynamic_prompt
        assert '"index": 1' in dynamic_prompt

    def test_each_job_carries_the_resume_generators_project_picks(self, tmp_path):
        """Stage 2 scores against the 3 projects the resume will actually
        carry: the same deterministic picks ResumeEngine makes."""
        import json
        import yaml
        from pathlib import Path
        from unittest.mock import patch
        from models.job import RawJob
        from generation.portfolio import parse_spec
        from generation.resume_engine import ResumeEngine

        specs = sorted((Path(__file__).resolve().parent.parent
                        / "examples" / "portfolio_catalog").glob("[0-9][0-9]-*.md"))
        catalog = []
        for spec in specs:
            meta, _ = parse_spec(spec)
            catalog.append({"id": meta["id"], "name": meta["name"], "spec": str(spec)})
        profile = tmp_path / "profile.yaml"
        profile.write_text(yaml.safe_dump({
            "personal": {"name": "Test Candidate", "email": "t@example.com",
                         "phone": "1", "location": "Austin, TX"},
            "portfolio_catalog": catalog,
        }), encoding="utf-8")

        desc = ("Requirements: administer Active Directory, Entra ID and Intune; "
                "PowerShell automation; Microsoft 365 tenant management.")
        job = RawJob(title="Windows Systems Administrator", company="Acme",
                     location="Remote", url="https://a.com", source="linkedin",
                     description=desc)
        screen = Stage2Screen(profile_path=str(profile))

        with patch("screening.stage2.run_claude", return_value=None) as mock_run:
            screen._screen_one_batch([job])

        dynamic_prompt = mock_run.call_args.args[0]
        payload = json.loads(dynamic_prompt.split("## Jobs to Screen", 1)[1]
                             .split("Return ONLY", 1)[0])
        sent = [p["name"] for p in payload[0]["resume_projects"]]
        expected = ResumeEngine(str(profile)).select_projects(job.title, desc).names
        assert sent == expected
        assert "HybridID" in sent
        # Catalog projects are presented exactly like built ones: no
        # built/portfolio label for the model to discount.
        assert all(set(p) == {"name", "covers"} for p in payload[0]["resume_projects"])

    def test_screen_one_batch_passes_thinking_budget(self, tmp_path):
        """Stage 2 caps rather than disables thinking — see
        config.STAGE2_THINKING_BUDGET_TOKENS."""
        from unittest.mock import patch
        from models.job import RawJob
        from config import STAGE2_THINKING_BUDGET_TOKENS

        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        screen = Stage2Screen(profile_path=str(profile))
        job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                     url="https://a.com", source="linkedin")

        with patch("screening.stage2.run_claude", return_value=None) as mock_run:
            screen._screen_one_batch([job])

        _args, kwargs = mock_run.call_args
        assert kwargs["thinking_budget_tokens"] == STAGE2_THINKING_BUDGET_TOKENS
        assert kwargs.get("disable_thinking", False) is False


def test_screen_batch_keys_by_index_when_fingerprint_text_mismatches():
    """Claude echoing a slightly-off fingerprint string must not lose the
    score as long as `index` round-trips correctly."""
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "index": 0,
        "fingerprint": "acme || cloud engineer  ",  # deliberately mismatched text
        "confidence": 5, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=claude_result):
        result = screen.screen_batch([job])

    assert result[0].confidence == 5


class TestScreenBatchConcurrency:
    """screen_batch() runs SCREENING_BATCH_SIZE-sized batches concurrently
    (config.SCREENING_MAX_WORKERS) instead of sequentially — added 2026-09-09
    once scraping/generation got fast enough that Stage 2 became the dominant
    chunk of run time."""

    def _jobs(self, n: int) -> list:
        from models.job import RawJob
        return [
            RawJob(title=f"Job {i}", company=f"Co{i}", location="Remote",
                   url=f"https://x.com/{i}", source="linkedin")
            for i in range(n)
        ]

    def test_batches_actually_overlap_in_wall_clock_time(self):
        """Two batches that each sleep 0.3s must finish in ~0.3s total, not 0.6s,
        proving they ran concurrently rather than sequentially."""
        import time
        from unittest.mock import patch

        jobs = self._jobs(16)  # SCREENING_BATCH_SIZE=8 -> 2 batches
        screen = Stage2Screen(profile_path="profile.yaml")

        def slow_screen(batch):
            time.sleep(0.3)
            return [
                {"index": i, "fingerprint": j.fingerprint, "verdict": "APPLY",
                 "confidence": 3, "reasoning": "ok", "match_signals": [],
                 "risk_flags": [], "suggested_angle": ""}
                for i, j in enumerate(batch)
            ]

        with patch.object(screen, "_screen_one_batch", side_effect=slow_screen):
            t0 = time.time()
            result = screen.screen_batch(jobs)
            elapsed = time.time() - t0

        assert len(result) == 16
        assert elapsed < 0.55  # well under 2x0.3s serial time

    def test_results_preserve_original_job_order_despite_completion_order(self):
        """The batch that finishes LAST in wall-clock time is job order 0-7 —
        output must still come back in original order, not completion order."""
        import time
        from unittest.mock import patch

        jobs = self._jobs(16)
        screen = Stage2Screen(profile_path="profile.yaml")

        def screen_with_variable_delay(batch):
            # First batch (contains "Job 0") finishes LAST.
            time.sleep(0.3 if batch[0].title == "Job 0" else 0.05)
            return [
                {"index": i, "fingerprint": j.fingerprint, "verdict": "APPLY",
                 "confidence": 3, "reasoning": "ok", "match_signals": [],
                 "risk_flags": [], "suggested_angle": ""}
                for i, j in enumerate(batch)
            ]

        with patch.object(screen, "_screen_one_batch", side_effect=screen_with_variable_delay):
            result = screen.screen_batch(jobs)

        assert [j.title for j in result] == [f"Job {i}" for i in range(16)]

    def test_progress_callback_fires_once_per_batch_thread_safely(self):
        from unittest.mock import patch

        jobs = self._jobs(24)  # 3 batches
        screen = Stage2Screen(profile_path="profile.yaml")
        calls = []

        def fake_screen(batch):
            return [
                {"index": i, "fingerprint": j.fingerprint, "verdict": "APPLY",
                 "confidence": 3, "reasoning": "ok", "match_signals": [],
                 "risk_flags": [], "suggested_angle": ""}
                for i, j in enumerate(batch)
            ]

        with patch.object(screen, "_screen_one_batch", side_effect=fake_screen):
            screen.screen_batch(jobs, on_progress=lambda n: calls.append(n))

        assert len(calls) == 3

    def test_empty_job_list_returns_empty_without_spawning_threads(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        assert screen.screen_batch([]) == []

    def test_seeds_cache_with_first_batch_before_fanning_out_the_rest(self):
        """When batches > max_workers, batch 0 must run to completion before
        any other batch starts — this is what lets the server-side
        system-prompt cache populate from a single write instead of
        `max_workers` concurrent misses."""
        import time
        from unittest.mock import patch

        jobs = self._jobs(24)  # SCREENING_BATCH_SIZE=8 -> 3 batches
        screen = Stage2Screen(profile_path="profile.yaml")
        order = []
        lock = threading.Lock()

        def tracked_screen(batch):
            with lock:
                order.append(("start", batch[0].title))
            time.sleep(0.05)
            with lock:
                order.append(("finish", batch[0].title))
            return [
                {"index": i, "fingerprint": j.fingerprint, "verdict": "APPLY",
                 "confidence": 3, "reasoning": "ok", "match_signals": [],
                 "risk_flags": [], "suggested_angle": ""}
                for i, j in enumerate(batch)
            ]

        with patch.object(screen, "_screen_one_batch", side_effect=tracked_screen):
            result = screen.screen_batch(jobs, max_workers=2)

        assert len(result) == 24
        # batch 0 (Job 0) must both start and finish before anything else starts
        assert order[0] == ("start", "Job 0")
        assert order[1] == ("finish", "Job 0")

    def test_seeding_skipped_when_batches_fit_in_one_wave(self):
        """With batches <= max_workers there's no second wave to benefit
        from seeding, so all batches must still start concurrently (no
        serial delay added) — same contract as
        test_batches_actually_overlap_in_wall_clock_time."""
        import time
        from unittest.mock import patch

        jobs = self._jobs(16)  # 2 batches, well under max_workers=5
        screen = Stage2Screen(profile_path="profile.yaml")

        def slow_screen(batch):
            time.sleep(0.3)
            return [
                {"index": i, "fingerprint": j.fingerprint, "verdict": "APPLY",
                 "confidence": 3, "reasoning": "ok", "match_signals": [],
                 "risk_flags": [], "suggested_angle": ""}
                for i, j in enumerate(batch)
            ]

        with patch.object(screen, "_screen_one_batch", side_effect=slow_screen):
            t0 = time.time()
            screen.screen_batch(jobs)
            elapsed = time.time() - t0

        assert elapsed < 0.55  # both batches ran concurrently, not seeded serially

    def test_worker_count_never_exceeds_batch_count(self):
        """A single batch must not error out asking ThreadPoolExecutor for
        SCREENING_MAX_WORKERS=5 workers when there's only 1 batch."""
        from unittest.mock import patch

        jobs = self._jobs(3)  # 1 batch
        screen = Stage2Screen(profile_path="profile.yaml")
        with patch.object(screen, "_screen_one_batch", return_value=[]):
            result = screen.screen_batch(jobs)  # must not raise
        assert len(result) == 3  # all unscored, no crash
        assert all(j.confidence is None for j in result)


def test_screen_batch_caps_reasoning_and_list_fields():
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "index": 0,
        "fingerprint": job.fingerprint,
        "confidence": 4,
        "reasoning": "x" * 1000,
        "match_signals": [f"signal{i}" for i in range(20)],
        "risk_flags": [f"flag{i}" for i in range(20)],
        "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=claude_result):
        result = screen.screen_batch([job])

    assert len(result[0].reasoning) == 300
    assert len(result[0].match_signals) == 5
    assert len(result[0].risk_flags) == 5


class TestNoVerdictsHonestScoring:
    """2026-10-03: verdicts removed — confidence, interview score and risk
    flags are the whole output; nothing is inflated."""

    def _job(self):
        from models.job import RawJob
        return RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                      url="https://a.com", source="linkedin")

    def test_unreturned_job_is_unscored_not_defaulted(self):
        from unittest.mock import patch
        from rescreen import FAILED_PREFIX
        screen = Stage2Screen(profile_path="profile.yaml")
        with patch.object(screen, "_screen_one_batch", return_value=[]):
            [job] = screen.screen_batch([self._job()])
        assert job.confidence is None
        assert job.interview_likelihood is None
        # rescreen.py --failed-only finds failures by this prefix on the Daily tab
        assert job.reasoning.startswith(FAILED_PREFIX)

    def test_missing_confidence_is_unscored_not_three(self):
        from unittest.mock import patch
        screen = Stage2Screen(profile_path="profile.yaml")
        result = [{"index": 0, "reasoning": "x", "interview_likelihood": 40}]
        with patch.object(screen, "_screen_one_batch", return_value=result):
            [job] = screen.screen_batch([self._job()])
        assert job.confidence is None

    def test_prompt_has_no_verdicts_or_inflation_rules(self):
        from screening.stage2 import PROMPT_PATH
        text = PROMPT_PATH.read_text(encoding="utf-8")
        assert '"verdict"' not in text
        for banned in ("APPLY", "MAYBE", "SKIP", "outweighs calendar YOE",
                       "raise confidence"):
            assert banned not in text, banned
        assert "{{jobs_json}}" in text and "{{sponsorship_policy}}" in text

    def test_sponsorship_policy_uses_confidence_not_verdict(self):
        from screening.stage2 import _SPONSORSHIP_POLICY_ON
        assert "SKIP" not in _SPONSORSHIP_POLICY_ON
        assert "confidence MUST be 1" in _SPONSORSHIP_POLICY_ON

    def test_prompt_treats_catalog_projects_as_built_evidence(self):
        """User decision 2026-10-03: catalog projects count as built work for
        confidence and interview scoring — but, like any project, never as
        years of professional experience."""
        from screening.stage2 import PROMPT_PATH
        text = PROMPT_PATH.read_text(encoding="utf-8")
        assert "zero credit" not in text
        assert "Treat every catalog project as built" in text
        assert "do not count portfolio projects" not in text
        assert "do not count as years of experience" in text

