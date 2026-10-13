---
id: fleetforge
name: "FleetForge"
tagline: "Linux fleet hardening, patching & configuration management pipeline"
role_families: [sysadmin, devops, sre, security]
skills:
  core: [linux, ansible, config_hardening, patching]
  supporting: [bash, gitlab_ci, jenkins, puppet_chef, packer, compliance]
  touch: [python, vuln_mgmt, cicd]
est_days: 2
lab_cost: "$0 — 6–10 RHEL/Rocky/Ubuntu VMs on Proxmox or Vagrant; GitLab CE container"
---

# FleetForge — Linux Fleet Hardening & Patch Automation

## Problem
Linux servers drift. Each was built slightly differently, patches are applied whenever
someone remembers, and the CIS benchmark score nobody measures is somewhere around 50%.
Patch night is a manual SSH loop that reboots everything at once and occasionally takes
production down.

## Why it matters (impact)
- Golden images + config management = every server identical and rebuildable.
- Rolling, health-checked patching removes the "patch night outage".
- CIS compliance from ~50% to 90%+ closes the most common audit and pentest findings.
- Patch cycle for a 100-server fleet goes from a day of admin time to an unattended run.

## Approach
1. Packer builds a hardened golden image (RHEL/Rocky 9 + Ubuntu 22.04).
2. Ansible roles: baseline (users, sudo, SSH hardening, chrony, auditd, SELinux enforcing),
   CIS Level 1 remediation, LVM layout, log forwarding, node_exporter.
3. Dynamic inventory by environment (dev/stage/prod) and role.
4. Patch pipeline in GitLab CI (Jenkinsfile equivalent included): stage → canary 10% →
   rolling batches with `serial`, pre/post health checks, auto-halt on failure,
   reboot only if kernel changed.
5. Compliance scanning with OpenSCAP before/after; report published as a CI artifact.
6. Molecule tests for every role; `ansible-lint` in CI.

## Architecture
```
Packer ─> golden image ─> VMs (dev/stage/prod)
GitLab CI ─> lint + Molecule ─> Ansible baseline/CIS roles ─> fleet
         └─> patch pipeline: canary ─> rolling batches ─> health checks ─> OpenSCAP report
```

## Interview-ready core (day 1)
Ansible baseline + CIS roles against 6 VMs, before/after OpenSCAP score, rolling patch
playbook with health checks.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Ansible roles, inventory, OpenSCAP before/after, rolling patch playbook |
| 2 | Packer golden images, GitLab CI pipeline with Molecule tests, canary patching, Jenkinsfile |

## Target metrics (measure; replace with actuals)
- CIS Level 1 score: ~55% → 92%+ across the fleet (OpenSCAP).
- Fleet patch run fully unattended; canary + rolling batches; 0 simultaneous-outage reboots.
- New server from golden image to compliant in < 10 min.
- 8 Ansible roles, each with Molecule tests.

## Draft resume bullets
- Built Ansible roles and Packer golden images that bring RHEL and Ubuntu servers to CIS Level 1, raising the fleet's OpenSCAP compliance score from ~55% to over 92%.
- Automated rolling OS patching through a GitLab CI pipeline with canary batches, pre/post health checks and automatic halt on failure, removing manual patch-night work.
- Cut new-server provisioning to under 10 minutes from image to compliant, with every role tested by Molecule and ansible-lint in CI.

## Likely interview questions
- Troubleshoot a server that won't boot after a kernel update (GRUB, rescue, previous kernel).
- SELinux denials — how to diagnose (`ausearch`, `audit2why`) rather than disabling.
- Ansible idempotency, handlers, `serial`, `max_fail_percentage`.
- Puppet/Chef (pull) vs Ansible (push) trade-offs.
