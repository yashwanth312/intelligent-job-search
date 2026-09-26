"""Canonical skill taxonomy shared by JD extraction and project tagging.

Every skill is a canonical key mapped to one alias regex, matched against
lowercased text. Project specs (docs/projects/*.md front matter) and
profile.yaml project `skills:` blocks tag themselves with these keys, so a
JD saying "EKS" and a project tagged `kubernetes` meet on the same key.

Patterns are deliberately conservative where a bare word is ambiguous in job
postings: "monitoring", "audit", "endpoint" (API endpoints), "organizations",
"certificate" (degree programs) and "san" (San Francisco) are all qualified.
"""
from __future__ import annotations

import re
from collections import Counter

_SF_CITIES = r"francisco|jose|diego|antonio|mateo|bruno|carlos|juan|ramon|rafael|luis|marcos"

SKILLS: dict[str, str] = {
    # cloud
    "aws": r"\baws\b|amazon web services",
    "azure": r"\bazure\b",
    "gcp": r"\bgcp\b|google cloud",
    "oci": r"\boci\b|oracle cloud",
    "multi_cloud": r"multi-cloud|multicloud|hybrid cloud",
    "ec2": r"\bec2\b",
    "s3": r"\bs3\b",
    "lambda_serverless": r"\blambda\b|serverless|azure functions|cloud functions|cloud run",
    "vpc_networking_cloud": r"\bvpc\b|\bvnet\b|transit gateway|direct connect|expressroute|private ?link",
    "cloud_iam": r"\biam\b|identity and access management",
    "cloudformation": r"cloudformation|\bcdk\b|\bbicep\b|arm templates?",
    "landing_zone": r"landing zones?|control tower|aws organizations|account vending",
    "cloud_migration": r"cloud migrations?|migrat\w+ to (?:the )?cloud|lift[- ]and[- ]shift|re-?platform",
    "finops": r"finops|cost optimi[sz]ation|cloud cost|cost management|reserved instances?|savings plans?",
    # containers
    "docker": r"docker|containeri[sz]",
    "kubernetes": r"kubernetes|\bk8s\b|\beks\b|\baks\b|\bgke\b|openshift",
    "helm": r"\bhelm\b|kustomize",
    "gitops": r"argo ?cd|\bflux\b|gitops",
    "service_mesh": r"istio|linkerd|service mesh|\benvoy\b",
    "k8s_operator": r"kubernetes operators?|operator pattern|custom resources?|\bcrds?\b|controller-runtime",
    "policy_as_code": r"\bopa\b|open policy agent|gatekeeper|kyverno|policy[- ]as[- ]code",
    # iac / config
    "terraform": r"terraform|opentofu",
    "pulumi": r"pulumi",
    "ansible": r"ansible",
    "puppet_chef": r"\bpuppet\b|\bchef\b|saltstack",
    "packer": r"\bpacker\b|golden images?",
    # ci/cd
    "cicd": r"ci ?/ ?cd|continuous integration|continuous deliver|continuous deploy",
    "jenkins": r"jenkins",
    "github_actions": r"github actions",
    "gitlab_ci": r"gitlab",
    "azure_devops": r"azure devops|azure pipelines",
    "artifact_mgmt": r"artifactory|\bnexus\b|container registr|\becr\b|\bacr\b",
    "release_eng": r"release engineering|blue[- ]green|canary (?:release|deploy)|feature flags?|rollbacks?",
    # observability / sre
    "prometheus": r"prometheus",
    "grafana": r"grafana",
    "datadog": r"datadog",
    "splunk": r"splunk",
    "elk": r"\belk\b|elasticsearch|kibana|logstash|opensearch",
    "otel_tracing": r"opentelemetry|\botel\b|distributed tracing|jaeger|\btempo\b",
    "observability": r"observability|monitoring (?:and|&) alerting|\balerting\b|\bapm\b|telemetry",
    "slo": r"\bslos?\b|\bslis?\b|error budgets?|service level objectives?",
    "incident_response": r"incident response|incident management|on-call|on call rotation|pagerduty|opsgenie",
    "postmortem": r"post-?mortems?|root cause analysis|\brca\b|blameless",
    "chaos": r"chaos engineering|fault injection|game ?days?",
    "capacity_perf": r"capacity planning|performance tuning|load test|performance test|\bk6\b|jmeter",
    "high_availability": r"high availability|fault[- ]toleran|resilien",
    "disaster_recovery": r"disaster recovery|\bbcp\b|business continuity|\brto\b|\brpo\b|failover",
    # linux / systems
    "linux": r"linux|\brhel\b|centos|ubuntu|debian",
    "bash": r"\bbash\b|shell script",
    "powershell": r"powershell",
    "windows_server": r"windows server|\biis\b|hyper-v",
    "active_directory": r"active directory|\bentra\b|azure ad\b|\bgpos?\b|group polic|\bldap\b",
    "intune_m365": r"intune|\bm365\b|office 365|microsoft 365|exchange online|\bsccm\b|\bmecm\b|endpoint manager",
    "vmware": r"vmware|vsphere|\besxi\b|vcenter|proxmox|nutanix|virtuali[sz]ation",
    "storage": rf"\bsan\b(?! (?:{_SF_CITIES}))|\bnas\b|netapp|pure storage|\bnfs\b|\bsmb\b|\biscsi\b|storage|file shares?|\blvm\b|\bzfs\b|\bceph\b",
    "backup": r"backups?\b|restores?\b|veeam|rubrik|commvault|snapshots?",
    "patching": r"patch(?:ing)? management|\bpatching\b|\bwsus\b|vulnerability remediation",
    "config_hardening": r"\bcis\b (?:benchmark|controls)|hardening|\bstigs?\b|selinux",
    "endpoint_mgmt": r"endpoint (?:management|security|protection|detection)|\bmdm\b|jamf|device management",
    "itsm": r"servicenow|\bitsm\b|\bitil\b|jira service|ticketing",
    # networking
    "networking": r"tcp/ip|networking|\bosi model\b|subnet",
    "dns_dhcp": r"\bdns\b|\bdhcp\b|route ?53",
    "load_balancing": r"load balanc|\bnginx\b|haproxy|\balb\b|\belb\b|\bf5\b",
    "firewall_vpn": r"firewalls?|\bvpns?\b|palo alto|fortinet|wireguard|ipsec",
    "routing_switching": r"\bbgp\b|\bospf\b|\brouting\b|\bswitching\b|\bvlans?\b|cisco|juniper|arista",
    "cdn_edge": r"\bcdn\b|cloudflare|cloudfront|akamai|\bwaf\b",
    "zero_trust": r"zero trust|\bztna\b|\bsase\b|zscaler",
    # security
    "security_ops": r"\bsiem\b|\bsoc\b(?! ?2)|threat detection|microsoft sentinel|crowdstrike|\bedr\b|\bxdr\b",
    "vuln_mgmt": r"vulnerability (?:management|scanning|assessment)|nessus|qualys|trivy|snyk|\bcves?\b",
    "secrets_mgmt": r"\bvault\b|secrets management|key vault|secrets manager|\bkms\b",
    "compliance": r"soc ?2|iso ?27001|hipaa|\bpci\b|fedramp|\bnist\b|compliance",
    "devsecops": r"devsecops|\bsast\b|\bdast\b|supply chain security|\bsbom\b|shift[- ]left",
    "cspm": r"\bcspm\b|security posture|guardduty|security hub|defender for cloud|\bwiz\b|prisma cloud",
    "pki_tls": r"\bpki\b|\btls\b|\bssl\b|x\.509|certificate (?:management|authority|lifecycle)",
    "sso_identity": r"\bsso\b|\bsaml\b|oauth|\boidc\b|\bokta\b|\bmfa\b",
    # programming
    "python": r"python",
    "go": (r"\bgolang\b|\bgo\s*\(|\b(?:in|with|using|like)\s+go\b"
           r"|\bgo\s*(?:,|/|and|or)\s*(?:python|java|rust|c\+\+)"
           r"|\b(?:python|java|rust|c\+\+|typescript)\s*(?:,|/|and|or)\s*go\b"),
    "java": r"\bjava\b",
    "typescript_js": r"typescript|javascript|node\.?js",
    "rust": r"\brust\b",
    "rest_api": r"rest(?:ful)? apis?|\bgrpc\b|graphql|\bapis?\b",
    "microservices": r"microservices?|distributed systems",
    # data
    "sql": r"\bsql\b|postgres|mysql|sql server",
    "nosql": r"mongodb|dynamodb|cassandra|\bredis\b|cosmos ?db",
    "kafka_streaming": r"kafka|kinesis|pub/sub|rabbitmq|event[- ]driven|stream processing",
    "data_pipeline": r"\betl\b|\belt\b|data pipelines?|airflow|\bdbt\b|\bspark\b|databricks|snowflake",
    # ai / ml
    "llm": r"\bllms?\b|large language models?|generative ai|\bgenai\b|\bgpt\b|claude|openai|anthropic",
    "rag": r"\brag\b|retrieval[- ]augmented|vector (?:db|database|store|search)|embeddings?|pinecone|pgvector",
    "agents": r"ai agents?|agentic|langchain|langgraph|llamaindex|tool calling|function calling|\bmcp\b",
    "mlops": r"mlops|mlflow|kubeflow|model registry|model serving|model deployment|feature store",
    "ml_platforms": r"sagemaker|vertex ai|azure ml\b|bedrock|azure openai",
    "ml_frameworks": r"pytorch|tensorflow|scikit|keras|hugging ?face",
    "llm_eval": (r"\bevals?\b|llm evaluation|model evaluation|evaluation (?:framework|harness|pipeline)s?"
                 r"|guardrails?|(?:ai|llm|model) red[- ]team|hallucination"),
    "gpu_inference": r"\bgpus?\b|\bcuda\b|\bvllm\b|triton|inference|tensorrt",
}

