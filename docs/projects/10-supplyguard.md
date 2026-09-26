---
id: supplyguard
name: "SupplyGuard"
tagline: "Secure software supply chain & cloud security posture pipeline (DevSecOps)"
role_families: [security, devsecops, devops, cloud]
skills:
  core: [devsecops, vuln_mgmt, secrets_mgmt, policy_as_code, cspm]
  supporting: [github_actions, cicd, docker, compliance, kubernetes, artifact_mgmt]
  touch: [terraform, aws]
est_days: 2
lab_cost: "$0 — GitHub Actions, open-source scanners (Trivy, Semgrep, Gitleaks, Checkov, Prowler), Sigstore"
---

# SupplyGuard — Secure Software Supply Chain & CSPM

## Problem
Most CI pipelines build and ship whatever is in the repo: vulnerable base images,
hardcoded secrets, misconfigured Terraform, and unsigned artifacts nobody can trace back
to a commit. Security finds out at the annual pentest. Meanwhile the cloud account
itself drifts into public buckets and overly broad IAM.

## Why it matters (impact)
- Shift-left: vulnerabilities and misconfigs caught in the PR cost minutes to fix,
  not days after release.
- Signed images + SBOMs + admission verification block tampered or untracked artifacts
  (SLSA, EO 14028 expectations).
- Continuous CSPM turns a yearly audit into a daily score.
- Secrets never reach Git (pre-commit + CI scanning).

## Approach
1. Reference app repo (API + Dockerfile + Terraform + K8s manifests).
2. GitHub Actions security pipeline:
   Gitleaks (secrets) → Semgrep (SAST) → Trivy (deps + image CVEs) → Checkov/tfsec
   (IaC) → Syft SBOM → Cosign keyless signing + SLSA provenance → push to registry.
3. Policy gates as code (OPA/Conftest): fail on critical CVEs with a fix available,
   any secret, high IaC findings; exceptions via reviewed allowlist file with expiry.
4. Kubernetes admission: Kyverno `verifyImages` only runs signed images from trusted registry.
5. CSPM: Prowler against the AWS account nightly (CIS benchmark), results to Security Hub;
   findings trend dashboard; auto-remediation Lambda for 2 classes (public S3, open SG 0.0.0.0/0 on 22).
6. Metrics: before/after finding counts on a deliberately vulnerable baseline.

## Architecture
```
PR ─> Gitleaks · Semgrep · Trivy · Checkov ─> OPA gate ─> build ─> Syft SBOM ─> Cosign sign ─> registry
                                                                                 │
K8s: Kyverno verifyImages ◄──────────────────────────────────────────────────────┘
AWS: Prowler nightly ─> Security Hub ─> dashboard · auto-remediation Lambda
```

## Interview-ready core (day 1)
Full scanner chain in GitHub Actions with OPA gate, SBOM + Cosign signing, and a
Prowler baseline report with before/after.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Scanner chain, OPA/Conftest gate, SBOM, signing |
| 2 | Kyverno verifyImages, Prowler + Security Hub, auto-remediation, trend dashboard |

## Target metrics (measure; replace with actuals)
- Seeded baseline: N critical/high CVEs, M IaC misconfigs, K secrets → 0 blocking findings after remediation.
- 100% of deployed images signed + SBOM attached; unsigned image admission blocked (demonstrated).
- CIS AWS benchmark (Prowler) pass rate: baseline → 90%+; 2 misconfig classes auto-remediated in < 5 min.
- Pipeline security stage adds < 3 min to CI.

## Draft resume bullets
- Built a DevSecOps pipeline in GitHub Actions chaining secret scanning, SAST, dependency and container CVE scanning and IaC checks behind OPA policy gates, adding under 3 minutes to CI.
- Implemented software supply-chain controls — SBOM generation, Cosign keyless signing and SLSA provenance — with Kyverno admission verification so only signed images run in Kubernetes.
- Automated cloud security posture management with nightly Prowler CIS scans into Security Hub and auto-remediation of public S3 buckets and open SSH security groups within 5 minutes.

## Likely interview questions
- SAST vs DAST vs SCA; how to handle false positives without disabling the gate.
- What an SBOM is and how it helped during Log4Shell-type events.
- How keyless signing (Sigstore/Fulcio/Rekor) works at a high level.
- Top 5 AWS misconfigurations and how you'd detect/prevent each.
