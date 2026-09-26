---
id: cloudbase
name: "CloudBase"
tagline: "Multi-cloud landing zone & FinOps — AWS Organizations + GCP, Terraform"
role_families: [cloud, platform, finops, security]
skills:
  core: [landing_zone, terraform, finops, cloud_iam, gcp, aws, multi_cloud]
  supporting: [vpc_networking_cloud, compliance, sso_identity, grafana]
  touch: [python]
est_days: 3
lab_cost: "< $5 — AWS Organizations + GCP free trial; budgets/billing exports are free; tear down NAT/VPN"
---

# CloudBase — Multi-Cloud Landing Zone & FinOps

## Problem
Companies that start in one cloud account end up with everything — dev, prod, experiments —
in one blast radius, IAM users with static keys, no tagging, and a cloud bill nobody can
attribute. When a second cloud arrives (often GCP for data/AI), it gets built by hand
with different conventions.

## Why it matters (impact)
- Account/project isolation contains breaches and mistakes to one environment.
- Central SSO + guardrails (SCPs / Org Policies) remove static keys and prevent risky configs.
- Tag enforcement + cost allocation lets teams see and own spend; rightsizing and
  schedules typically cut non-prod spend 30–40%.
- New team environment vended in minutes instead of a week of tickets.

## Approach
1. AWS: Organizations with OUs (Security, Infrastructure, Workloads/dev, Workloads/prod,
   Sandbox), IAM Identity Center SSO, SCP guardrails (deny root, region lock, deny
   disabling CloudTrail/GuardDuty), org CloudTrail to a log-archive account.
2. GCP: folder hierarchy mirroring the OUs, Org Policy constraints (no external IPs,
   uniform bucket access, domain-restricted sharing), Workload Identity Federation.
3. Account/project vending: one Terraform module call → new account/project with baseline
   (VPC, logging, budgets, tags, SSO permission set).
4. Networking: hub-and-spoke (Transit Gateway / Shared VPC), AWS↔GCP HA VPN.
5. FinOps: mandatory tags (owner, env, cost-center) enforced by policy; CUR + BigQuery
   billing export → unified cost dashboard (Grafana/Looker Studio); budgets + anomaly
   alerts; nightly scheduler stopping non-prod; rightsizing report (Python).
6. Compliance: AWS Config conformance pack (CIS) + GCP Security Command Center findings summary.

## Architecture
```
Terraform ─┬─> AWS Org: OUs · SCPs · Identity Center · log-archive · TGW hub ─┐
           │                                                                 ├─ HA VPN
           └─> GCP Org: folders · Org Policies · Shared VPC hub ─────────────┘
account/project vending module ─> baseline (VPC, logs, budget, tags, SSO)
CUR + BigQuery billing export ─> cost dashboard · budgets · anomaly alerts · rightsizing report
```

## Interview-ready core (days 1–2)
AWS Organizations with OUs, SCPs, Identity Center; account vending module; tag policy +
budgets + cost dashboard.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | AWS Org, OUs, SCPs, Identity Center, log archive, vending module |
| 2 | GCP org/folders/Org Policies, Shared VPC, HA VPN to AWS |
| 3 | FinOps: tag enforcement, billing exports, dashboard, budgets/anomalies, scheduler, rightsizing |

## Target metrics (measure; replace with actuals)
- New account/project vended with full baseline in < 15 min (vs ~days of tickets).
- 0 IAM users with static keys; 100% resources tagged (enforced).
- 8 SCP / Org Policy guardrails; CIS conformance ≥ 90%.
- Non-prod off-hours schedule: ~65% compute-hour reduction on scheduled resources (projected monthly $ on a sample fleet).

## Draft resume bullets
- Designed a multi-cloud landing zone in Terraform across AWS Organizations and GCP folders with SSO via IAM Identity Center, SCP and Org Policy guardrails, and centralized audit logging.
- Built an account and project vending module that delivers a baselined environment (networking, logging, budgets, tagging, SSO) in under 15 minutes, connected by hub-and-spoke networking and an AWS-to-GCP HA VPN.
- Implemented FinOps controls — enforced cost-allocation tags, unified billing dashboards, budgets with anomaly alerts, off-hours scheduling and rightsizing reports — reducing scheduled non-prod compute hours about 65%.

## Likely interview questions
- SCPs vs IAM policies vs permission boundaries.
- Why multi-account; what goes in the security and log-archive accounts.
- Shared VPC vs VPC peering vs Transit Gateway.
- How you'd cut a cloud bill by 30% in a month.
