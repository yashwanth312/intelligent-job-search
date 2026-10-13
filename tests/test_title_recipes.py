"""The README title-gate recipes must behave as documented."""
import pytest

from examples.title_gate_recipes import RECIPES, apply_to_stage1
from screening.stage1 import title_passes

REJECTED_EVERYWHERE = ["Senior Staff Engineer", "Engineering Manager", "Marketing Coordinator",
                       "Summer Intern"]


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_every_recipe_title_passes_its_own_gate(name, monkeypatch):
    recipe = RECIPES[name]
    apply_to_stage1(recipe, monkeypatch)
    failed = [t for t in recipe["TARGET_TITLES"] if not title_passes(t)]
    assert not failed, f"{name}: searched titles the gate would drop: {failed}"


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_recipes_reject_seniority_and_off_domain_titles(name, monkeypatch):
    apply_to_stage1(RECIPES[name], monkeypatch)
    for title in REJECTED_EVERYWHERE:
        assert not title_passes(title), (name, title)


@pytest.mark.parametrize("title,expected", [
    ("Site Reliability Engineer", True),
    ("Platform Engineer", True),
    ("Generative AI Engineer", True),
    ("ML Platform Engineer", True),
    ("Founding AI/ML Engineer, Agents", True),
    ("Windows Systems Administrator", True),
    ("Machine Learning Engineer", False),
    ("AI/ML Engineer", False),
    ("Identity Security Engineer", False),
    ("Software Engineer", False),
    ("Network Engineer", False),
])
def test_infra_and_ai_recipe_documented_behavior(title, expected, monkeypatch):
    apply_to_stage1(RECIPES["infra_and_ai"], monkeypatch)
    assert title_passes(title) is expected


def test_backend_recipe_admits_software_titles_and_drops_ml(monkeypatch):
    apply_to_stage1(RECIPES["backend_software"], monkeypatch)
    assert title_passes("Backend Engineer")
    assert title_passes("Full Stack Software Engineer")
    assert not title_passes("Machine Learning Engineer")


def test_data_recipe_keeps_data_engineers_not_scientists(monkeypatch):
    apply_to_stage1(RECIPES["data_engineering"], monkeypatch)
    assert title_passes("Data Engineer")
    assert title_passes("Analytics Engineer")
    assert not title_passes("Data Scientist")
