---
id: azurebridge
name: "AzureBridge"
tagline: "Azure landing zone & AKS delivery with Bicep and Azure DevOps pipelines"
role_families: [cloud, azure, devops, platform]
skills:
  core: [azure, azure_devops, cloudformation, secrets_mgmt]
  supporting: [kubernetes, cspm, sso_identity, powershell, vpc_networking_cloud, observability]
  touch: [active_directory, finops]
est_days: 3
lab_cost: "$0–10 — Azure free account ($200 credit), Azure DevOps free tier; stop AKS when idle"
---

# AzureBridge — Azure Landing Zone & AKS Delivery

## Problem
Azure estates tend to grow portal-first: resources clicked into one subscription,
secrets pasted into app settings, public endpoints everywhere, and deployments that only
one engineer knows how to run. Microsoft shops also need this to sit cleanly on top of
Entra ID and existing identity governance.

## Why it matters (impact)
- Hub-spoke network with private endpoints removes public exposure of data services.
- Managed identities + Key Vault eliminate secrets in config and pipelines.
- Azure Policy + Defender for Cloud give a continuously measured secure score.
- Repeatable Bicep deployments via Azure DevOps turn a days-long manual build into a pipeline run.

## Approach
1. Management groups + subscriptions (platform, landing-zone-dev, landing-zone-prod),
   Azure Policy initiatives (allowed regions, require tags, deny public IPs on NICs,
   require private endpoints for storage/SQL).
2. Hub-spoke VNets: Azure Firewall/NVA in hub, spokes peered, Private DNS zones,
   Bastion for admin access.
3. Workload: AKS (Entra-integrated RBAC, workload identity) running a sample API,
   Azure SQL + Storage via private endpoints, Key Vault with CSI secret driver.
4. Bicep modules for everything; Azure DevOps multi-stage YAML pipeline
   (what-if → approval gate → deploy) using workload identity federation service connection.
5. Security posture: Defender for Cloud secure score before/after, Entra PIM for admin roles,
   Conditional Access for portal.
6. Monitoring: Log Analytics + Azure Monitor alerts; cost budgets per subscription;
   PowerShell runbook (Automation Account) for scheduled AKS stop/start.

## Architecture
```
Mgmt groups ─> Azure Policy initiatives
Hub VNet (Firewall, Bastion, Private DNS) ──peering──> Spoke (AKS, SQL PE, Storage PE, Key Vault)
Azure DevOps YAML: Bicep what-if ─> approval ─> deploy (workload identity federation)
Defender for Cloud · Log Analytics · Budgets · Automation runbook (AKS schedule)
```

## Interview-ready core (days 1–2)
Hub-spoke network, AKS with workload identity + Key Vault, private-endpoint SQL, all in
Bicep deployed from an Azure DevOps pipeline with an approval gate.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Mgmt groups, Policy, hub-spoke network, Bicep modules |
| 2 | AKS + workload identity + Key Vault + private endpoints, Azure DevOps pipeline |
| 3 | Defender secure score remediation, PIM/CA, monitoring, budgets, automation runbook |

## Target metrics (measure; replace with actuals)
- Environment rebuild from zero via pipeline < 30 min.
- 0 secrets in pipeline variables or app config (managed identity + Key Vault only).
- Defender secure score: baseline → 85%+ ; 0 public endpoints on data services.
- 10+ Azure Policy assignments enforced; AKS off-hours schedule saves ~60% of cluster hours.

## Draft resume bullets
- Built an Azure landing zone with management groups, Azure Policy guardrails and a hub-spoke network (Azure Firewall, Bastion, Private DNS) defined entirely in Bicep modules.
- Deployed AKS with Entra ID RBAC and workload identity, reaching Azure SQL and Storage only over private endpoints and pulling all secrets from Key Vault, with zero secrets in configuration.
- Delivered infrastructure through a multi-stage Azure DevOps pipeline with what-if previews, approval gates and federated credentials, raising the Defender for Cloud secure score to over 85%.

## Likely interview questions
- Management groups vs subscriptions vs resource groups.
- Service principal vs managed identity vs workload identity federation.
- Private endpoint vs service endpoint.
- Bicep vs Terraform in an Azure shop.
