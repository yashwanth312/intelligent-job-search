import pytest
from pathlib import Path
from unittest.mock import patch
from config import (
    TARGET_TITLES, LOCATIONS, EXCLUDE_TITLE_KEYWORDS,
    SALARY_FLOOR, SCREENING_CONFIDENCE_THRESHOLD,
    TITLE_DOMAIN_KEYWORDS, SCREENING_BATCH_SIZE,
)


class TestConfig:
    def test_target_titles_include_ai_roles(self):
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("mlops" in t for t in titles_lower)
        assert any("ai" in t for t in titles_lower)

    def test_target_titles_include_cloud_roles(self):
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("cloud" in t for t in titles_lower)
        assert any("devops" in t for t in titles_lower)

    def test_target_titles_cover_all_domains(self):
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("cloud" in t for t in titles_lower)
        assert any("devops" in t for t in titles_lower)
        assert any("security" in t for t in titles_lower)

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
