---
id: hybridid
name: "HybridID"
tagline: "Hybrid identity & endpoint automation — Active Directory, Entra ID, Intune"
role_families: [sysadmin, it_engineer, security, azure]
skills:
  core: [active_directory, intune_m365, powershell, sso_identity]
  supporting: [endpoint_mgmt, windows_server, patching, azure, compliance]
  touch: [itsm, config_hardening]
est_days: 3
lab_cost: "$0 — Windows Server eval ISO, M365 Developer tenant (free E5 sandbox), Proxmox/Hyper-V host"
---

# HybridID — Hybrid Identity & Endpoint Automation

## Problem
In most mid-size companies, joiner/mover/leaver (JML) is a ticket that an admin works by hand:
create the AD user, pick groups, license M365, enroll the laptop, and — the part that goes
wrong — remember to disable everything when someone leaves. Manual JML is slow (30–60 min
per hire), inconsistent (group sprawl, over-permissioned accounts), and a real audit finding
when orphaned accounts of departed staff stay enabled.

## Why it matters (impact)
- Onboarding time drops from ~45 min of admin work to a few minutes of automated run time.
- Offboarding becomes same-hour and complete, removing orphaned-account audit findings
  (SOC 2 CC6.2 / ISO 27001 A.9.2 access provisioning/removal).
- Role-based group mapping ends "copy Bob's permissions" access creep.
- At 20 hires/month, ~15 admin hours/month saved (~$9k/year at $50/hr loaded cost).

## Approach
1. On-prem AD domain (`corp.lab`) on Windows Server 2022, tiered OU design
   (Tier 0 admins / Users / Workstations / Service Accounts), baseline GPOs
   (password policy, BitLocker, firewall, LAPS).
2. Entra Connect Cloud Sync to an M365 Developer tenant → hybrid identities.
3. PowerShell module `HybridID` driven by a CSV/JSON "HR feed":
   `New-Hire`, `Move-Role`, `Remove-Leaver` — role→group map in one JSON file, idempotent.
4. Entra ID: security defaults off → Conditional Access (MFA for all, block legacy auth),
   SSO enterprise app via SAML/OIDC.
5. Intune: Autopilot-style enrollment of a Windows 11 VM, compliance policy
   (BitLocker, OS version, Defender on), configuration profile, update ring.
6. Nightly access review report: stale accounts (>30 days no logon), privileged group
   membership diff, unlicensed users → HTML/CSV mailed via Graph API.

## Architecture
```
HR feed (CSV) ──> HybridID PowerShell ──> AD DS (corp.lab) ──Cloud Sync──> Entra ID
                         │                    │ GPOs                    │ Conditional Access
                         │                    └─> Win Server/Win11 VMs   ├─> M365 licenses (Graph)
                         └─> Access-review report (Graph mail)           └─> Intune compliance + update rings
```

## Interview-ready core (days 1–2)
AD domain + OU/GPO baseline, the PowerShell JML module with a role map, one Win11 VM
domain-joined, and the stale-account report. This alone answers 80% of AD/PowerShell
interview questions.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | DC build, OU tiering, GPO baseline, LAPS |
| 2 | PowerShell JML module + Pester tests, role map, offboarding checklist automation |
| 3 | Cloud Sync to M365 dev tenant, Conditional Access, Intune compliance + update ring, access-review report |

## Target metrics (measure; replace with actuals)
- Onboarding: manual ~45 min → automated < 3 min per user (timed, 10 test users).
- Offboarding: account disable + group strip + license removal + session revoke in < 60 s.
- 100% of test devices compliant after enrollment; 0 stale accounts after nightly report.
- 12 baseline GPOs, 3 Conditional Access policies, 1 SSO app.

## Draft resume bullets
- Automated joiner/mover/leaver lifecycle across Active Directory and Entra ID with a PowerShell module driven by a role-to-group map, cutting per-user onboarding from ~45 minutes to under 3 and offboarding to under 60 seconds.
- Built a hybrid identity environment (AD DS, Entra Cloud Sync, Conditional Access MFA, SAML SSO) with a tiered OU and GPO baseline including LAPS and BitLocker.
- Enrolled Windows endpoints into Intune with compliance policies and update rings, and shipped a nightly access-review report flagging stale and privileged accounts via Microsoft Graph.

## Likely interview questions
- FSMO roles and what breaks when a DC holding them is down.
- GPO processing order (LSDOU), loopback, why a GPO doesn't apply (`gpresult /r`).
- Cloud Sync vs Connect Sync; password hash sync vs pass-through auth.
- How you'd make offboarding safe (disable first, delete after 30 days, revoke tokens).
