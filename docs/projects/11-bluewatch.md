---
id: bluewatch
name: "BlueWatch"
tagline: "SIEM detection engineering & incident response lab — Wazuh/Elastic, Sysmon, playbooks"
role_families: [security, soc, sysadmin]
skills:
  core: [security_ops, incident_response, config_hardening, zero_trust]
  supporting: [elk, splunk, endpoint_mgmt, compliance, vuln_mgmt, linux, windows_server]
  touch: [python, postmortem]
est_days: 3
lab_cost: "$0 — Wazuh or Elastic Security (self-hosted), Sysmon, Atomic Red Team, Splunk free dev license"
---

# BlueWatch — SIEM Detection & Incident Response Lab

## Problem
Many organizations buy a SIEM and forward logs into it, but detections are vendor
defaults, nobody knows which attacker techniques are actually covered, and alerts arrive
without a playbook. Analysts drown in noise while real intrusions (credential dumping,
lateral movement) go unnoticed.

## Why it matters (impact)
- Detections mapped to MITRE ATT&CK give a measurable coverage number instead of a guess.
- Each detection validated by a real simulated attack → known true-positive, tuned false positives.
- Playbooks + SOAR-style automation cut triage from ~30 min to minutes per alert.
- Hardening baselines remove the attack paths detections would otherwise have to catch.

## Approach
1. Lab: Windows Server DC + Windows 11 + 2 Linux servers, attacker Kali VM, isolated network.
2. Telemetry: Sysmon (SwiftOnSecurity/Olaf config), Windows event forwarding, auditd,
   osquery → Wazuh or Elastic Security (Splunk free as a parallel option for SPL practice).
3. Attack simulation: Atomic Red Team + manual scenarios (Mimikatz-style LSASS access,
   Kerberoasting, PsExec lateral movement, persistence via scheduled task, SSH brute force).
4. Detection engineering: 20+ Sigma rules → converted to the SIEM, each mapped to an
   ATT&CK technique, tested against its atomic, tuned for FPs; rules in Git with CI tests.
5. Response: 5 playbooks (compromised account, malware on host, brute force, lateral movement,
   data exfil) — triage steps, containment, evidence collection; Python enrichment
   (IP reputation, user context) + auto-isolation of host via Wazuh active response.
6. Hardening: CIS baselines + Windows LAPS/tiering; re-run attacks to show which are now blocked.
7. ATT&CK Navigator heatmap of coverage before/after.

## Architecture
```
Kali (Atomic Red Team) ──attacks──> Win DC · Win11 · Linux (Sysmon, auditd, osquery)
                                         └─ logs ─> Wazuh/Elastic (+Splunk) ─> Sigma detections (Git+CI)
                                                         └─> alert ─> enrichment (Python) ─> playbook ─> active response
ATT&CK Navigator coverage heatmap · CIS hardening before/after
```

## Interview-ready core (days 1–2)
Lab + Sysmon + Wazuh/Elastic, 10 Sigma detections validated against Atomic Red Team,
2 playbooks, ATT&CK coverage map.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Lab VMs, Sysmon/auditd/osquery, SIEM ingestion |
| 2 | Attack simulations, 20+ Sigma detections with tests, ATT&CK mapping |
| 3 | Playbooks, Python enrichment + active response, hardening re-test, Splunk SPL versions |

## Target metrics (measure; replace with actuals)
- 20+ detections across ~25 ATT&CK techniques, each validated by a simulated attack.
- Mean time to detect simulated attacks < 1 min; triage with enrichment < 5 min.
- False positives reduced ≥ 70% through tuning over a week of baseline noise.
- After hardening, X of Y attack scenarios blocked outright.

## Draft resume bullets
- Built a detection engineering lab with Sysmon, auditd and osquery telemetry flowing into Wazuh/Elastic, and wrote 20+ Sigma detections mapped to MITRE ATT&CK, each validated against Atomic Red Team simulations.
- Authored incident response playbooks for account compromise, lateral movement and brute force, with Python alert enrichment and automated host isolation, bringing triage under 5 minutes per alert.
- Applied CIS hardening and AD tiering, then re-ran attack scenarios to demonstrate blocked attack paths, while cutting detection false positives by more than 70% through tuning.

## Likely interview questions
- Walk through triaging a suspicious PowerShell alert.
- Which Windows event IDs matter (4624/4625/4688/4769/7045) and why.
- Kerberoasting: how it works, how to detect, how to prevent.
- NIST incident response lifecycle; containment vs eradication.
