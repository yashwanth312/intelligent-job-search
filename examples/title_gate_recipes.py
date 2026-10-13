"""Ready-to-paste title-gate recipes for config.py.

Each recipe is the set of config.py values that decide which job TITLES get
searched (TARGET_TITLES) and which survive Stage 1 (the keyword lists). Copy a
recipe's values over the matching names in config.py, then adjust.

The recipes are exercised by tests/test_title_recipes.py, so the examples in
README.md ("Tune the title gate") are known to behave as described.

How the gate works (screening/stage1.py -> title_passes):
  1. A title containing any EXCLUDE_TITLE_KEYWORDS word is dropped.
  2. If it contains an ML_TITLE_KEYWORDS word, it must ALSO contain a
     CORE_TITLE_KEYWORDS word or an ML_TITLE_LLM_EXEMPTIONS word.
  3. It must contain a TITLE_DOMAIN_KEYWORDS word (CORE + EXTRA), or else an
     IT_IDENTITY_TITLE_KEYWORDS word with no IT_IDENTITY_SECURITY_BLOCKERS word.
Matching is whole-word and case-insensitive.
"""

# ---------------------------------------------------------------------------
# 1. Infrastructure + AI engineering  (the strategy this project was tuned on)
#
# Derived from ~1,000 real applications: callbacks came only from
# cloud / SRE / systems-and-infrastructure roles. Pure AI/ML-modelling titles,
# generic software-engineer titles, network titles and security-analyst
# titles produced none, so they are kept out. AI *engineering* titles (LLMOps,
# GenAI platform work) stayed in because one of them sent an assessment.
# ---------------------------------------------------------------------------
INFRA_AND_AI = {
    "TARGET_TITLES": [
        "Cloud Engineer", "Cloud Infrastructure Engineer", "Infrastructure Engineer",
        "Systems Engineer", "Systems Development Engineer",
        "Site Reliability Engineer", "Platform Engineer",
        "Observability Engineer", "DevOps Engineer", "MLOps Engineer",
        "AI Engineer", "Generative AI Engineer", "Systems Administrator",
    ],
    "CORE_TITLE_KEYWORDS": [
        "cloud", "devops", "devsecops", "sre", "platform", "infrastructure",
        "reliability", "kubernetes", "observability", "systems",
        "mlops", "ml ops", "ml-ops",
        "aws", "gcp", "azure", "terraform", "k8s", "ci/cd",
        "docker", "jenkins", "ansible", "prometheus", "grafana", "helm", "vault",
        "automation", "linux",
    ],
    "EXTRA_TITLE_KEYWORDS": ["ai", "genai", "generative", "agentic", "llm", "llms", "llmops"],
    # "Machine Learning Engineer" / "AI/ML Engineer" are out unless the title also
    # names infrastructure or LLM/agent work ("ML Platform Engineer", "Founding
    # AI/ML Engineer, Agents").
    "ML_TITLE_KEYWORDS": ["ml", "machine learning", "deep learning"],
    "ML_TITLE_LLM_EXEMPTIONS": ["genai", "generative", "agentic", "agent", "agents",
                                "llm", "llms", "llmops"],
    # Sysadmin / identity / endpoint titles are admitted only when they carry no
    # security word ("Identity Security Engineer" stays out).
    "IT_IDENTITY_TITLE_KEYWORDS": [
        "systems administrator", "system administrator", "sysadmin",
        "windows", "active directory", "identity", "iam", "entra",
        "endpoint", "intune", "microsoft 365", "m365",
        "it infrastructure", "it engineer", "it systems",
        "vmware", "virtualization",
    ],
    "IT_IDENTITY_SECURITY_BLOCKERS": ["security", "cybersecurity", "cyber", "threat", "soc"],
    "REQUIRE_ONE_OF": [
        "aws", "gcp", "azure", "cloud", "kubernetes", "k8s", "terraform",
        "devops", "security", "iam", "sre", "platform", "infrastructure",
        "ci/cd", "docker", "jenkins", "github actions", "ansible",
        "prometheus", "grafana", "helm", "vault", "linux", "automation",
        "mlops", "ai", "machine learning", "ml pipeline", "observability",
        "active directory", "windows server", "powershell", "intune", "entra",
        "microsoft 365", "vmware",
    ],
}

