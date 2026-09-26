---
id: restorepoint
name: "RestorePoint"
tagline: "Backup, disaster recovery & virtualization platform with tested restores"
role_families: [sysadmin, infra, sre]
skills:
  core: [backup, disaster_recovery, vmware, storage]
  supporting: [linux, patching, capacity_perf, high_availability, dns_dhcp]
  touch: [bash, ansible, s3, windows_server]
est_days: 3
lab_cost: "$0–5/mo — Proxmox VE on a spare PC or nested VM, Proxmox Backup Server, Backblaze B2/S3 offsite (~$1/mo)"
---

# RestorePoint — Backup, DR & Virtualization Platform

## Problem
Most small/mid infra teams *have* backups but have never *restored* from them under
time pressure. RTO/RPO numbers in the DR plan are guesses, offsite copies are missing or
unencrypted, and storage fills up silently until a backup job fails. A backup that
hasn't been restore-tested is a hope, not a control.

## Why it matters (impact)
- Converts DR from a document into a measured, repeatable drill with real RTO/RPO numbers.
- 3-2-1 backups (3 copies, 2 media, 1 offsite, immutable) protect against ransomware.
- Automated restore tests catch corrupt backups before an outage does.
- Dedup + retention policy cut backup storage ~60–70% vs full nightly copies.

## Approach
1. Proxmox VE cluster (or single node + nested) hosting a mini "company":
   AD/DNS VM, Linux file server (Samba + NFS on LVM/ZFS), PostgreSQL VM, web VM.
2. Storage: ZFS pool with snapshots, LVM thin pools, SMB/NFS shares with quotas.
3. Proxmox Backup Server: nightly incremental, dedup, encryption, retention
   (7 daily / 4 weekly / 6 monthly), sync to offsite S3-compatible bucket with object lock.
4. App-consistent DB backups: `pg_dump` + WAL archiving → point-in-time recovery.
5. **Automated restore drill** (weekly, Bash/Ansible): restore latest VM backup to an
   isolated VLAN, boot, run health checks (service up, row counts, file checksums),
   record timings, tear down, post result.
6. DR runbook: full site-loss scenario rebuilt from offsite copy, timed.
7. Capacity dashboard: pool usage, growth rate, days-until-full forecast.

## Architecture
```
Proxmox VE ──> VMs (AD/DNS, file server ZFS/LVM, Postgres, web)
     │
     └─> Proxmox Backup Server (dedup, encrypted) ──sync──> S3 bucket (object lock)
                   │
        weekly restore-drill job ─> isolated VLAN ─> health checks ─> RTO/RPO report
```

## Interview-ready core (days 1–2)
Proxmox + 3 VMs, ZFS/LVM storage with SMB/NFS shares, PBS with retention and offsite sync,
and one timed manual full-VM restore with a written runbook.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Proxmox, storage (ZFS/LVM), file server shares, VMs |
| 2 | PBS schedules, retention, encryption, offsite + immutability, Postgres PITR |
| 3 | Automated restore drill, DR runbook + timed site-loss rebuild, capacity forecast |

## Target metrics (measure; replace with actuals)
- Full VM restore RTO < 15 min; database PITR to any point in last 7 days, RPO ≤ 5 min.
- Dedup ratio ≥ 3:1 (≈ 65% storage saved vs full copies).
- 100% of weekly restore drills pass automated health checks over 4 weeks.
- Site-loss rebuild from offsite copy < 90 min.

## Draft resume bullets
- Built a virtualized infrastructure on Proxmox with ZFS/LVM storage and SMB/NFS file services, protected by an encrypted, deduplicated 3-2-1 backup design with immutable offsite copies.
- Automated weekly restore drills that boot backups in an isolated network and verify service health, proving a full-VM RTO under 15 minutes and database point-in-time recovery with RPO of 5 minutes.
- Wrote and timed a site-loss disaster recovery runbook and a storage capacity forecast, cutting backup storage ~65% through deduplication and tiered retention.

## Likely interview questions
- RTO vs RPO; how you'd pick them per system.
- Crash-consistent vs application-consistent backups.
- Snapshots are not backups — why.
- Ransomware-resilient backup design (immutability, separate credentials, air gap).
