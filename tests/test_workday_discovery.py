"""Tests for Workday tenant discovery and yaml persistence."""
from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from sources.workday_discovery import extract_workday_tenant, save_new_companies


class TestExtractWorkdayTenant:
    def test_extract_standard_url(self):
        url = "https://microsoft.wd5.myworkdayjobs.com/External_Careers/job/Redmond/CE_JR1"
        result = extract_workday_tenant(url, "Microsoft")
        assert result == {
            "tenant": "microsoft",
            "wd_server": "wd5",
            "site": "External_Careers",
            "name": "Microsoft",
        }

    def test_extract_url_with_locale(self):
        url = "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/x"
        result = extract_workday_tenant(url, "Salesforce")
        assert result["tenant"] == "salesforce"
        assert result["wd_server"] == "wd12"
        assert result["site"] == "External_Career_Site"
        assert result["name"] == "Salesforce"

    def test_non_workday_url_returns_none(self):
        assert extract_workday_tenant("https://linkedin.com/jobs/view/123", "Co") is None

    def test_empty_string_returns_none(self):
        assert extract_workday_tenant("", "Co") is None

    def test_none_returns_none(self):
        assert extract_workday_tenant(None, "Co") is None

    def test_tenant_lowercased(self):
        url = "https://CrowdStrike.wd5.myworkdayjobs.com/CrowdStrikeCareers/job/x"
        result = extract_workday_tenant(url, "CrowdStrike")
        assert result["tenant"] == "crowdstrike"
        assert result["wd_server"] == "wd5"


class TestSaveNewCompanies:
    def _tmp_yaml(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_adds_new_company_to_empty_workday_section(self):
        path = self._tmp_yaml("greenhouse:\n  - token: anthropic\n    name: Anthropic\n")
        try:
            added = save_new_companies(
                [{"tenant": "crowdstrike", "wd_server": "wd5",
                  "site": "CrowdStrikeCareers", "name": "CrowdStrike"}],
                yaml_path=path,
            )
            assert added == 1
            with open(path) as f:
                data = yaml.safe_load(f)
            assert len(data["workday"]) == 1
            assert data["workday"][0]["tenant"] == "crowdstrike"
        finally:
            os.unlink(path)

    def test_skips_existing_tenant(self):
        path = self._tmp_yaml(
            "workday:\n  - tenant: microsoft\n    wd_server: wd5\n"
            "    site: External_Careers\n    name: Microsoft\n"
        )
        try:
            added = save_new_companies(
                [{"tenant": "microsoft", "wd_server": "wd5",
                  "site": "External_Careers", "name": "Microsoft"}],
                yaml_path=path,
            )
            assert added == 0
        finally:
            os.unlink(path)

    def test_deduplicates_within_input_list(self):
        path = self._tmp_yaml("")
        try:
            added = save_new_companies(
                [
                    {"tenant": "okta", "wd_server": "wd5", "site": "okta", "name": "Okta"},
                    {"tenant": "okta", "wd_server": "wd5", "site": "okta", "name": "Okta"},
                ],
                yaml_path=path,
            )
            assert added == 1
        finally:
            os.unlink(path)

    def test_empty_discoveries_returns_zero(self):
        path = self._tmp_yaml("")
        try:
            assert save_new_companies([], yaml_path=path) == 0
        finally:
            os.unlink(path)
