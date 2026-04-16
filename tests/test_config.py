import pytest
from config import (
    TARGET_TITLES, SEARCH_QUERIES, LOCATIONS, EXCLUDE_TITLE_KEYWORDS,
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

    def test_locations_include_remote(self):
        assert "Remote" in LOCATIONS

    def test_salary_floor(self):
        assert SALARY_FLOOR >= 70000

    def test_screening_defaults(self):
        assert SCREENING_CONFIDENCE_THRESHOLD >= 1
        assert SCREENING_BATCH_SIZE >= 1

    def test_search_queries_are_broad_terms(self):
        assert len(SEARCH_QUERIES) < len(TARGET_TITLES)
        assert len(SEARCH_QUERIES) >= 5
        queries_lower = [q.lower() for q in SEARCH_QUERIES]
        assert any("cloud" in q for q in queries_lower)
        assert any("devops" in q for q in queries_lower)
        assert any("security" in q for q in queries_lower)
