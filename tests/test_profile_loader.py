import pytest
import yaml
from pathlib import Path
from models.profile import Profile


class TestProfileLoader:
    def test_load_profile_yaml(self, tmp_path):
        profile_data = {
            "personal": {
                "name": "Test User",
                "email": "test@test.com",
                "phone": "123",
                "location": "NYC",
                "visa": "F1 OPT",
            },
            "education": [{"school": "MIT", "degree": "MS CS", "gpa": "4.0", "graduation": "2025"}],
            "experiences": [{
                "company": "TestCo",
                "location": "NYC",
                "period": "2024-present",
                "framings": {"devops": {"title": "DevOps Eng", "bullets": ["Did stuff"]}},
                "raw_context": "Built infra from scratch",
            }],
            "projects": [{"name": "TestProject", "raw_context": "A test project"}],
            "certifications": [{"name": "Security+", "issuer": "CompTIA", "status": "Active"}],
            "training": ["Docker", "K8s"],
            "skills": {"cloud": ["AWS", "GCP"]},
        }
        path = tmp_path / "profile.yaml"
        path.write_text(yaml.dump(profile_data, default_flow_style=False))

        with open(path) as f:
            data = yaml.safe_load(f)
        profile = Profile(**data)
        assert profile.personal.name == "Test User"
        assert len(profile.experiences) == 1
        assert profile.experiences[0].company == "TestCo"