_COMPILED: dict[str, re.Pattern[str]] = {k: re.compile(v) for k, v in SKILLS.items()}

# Human-readable names for the few keys whose snake_case reads badly in a prompt.
_LABELS = {
    "aws": "AWS", "gcp": "GCP", "oci": "Oracle Cloud", "ec2": "EC2", "s3": "S3",
    "lambda_serverless": "Lambda/serverless", "vpc_networking_cloud": "VPC/cloud networking",
    "cloud_iam": "cloud IAM", "cloudformation": "CloudFormation/CDK/Bicep",
    "finops": "FinOps/cost optimization", "k8s_operator": "Kubernetes operators",
    "cicd": "CI/CD", "github_actions": "GitHub Actions", "gitlab_ci": "GitLab CI",
    "azure_devops": "Azure DevOps", "otel_tracing": "OpenTelemetry/tracing",
    "slo": "SLOs/SLIs", "elk": "ELK/OpenSearch", "intune_m365": "Intune/Microsoft 365",
    "vmware": "VMware/virtualization", "dns_dhcp": "DNS/DHCP", "firewall_vpn": "firewalls/VPN",
    "routing_switching": "routing/switching", "cdn_edge": "CDN/WAF", "security_ops": "SIEM/SOC",
    "vuln_mgmt": "vulnerability management", "cspm": "cloud security posture (CSPM)",
    "pki_tls": "PKI/TLS", "sso_identity": "SSO/SAML/OIDC", "typescript_js": "TypeScript/JavaScript",
    "rest_api": "REST APIs", "sql": "SQL", "nosql": "NoSQL", "kafka_streaming": "Kafka/streaming",
    "llm": "LLMs", "rag": "RAG", "agents": "AI agents", "mlops": "MLOps",
    "ml_platforms": "ML platforms (SageMaker/Vertex/Bedrock)", "llm_eval": "LLM evaluation",
    "gpu_inference": "GPU inference", "go": "Go", "devsecops": "DevSecOps",
    "itsm": "ITSM/ServiceNow", "puppet_chef": "Puppet/Chef",
}


def label(skill: str) -> str:
    return _LABELS.get(skill, skill.replace("_", " "))


def extract(text: str) -> set[str]:
    """Canonical skills mentioned anywhere in `text`."""
    t = (text or "").lower()
    return {k for k, rx in _COMPILED.items() if rx.search(t)}


def count(text: str) -> Counter[str]:
    """Mention counts per canonical skill in `text`."""
    t = (text or "").lower()
    out: Counter[str] = Counter()
    for k, rx in _COMPILED.items():
        n = len(rx.findall(t))
        if n:
            out[k] = n
    return out
