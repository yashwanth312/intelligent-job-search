import pytest
from sources.hackernews import HackerNewsAdapter, parse_hn_comment


class TestHNParsing:
    def test_parse_standard_format(self):
        comment = "Anthropic | Cloud Engineer | San Francisco, CA | Remote OK\n\nWe are building..."
        result = parse_hn_comment(comment, "https://news.ycombinator.com/item?id=123")
        assert result is not None
        assert result.company == "Anthropic"
        assert result.title == "Cloud Engineer"
        assert "San Francisco" in result.location

    def test_parse_with_url(self):
        comment = "Google | DevOps Engineer | NYC | https://careers.google.com/jobs/123"
        result = parse_hn_comment(comment, "https://news.ycombinator.com/item?id=456")
        assert result is not None
        assert result.company == "Google"

    def test_skip_non_job_comment(self):
        comment = "This is just a regular comment about the thread."
        result = parse_hn_comment(comment, "https://news.ycombinator.com/item?id=789")
        assert result is None

    def test_skip_empty_comment(self):
        result = parse_hn_comment("", "https://news.ycombinator.com/item?id=0")
        assert result is None