# ---------------------------------------------------------------------------
# 2. Backend / software engineering  (starting point, not outcome-tuned)
# ---------------------------------------------------------------------------
BACKEND_SOFTWARE = {
    "TARGET_TITLES": [
        "Software Engineer", "Backend Engineer", "Back End Engineer",
        "Full Stack Engineer", "Python Developer", "API Engineer",
    ],
    "CORE_TITLE_KEYWORDS": [
        "software", "backend", "back-end", "back end", "full stack", "full-stack",
        "fullstack", "api", "python", "java", "golang", "developer",
    ],
    "EXTRA_TITLE_KEYWORDS": [],
    "ML_TITLE_KEYWORDS": ["ml", "machine learning", "deep learning", "data scientist"],
    "ML_TITLE_LLM_EXEMPTIONS": [],
    "IT_IDENTITY_TITLE_KEYWORDS": [],
    "IT_IDENTITY_SECURITY_BLOCKERS": [],
    "REQUIRE_ONE_OF": [
        "python", "java", "go", "typescript", "javascript", "sql", "rest", "api",
        "postgres", "docker", "aws", "microservices", "git",
    ],
}

# ---------------------------------------------------------------------------
# 3. Data engineering  (starting point, not outcome-tuned)
# Tip: when a bare word is too broad ("data" admits "Data Scientist"), list
# the multi-word phrase instead.
# ---------------------------------------------------------------------------
DATA_ENGINEERING = {
    "TARGET_TITLES": [
        "Data Engineer", "Analytics Engineer", "ETL Developer", "Data Platform Engineer",
    ],
    # Multi-word phrases keep "Data Scientist" / "Data Analyst" out while
    # admitting data-engineering titles (matching is whole-phrase).
    "CORE_TITLE_KEYWORDS": [
        "data engineer", "data engineering", "analytics engineer", "etl",
        "data platform", "data pipeline", "data warehouse", "bi engineer",
    ],
    "EXTRA_TITLE_KEYWORDS": [],
    "ML_TITLE_KEYWORDS": [],
    "ML_TITLE_LLM_EXEMPTIONS": [],
    "IT_IDENTITY_TITLE_KEYWORDS": [],
    "IT_IDENTITY_SECURITY_BLOCKERS": [],
    "REQUIRE_ONE_OF": [
        "sql", "python", "airflow", "dbt", "spark", "snowflake", "bigquery",
        "redshift", "kafka", "etl", "data pipeline", "warehouse",
    ],
}

RECIPES = {
    "infra_and_ai": INFRA_AND_AI,
    "backend_software": BACKEND_SOFTWARE,
    "data_engineering": DATA_ENGINEERING,
}


def apply_to_stage1(recipe: dict, monkeypatch) -> None:
    """Test helper: point screening.stage1 (which imported these names at load
    time) at a recipe. Real use is simply editing config.py."""
    import screening.stage1 as s1

    core = recipe["CORE_TITLE_KEYWORDS"]
    extra = recipe["EXTRA_TITLE_KEYWORDS"]
    monkeypatch.setattr(s1, "CORE_TITLE_KEYWORDS", core)
    monkeypatch.setattr(s1, "TITLE_DOMAIN_KEYWORDS", core + extra)
    for name in ("ML_TITLE_KEYWORDS", "ML_TITLE_LLM_EXEMPTIONS",
                 "IT_IDENTITY_TITLE_KEYWORDS", "IT_IDENTITY_SECURITY_BLOCKERS",
                 "REQUIRE_ONE_OF"):
        monkeypatch.setattr(s1, name, recipe[name])
