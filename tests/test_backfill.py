# tests/test_backfill.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sources.backfill import extract_description_from_html, fetch_description_from_url


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
