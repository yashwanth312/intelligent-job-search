# tests/test_backfill.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from models.job import RawJob
from sources.backfill import backfill_descriptions, extract_description_from_html, fetch_description_from_url


def make_job(**kwargs) -> RawJob:
    defaults = {
        "title": "Cloud Engineer",
        "company": "TestCo",
        "location": "Remote",
        "description": None,
        "url": "https://jobs.example.com/cloud-engineer",
        "source": "linkedin",
    }
    defaults.update(kwargs)
    return RawJob(**defaults)


SAMPLE_HTML = """
<html>
<head><title>Cloud Engineer</title></head>
<body>
<nav>Site nav</nav>
<script>var x = 1;</script>
<style>.foo { color: red; }</style>
<div class="job-description">
  <h1>Cloud Engineer</h1>
  <p>We are looking for a cloud engineer with AWS and Kubernetes experience.</p>
  <p>Requirements: 2+ years, Python, Terraform.</p>
</div>
<footer>Copyright 2026</footer>
</body>
</html>
"""


class TestExtractDescription:
    def test_extracts_text_removes_scripts_and_nav(self):
        text = extract_description_from_html(SAMPLE_HTML)
        assert "cloud engineer" in text.lower()
        assert "aws" in text.lower()
        assert "var x" not in text  # script removed
        assert "Site nav" not in text  # nav removed
        assert "Copyright" not in text  # footer removed

    def test_returns_none_for_empty_html(self):
        assert extract_description_from_html("") is None
        assert extract_description_from_html("<html><body></body></html>") is None

    def test_returns_none_for_short_text(self):
        # Less than 50 chars of meaningful text = not a real description
        assert extract_description_from_html("<html><body><p>Hi</p></body></html>") is None


class TestBackfillDescriptions:
    @pytest.mark.asyncio
    async def test_skips_jobs_with_existing_description(self):
        jobs = [make_job(description="Already has a description")]
        result = await backfill_descriptions(jobs)
        assert result.skipped == 1
        assert result.filled == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_skips_jobs_with_no_url(self):
        jobs = [make_job(url="")]
        result = await backfill_descriptions(jobs)
        assert result.skipped == 1
        assert result.filled == 0

    @pytest.mark.asyncio
    async def test_fills_description_from_url(self):
        jobs = [make_job()]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=SAMPLE_HTML)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            result = await backfill_descriptions(jobs)

        assert result.filled == 1
        assert jobs[0].description is not None
        assert "cloud engineer" in jobs[0].description.lower()

    @pytest.mark.asyncio
    async def test_handles_http_error_gracefully(self):
        jobs = [make_job()]

        mock_resp = AsyncMock()
        mock_resp.status = 403
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            result = await backfill_descriptions(jobs)

        assert result.failed == 1
        assert jobs[0].description is None

    @pytest.mark.asyncio
    async def test_caps_description_length(self):
        long_text = "word " * 2000  # ~10000 chars
        long_html = f"<html><body><div>{long_text}</div></body></html>"
        jobs = [make_job()]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=long_html)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            result = await backfill_descriptions(jobs)

        assert result.filled == 1
        assert len(jobs[0].description) <= 15000


class TestFetchDescriptionFromUrl:
    @pytest.mark.asyncio
    async def test_returns_extracted_text(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=SAMPLE_HTML)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            text = await fetch_description_from_url("https://example.com/job")

        assert text is not None
        assert "cloud engineer" in text.lower()
