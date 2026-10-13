---
id: shipyard
name: "ShipYard"
tagline: "GitOps Kubernetes platform — Terraform, Helm, Argo CD, policy guardrails"
role_families: [devops, platform, cloud, sre]
skills:
  core: [kubernetes, helm, gitops, terraform]
  supporting: [docker, github_actions, cicd, prometheus, grafana, policy_as_code, secrets_mgmt]
  touch: [aws, service_mesh, release_eng]
est_days: 3
lab_cost: "$0 on kind/k3d locally; ~$3–5 for a weekend EKS run (tear down after)"
---

# ShipYard — GitOps Kubernetes Platform

## Problem
Teams deploying to Kubernetes with `kubectl apply` from laptops or hand-rolled CI scripts
end up with clusters nobody can reproduce: config drifts from Git, rollbacks are manual,
every team writes YAML differently, and nothing stops a pod running as root with no
resource limits.

## Why it matters (impact)
- Git becomes the single source of truth — every change reviewed, auditable, revertible.
- Self-service golden-path Helm chart lets a new service ship in minutes, not days.
- Admission policies block insecure workloads before they run.
- Drift is auto-healed; rollback = `git revert`.

## Approach
1. Terraform provisions the cluster (EKS module; kind/k3d for local) + VPC + IRSA.
2. Argo CD with the app-of-apps pattern; environments (dev/prod) as overlays.
3. Golden-path Helm chart: Deployment, HPA, PDB, ServiceMonitor, NetworkPolicy,
   resource limits, probes — teams set ~10 values.
4. GitHub Actions: build → Trivy scan → push to registry → bump image tag in the GitOps
   repo (PR) → Argo syncs.
5. Guardrails: Kyverno policies (no root, limits required, trusted registries only,
   required labels).
6. Secrets: External Secrets Operator ← AWS Secrets Manager (or SOPS locally).
7. Platform add-ons via Argo: ingress-nginx, cert-manager, kube-prometheus-stack.
8. Progressive delivery: Argo Rollouts canary with Prometheus analysis.

## Architecture
```
dev PR ─> GitHub Actions (build, scan, push) ─> PR to gitops repo
                                                   │
Terraform ─> EKS/kind ◄── Argo CD (app-of-apps) ◄──┘
                 ├─ Kyverno guardrails   ├─ External Secrets
                 ├─ ingress + cert-manager ├─ kube-prometheus-stack
                 └─ Argo Rollouts canary (Prometheus analysis)
```

## Interview-ready core (days 1–2)
kind cluster, Argo CD app-of-apps, golden Helm chart deploying 2 sample services,
GitHub Actions image-bump flow, 3 Kyverno policies.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Terraform EKS/kind, Argo CD bootstrap, add-ons |
| 2 | Golden-path Helm chart, CI pipeline with scan + GitOps PR, Kyverno |
| 3 | External Secrets, Argo Rollouts canary with Prometheus analysis, EKS run + teardown |

## Target metrics (measure; replace with actuals)
- New service from template to running in prod overlay < 10 min.
- Commit-to-deploy < 5 min; rollback via `git revert` < 2 min.
- 100% of workloads pass 6 Kyverno policies; drift auto-healed within the 3-min sync window.
- Canary auto-aborts on error-rate > 2% (demonstrated with a bad release).

## Draft resume bullets
- Built a GitOps Kubernetes platform with Terraform-provisioned EKS and Argo CD (app-of-apps), where every deploy and rollback is a Git commit, with commit-to-production under 5 minutes.
- Created a golden-path Helm chart (HPA, PDB, NetworkPolicy, probes, ServiceMonitor) that takes a new service to production in under 10 minutes, enforced by Kyverno admission policies.
- Added Argo Rollouts canary releases gated on Prometheus error-rate analysis that automatically aborted a deliberately faulty release, plus External Secrets integration with AWS Secrets Manager.

## Likely interview questions
- What happens when you `kubectl apply` a Deployment (API server → etcd → scheduler → kubelet).
- Pod stuck Pending / CrashLoopBackOff / ImagePullBackOff — diagnosis steps.
- Push vs pull CD; how Argo detects and fixes drift.
- Requests vs limits, HPA mechanics, PDBs during node drains.
