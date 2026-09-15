import pytest
import json
import threading
from screening.stage2 import Stage2Screen
from models.job import ScreeningVerdict


MOCK_CLAUDE_OUTPUT = json.dumps([
    {
        "fingerprint": "google||cloud engineer",
        "verdict": "APPLY",
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
        assert results[0]["verdict"] == "APPLY"
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


def test_default_apply_does_not_inject_no_h1b_history_flag():
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
    screened = Stage2Screen()._default_apply(job)
    assert "no_h1b_history" not in screened.risk_flags


def test_default_maybe_does_not_inject_no_h1b_history_flag():
    from models.job import RawJob
    from screening.stage2 import Stage2Screen

    job = RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        source="linkedin",
        h1b_sponsor_verified=False,
    )
    screened = Stage2Screen()._default_maybe(job)
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
        "verdict": "APPLY", "confidence": 4, "reasoning": "Good",
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
    assert len(result) == 2  # both jobs still in output (one APPLY, one MAYBE)


def test_screen_batch_carries_interview_likelihood_into_screened_job():
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "fingerprint": job.fingerprint,
        "verdict": "APPLY", "confidence": 4, "reasoning": "Good",
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
        "verdict": "APPLY", "confidence": 4, "reasoning": "Good",
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
    verdict as long as `index` round-trips correctly."""
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "index": 0,
        "fingerprint": "acme || cloud engineer  ",  # deliberately mismatched text
        "verdict": "APPLY", "confidence": 5, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=claude_result):
        result = screen.screen_batch([job])

    assert result[0].verdict == ScreeningVerdict.APPLY
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
        assert len(result) == 3  # all defaulted to MAYBE, no crash


def test_screen_batch_caps_reasoning_and_list_fields():
    from unittest.mock import patch
    from models.job import RawJob

    job = RawJob(title="Cloud Engineer", company="Acme", location="Remote",
                 url="https://a.com", source="linkedin")
    claude_result = [{
        "index": 0,
        "fingerprint": job.fingerprint,
        "verdict": "APPLY", "confidence": 4,
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
