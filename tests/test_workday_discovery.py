"""Tests for Workday tenant discovery, candidate gating, and yaml persistence."""
from __future__ import annotations

import os
import tempfile

import yaml

from sources.workday_discovery import extract_workday_tenant, save_candidates


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

    def test_extract_url_with_uppercase_locale(self):
        url = "https://salesforce.wd12.myworkdayjobs.com/EN-US/External_Career_Site/job/x"
        result = extract_workday_tenant(url, "Salesforce")
        assert result is not None
        assert result["site"] == "External_Career_Site"


class TestSaveCandidates:
    """save_candidates() routes Workday discoveries to a staging file rather
    than appending directly to target_companies.yaml. Tests verify the gating
    rules (skip active, skip rejected, dedupe) and metadata tracking
    (first_seen, last_seen, n_seen).
    """

    def _tmp(self, content: str = "") -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.write(content)
        f.close()
        return f.name

    def _read(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f) or {}

    def test_adds_new_candidate_to_empty_file(self):
        candidates = self._tmp("")
        target = self._tmp("workday: []\n")
        rejected = self._tmp("rejected: []\n")
        try:
            queued, repeats = save_candidates(
                [{"tenant": "newco", "wd_server": "wd5",
                  "site": "Careers", "name": "New Co"}],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            )
            assert queued == 1 and repeats == 0
            data = self._read(candidates)
            assert len(data["candidates"]) == 1
            entry = data["candidates"][0]
            assert entry["tenant"] == "newco"
            assert entry["n_seen"] == 1
            assert entry["promotion_attempts"] == 0
            assert entry["first_seen"] == entry["last_seen"]
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)

    def test_repeat_sighting_increments_n_seen(self):
        candidates = self._tmp(
            "candidates:\n"
            "  - tenant: foo\n"
            "    name: Foo\n"
            "    wd_server: wd5\n"
            "    site: Careers\n"
            "    first_seen: 2026-04-01\n"
            "    last_seen: 2026-04-01\n"
            "    n_seen: 1\n"
            "    promotion_attempts: 0\n"
            "    last_attempt: null\n"
        )
        target = self._tmp("workday: []\n")
        rejected = self._tmp("rejected: []\n")
        try:
            queued, repeats = save_candidates(
                [{"tenant": "foo", "wd_server": "wd5",
                  "site": "Careers", "name": "Foo"}],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            )
            assert queued == 0 and repeats == 1
            data = self._read(candidates)
            assert data["candidates"][0]["n_seen"] == 2
            # PyYAML auto-parses ISO dates to date objects; compare as strings.
            assert str(data["candidates"][0]["last_seen"]) != "2026-04-01"
            # first_seen MUST NOT change on repeat
            assert str(data["candidates"][0]["first_seen"]) == "2026-04-01"
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)

    def test_skips_tenants_already_active(self):
        candidates = self._tmp("")
        target = self._tmp(
            "workday:\n"
            "  - tenant: nvidia\n"
            "    wd_server: wd5\n"
            "    site: NVIDIAExternalCareerSite\n"
            "    name: NVIDIA\n"
        )
        rejected = self._tmp("rejected: []\n")
        try:
            queued, repeats = save_candidates(
                [{"tenant": "nvidia", "wd_server": "wd5",
                  "site": "NVIDIAExternalCareerSite", "name": "NVIDIA"}],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            )
            assert queued == 0 and repeats == 0
            data = self._read(candidates)
            assert not data.get("candidates")
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)

    def test_skips_tenants_already_rejected(self):
        candidates = self._tmp("")
        target = self._tmp("workday: []\n")
        rejected = self._tmp(
            "rejected:\n"
            "  - tenant: bannerhealth\n"
            "    name: Banner Health\n"
            "    reason: industry_mismatch\n"
            "    rejected_on: 2026-04-29\n"
        )
        try:
            queued, repeats = save_candidates(
                [{"tenant": "bannerhealth", "wd_server": "wd108",
                  "site": "Careers", "name": "Banner Health"}],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            )
            assert queued == 0 and repeats == 0
            data = self._read(candidates)
            assert not data.get("candidates")
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)

    def test_dedupes_within_input_batch(self):
        candidates = self._tmp("")
        target = self._tmp("workday: []\n")
        rejected = self._tmp("rejected: []\n")
        try:
            queued, repeats = save_candidates(
                [
                    {"tenant": "okta", "wd_server": "wd5",
                     "site": "Okta", "name": "Okta"},
                    {"tenant": "okta", "wd_server": "wd5",
                     "site": "Okta", "name": "Okta"},
                ],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            )
            assert queued == 1 and repeats == 0
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)

    def test_empty_discoveries_returns_zero_zero(self):
        candidates = self._tmp("")
        target = self._tmp("workday: []\n")
        rejected = self._tmp("rejected: []\n")
        try:
            assert save_candidates(
                [],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            ) == (0, 0)
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)

    def test_missing_files_are_safe(self):
        """All three yaml paths missing should not crash; new candidate is
        written to a fresh file."""
        candidates = self._tmp("")
        os.unlink(candidates)  # candidates file does not exist yet
        try:
            queued, repeats = save_candidates(
                [{"tenant": "newco", "wd_server": "wd5",
                  "site": "Careers", "name": "New Co"}],
                candidates_yaml_path=candidates,
                target_yaml_path="/nonexistent/target.yaml",
                rejected_yaml_path="/nonexistent/rejected.yaml",
            )
            assert queued == 1
            assert os.path.exists(candidates)
        finally:
            if os.path.exists(candidates):
                os.unlink(candidates)

    def test_malformed_discovery_skipped(self):
        candidates = self._tmp("")
        target = self._tmp("workday: []\n")
        rejected = self._tmp("rejected: []\n")
        try:
            queued, repeats = save_candidates(
                [
                    {"tenant": "valid", "wd_server": "wd5",
                     "site": "Careers", "name": "Valid"},
                    {"tenant": "missing_fields"},  # incomplete -> dropped
                ],
                candidates_yaml_path=candidates,
                target_yaml_path=target,
                rejected_yaml_path=rejected,
            )
            assert queued == 1
            data = self._read(candidates)
            tenants = {c["tenant"] for c in data["candidates"]}
            assert tenants == {"valid"}
        finally:
            for p in (candidates, target, rejected):
                os.unlink(p)
