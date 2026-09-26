import pytest
from models.job import RawJob
from screening.stage1 import Stage1Filter, FilterResult


def make_job(**kwargs) -> RawJob:
    defaults = {
        "title": "Cloud Engineer",
        "company": "Google",
        "location": "San Francisco, CA",
        "description": "We need a cloud engineer with AWS and Kubernetes experience. 2+ years preferred.",
        "url": "https://example.com",
        "source": "greenhouse-google",
    }
    defaults.update(kwargs)
    return RawJob(**defaults)


class TestStage1Filter:
    def test_good_job_passes(self):
        f = Stage1Filter()
        result = f.filter_job(make_job())
        assert result.passed is True

    def test_rejects_india_location(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(location="Bangalore, Karnataka, India"))
        assert result.passed is False
        assert result.stage == "stage1_location"

    @pytest.mark.parametrize("location", [
        "Taipei",                      # Taiwan — previously uncovered
        "Manila, Philippines",         # Philippines — previously uncovered
        "Riyadh - MSO",                # decoded Workday URL slug format
        "Romania - Bucharest",
        "Vietnam, Ho_Chi_Minh_City",
        "Malaysia, Penang",
    ])
    def test_rejects_previously_uncovered_non_us_locations(self, location):
        f = Stage1Filter()
        result = f.filter_job(make_job(location=location))
        assert result.passed is False
        assert result.stage == "stage1_location"

    @pytest.mark.parametrize("location", [
        "Vienna, VA",     # DC-metro suburb — collides with Vienna, Austria
        "Melbourne, FL",  # Space Coast aerospace hub — collides with Melbourne, AU
        "Rome, GA",
    ])
    def test_us_cities_sharing_names_with_foreign_cities_still_pass(self, location):
        f = Stage1Filter()
        result = f.filter_job(make_job(location=location))
        assert result.passed is True

    def test_rejects_senior_title(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(title="Senior Cloud Engineer"))
        assert result.passed is False
        assert "senior" in result.reason.lower()

    def test_rejects_clearance_required(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description="Must have TS/SCI clearance"))
        assert result.passed is False
        assert "clearance" in result.reason.lower() or "ts/sci" in result.reason.lower()

    def test_no_sponsorship_follows_toggle(self):
        """A 'we don't sponsor' JD is kept while the sponsorship filter is off
        (candidate is work-authorized) and rejected only when it is on. The
        effective hard-stop list in stage1 is built from the same flag, so the
        two stay consistent."""
        from config import SPONSORSHIP_FILTER_ENABLED
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="We will not sponsor visas. AWS and Kubernetes required."
        ))
        if SPONSORSHIP_FILTER_ENABLED:
            assert result.passed is False
        else:
            assert result.passed is True

    def test_still_rejects_citizenship_requirement(self):
        """US-citizenship requirements are always rejected, independent of the
        sponsorship toggle — an F1 candidate cannot take a citizens-only role."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="Must be a US citizen. AWS and Kubernetes required."
        ))
        assert result.passed is False

    def test_rejects_5_plus_years(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description="Requires 5+ years of experience"))
        assert result.passed is False

    def test_rejects_markdown_escaped_hyphen_range(self):
        """jobspy renders LinkedIn/Indeed descriptions as Markdown, which
        backslash-escapes hyphens: "4\\-6 years" instead of "4-6 years"."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="AWS and Kubernetes required. 4\\-6 years of experience in site reliability."
        ))
        assert result.passed is False
        assert "yoe" in result.reason.lower()

    def test_rejects_bare_years_of_experience_no_qualifier(self):
        """'6 years of experience' with no '+'/'minimum'/'at least' qualifier
        was previously uncovered by any pattern."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="AWS and Kubernetes required. 6 years of experience with cloud native technologies."
        ))
        assert result.passed is False
        assert "yoe" in result.reason.lower()

    def test_rejects_range_lower_bound_above_threshold(self):
        """A numeric combo not in the old hardcoded list (e.g. 6-9) must
        still be caught now that ranges are matched generally."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="AWS and Kubernetes required. 6-9 years of relevant experience needed."
        ))
        assert result.passed is False

    def test_keeps_low_end_range_spanning_below_threshold(self):
        """"2-5 years" starts below MIN_YOE_HARD_STOP, so it's not a hard
        4+ requirement — must not be hard-stopped."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="AWS and Kubernetes required. 2-5 years of experience is fine."
        ))
        assert result.passed is True

    def test_keeps_company_history_years_mention(self):
        """"with over 26 years of experience, we..." describes the company,
        not a job requirement — must not be hard-stopped."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description=(
                "AWS and Kubernetes required. With over 26 years of experience, "
                "we consistently deliver great cloud infrastructure."
            )
        ))
        assert result.passed is True

    def test_keeps_range_with_dropped_dash(self):
        """"3–5 years" scraped as "35 years" is a 3-year lower bound, not 35."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description=(
                "AWS and Kubernetes cloud infrastructure engineer. "
                "35 years of hands-on experience delivering production AI solutions."
            )
        ))
        assert result.passed is True

    def test_rejects_range_with_dropped_dash_above_threshold(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="AWS and Kubernetes cloud infrastructure engineer. 58 years of experience."
        ))
        assert result.passed is False

    def test_keeps_preferred_low_years(self):
        """2+ years preferred stays under the hard-stop threshold."""
        f = Stage1Filter()
        result = f.filter_job(make_job(
            description="AWS and Kubernetes cloud infrastructure engineer. 2+ years preferred."
        ))
        assert result.passed is True

    def test_rejects_empty_description(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description=None))
        assert result.passed is False
        assert "no description" in result.reason.lower()

    def test_rejects_below_salary_floor(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(salary_max=50000))
        assert result.passed is False

    def test_rejects_missing_domain_keywords(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(
            title="Marketing Coordinator",
            description="Looking for a marketing person.",
        ))
        assert result.passed is False

    def test_batch_filter(self):
        f = Stage1Filter()
        jobs = [
            make_job(title="Cloud Engineer"),
            make_job(title="Senior Principal Architect"),
            make_job(title="DevOps Engineer"),
        ]
        passed, rejected = f.filter_batch(jobs)
        assert len(passed) == 2
        assert len(rejected) == 1

    @pytest.mark.parametrize("title", [
        "System Administrator",
        "Windows Server Engineer",
        "IAM Engineer",
        "Entra ID Engineer",
        "Endpoint Engineer (Intune & FlexApp)",
        "M365 Engineer",
        "VMware (ESXi) Engineer",
    ])
    def test_it_identity_titles_pass_title_gate(self, title):
        f = Stage1Filter()
        result = f.filter_job(make_job(
            title=title,
            description="Manage Active Directory, Windows Server and Intune with PowerShell.",
        ))
        assert result.stage != "stage1_title_domain", result.reason
        assert result.passed is True

    @pytest.mark.parametrize("title", [
        "Identity Security Engineer",
        "Endpoint Security Engineer",
        "M365 Security Engineer",
        "Endpoint Threat Hunting Consultant",
    ])
    def test_it_identity_word_does_not_admit_security_titles(self, title):
        f = Stage1Filter()
        result = f.filter_job(make_job(title=title))
        assert result.passed is False
        assert result.stage == "stage1_title_domain"

    def test_bare_administrator_is_not_a_domain_word(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(title="Benefits Administrator"))
        assert result.stage == "stage1_title_domain"

    def test_title_only_gate_admits_it_identity_titles(self):
        f = Stage1Filter()
        passed, rejected = f.filter_titles_only([
            make_job(title="Windows System Administrator", description=None),
            make_job(title="Identity Security Engineer", description=None),
        ])
        assert [j.title for j in passed] == ["Windows System Administrator"]
        assert len(rejected) == 1
