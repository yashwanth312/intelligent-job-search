import pytest
from pathlib import Path
from unittest.mock import patch
from config import (
    TARGET_TITLES, LOCATIONS, EXCLUDE_TITLE_KEYWORDS,
    SALARY_FLOOR, SCREENING_CONFIDENCE_THRESHOLD,
    TITLE_DOMAIN_KEYWORDS, SCREENING_BATCH_SIZE,
)


class TestConfig:
    def test_target_titles_cover_the_converting_infra_domains(self):
        titles_lower = [t.lower() for t in TARGET_TITLES]
        for expected in (
            "cloud engineer",
            "infrastructure engineer",
            "systems engineer",
            "site reliability engineer",
            "platform engineer",
            "devops engineer",
        ):
            assert any(expected in t for t in titles_lower), expected

    def test_target_titles_include_systems_development_engineer(self):
        # The Amazon callback came from this exact title and the old list
        # never searched for it.
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("systems development engineer" in t for t in titles_lower)

    def test_target_titles_exclude_standalone_security_and_ai(self):
        # 0/73 on Security Analyst and 0/238 on AI/ML over 1,003 applications.
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert not any("security" in t for t in titles_lower)
        assert not any(t.startswith("ai") or " ai" in t for t in titles_lower)

    def test_mlops_is_the_only_ai_adjacent_title(self):
        # Kept because MLOps is infrastructure work in an under-supplied niche.
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("mlops" in t for t in titles_lower)

    def test_title_domain_keywords_require_infra_context_for_ai(self):
        kws = [k.lower() for k in TITLE_DOMAIN_KEYWORDS]
        # Bare "ai" and "security" must not be standalone passes any more.
        assert "ai" not in kws
        assert "security" not in kws
        # Infra vocabulary stays.
        for expected in ("cloud", "infrastructure", "systems", "platform", "sre"):
            assert expected in kws, expected

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

    def test_callback_titles_survive_the_title_gate(self):
        """The 7 titles that actually produced interviews must never be filtered."""
        import re
        domain = [re.compile(r"\b" + re.escape(k) + r"\b", re.I) for k in TITLE_DOMAIN_KEYWORDS]

        def passes(title: str) -> bool:
            low = title.lower()
            if any(kw in low for kw in EXCLUDE_TITLE_KEYWORDS):
                return False
            return any(rx.search(title) for rx in domain)

        for title in (
            "AWS Cloud Engineer",
            "Site Reliability Engineer II",
            "Software Security Engineer (Distributed Systems) MTS",
            "Systems Development Engineer, Devices Technologies",
            "Financial Connections TechOps Integration Reliability Engineer",
            "Applied Cloud and AI Engineer - Equities Cloud Platform Technology",
            "Core Infrastructure Engineer",
        ):
            assert passes(title), title

    def test_locations_include_remote(self):
        assert "Remote" in LOCATIONS

    def test_salary_floor(self):
        assert SALARY_FLOOR >= 70000

    def test_screening_defaults(self):
        assert SCREENING_CONFIDENCE_THRESHOLD >= 1
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
