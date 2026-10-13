import pytest
from pathlib import Path
from unittest.mock import patch
from config import (
    TARGET_TITLES, LOCATIONS, EXCLUDE_TITLE_KEYWORDS,
    SALARY_FLOOR, DAILY_MIN_CONFIDENCE,
    TITLE_DOMAIN_KEYWORDS, SCREENING_BATCH_SIZE,
)


class TestConfig:
    def test_target_titles_are_a_nonempty_list_of_strings(self):
        assert TARGET_TITLES and all(isinstance(t, str) and t.strip() for t in TARGET_TITLES)

    def test_every_target_title_passes_the_title_gate(self):
        """A searched title that Stage 1 would drop is wasted scrape time."""
        from screening.stage1 import title_passes
        rejected = [t for t in TARGET_TITLES if not title_passes(t)]
        assert not rejected, f"TARGET_TITLES rejected by the title gate: {rejected}"

    def test_title_domain_keywords_are_lowercase_and_nonempty(self):
        assert TITLE_DOMAIN_KEYWORDS
        assert all(k == k.lower() for k in TITLE_DOMAIN_KEYWORDS)

    def test_optional_title_families_default_to_disabled(self):
        import config
        assert config.ML_TITLE_KEYWORDS == []
        assert config.IT_IDENTITY_TITLE_KEYWORDS == []

    def test_campus_funnels_are_excluded_but_junior_is_not(self):
        excl = [k.lower() for k in EXCLUDE_TITLE_KEYWORDS]
        assert "new grad" in excl
        assert "early career" in excl
        # Junior/associate/entry-level are the right level — never exclude them.
        assert "junior" not in excl
        assert "associate" not in excl
        assert "entry level" not in excl

    def test_industrial_and_work_auth_titles_are_excluded(self):
        excl = [k.lower() for k in EXCLUDE_TITLE_KEYWORDS]
        # "automation" and "systems" in TITLE_DOMAIN_KEYWORDS would otherwise
        # pull in plant-floor roles.
        for kw in ("technician", "manufacturing", "quality systems", "thermal"):
            assert kw in excl, kw
        # Staffing firms put work-authorization limits in the TITLE, where the
        # description-level patterns never see them.
        for kw in ("usc/gc", "green card", "clearance", "no c2c"):
            assert kw in excl, kw

    def test_default_titles_pass_and_seniority_fails(self):
        from screening.stage1 import title_passes as passes
        for title in ("Software Engineer", "Backend Engineer", "Junior DevOps Engineer",
                      "Cloud Engineer II", "Data Engineer"):
            assert passes(title), title
        for title in ("Senior Software Engineer", "Engineering Manager", "Staff Engineer",
                      "Software Engineering Intern"):
            assert not passes(title), title

    def test_ai_word_does_not_match_inside_other_words(self):
        import re
        domain = [re.compile(r"\b" + re.escape(k) + r"\b", re.I) for k in TITLE_DOMAIN_KEYWORDS]
        for title in ("Retail Sales Associate", "HTML Email Designer", "Email Marketing Specialist"):
            assert not any(rx.search(title) for rx in domain), title

    def test_locations_include_remote(self):
        assert "Remote" in LOCATIONS

    def test_salary_floor_is_nonnegative_and_off_by_default(self):
        assert SALARY_FLOOR >= 0
        assert SALARY_FLOOR == 0  # neutral default: no salary filtering

    def test_sponsorship_filter_is_off_by_default(self):
        from config import SPONSORSHIP_FILTER_ENABLED
        assert SPONSORSHIP_FILTER_ENABLED is False

    def test_screening_defaults(self):
        assert 1 <= DAILY_MIN_CONFIDENCE <= 5
        assert SCREENING_BATCH_SIZE >= 1

    def test_h1b_cache_ttl_exists(self):
        from config import H1B_CACHE_TTL_DAYS
        assert H1B_CACHE_TTL_DAYS == 30



class TestValidateRequiredConfig:
    def test_passes_when_all_set(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.touch()
        with patch("config.YOUR_NAME", "Test User"), \
             patch("config.YOUR_EMAIL", "test@example.com"), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(creds)):
            from config import validate_required_config
            validate_required_config()  # must not raise

    def test_fails_missing_name(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.touch()
        with patch("config.YOUR_NAME", ""), \
             patch("config.YOUR_EMAIL", "test@example.com"), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(creds)):
            from config import validate_required_config
            with pytest.raises(SystemExit) as exc:
                validate_required_config()
            assert "YOUR_NAME" in str(exc.value)

    def test_fails_missing_email(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.touch()
        with patch("config.YOUR_NAME", "Test User"), \
             patch("config.YOUR_EMAIL", ""), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(creds)):
            from config import validate_required_config
            with pytest.raises(SystemExit) as exc:
                validate_required_config()
            assert "YOUR_EMAIL" in str(exc.value)

    def test_fails_missing_creds_file(self, tmp_path):
        with patch("config.YOUR_NAME", "Test User"), \
             patch("config.YOUR_EMAIL", "test@example.com"), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(tmp_path / "nope.json")):
            from config import validate_required_config
            with pytest.raises(SystemExit) as exc:
                validate_required_config()
            assert "GOOGLE_SHEETS_CREDS_FILE" in str(exc.value)
