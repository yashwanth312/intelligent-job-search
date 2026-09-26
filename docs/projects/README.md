# Project Catalog

15 portfolio projects derived from the skills in 1,598 applied job descriptions
(analysis run 2026-09-26). Each spec's YAML front matter (`skills.core/supporting/touch`)
is what the resume project scorer reads; the body is the build plan. Build status is
tracked in the [Portfolio Build Board](https://claude.ai/artifact/UwPKd8R8zVisEQnc44H9Mp),
not here and not in the generator — the generator may select any project.

## How the pipeline uses these

1. `profile.yaml` → `portfolio_catalog:` points at each spec; `projects:` holds built work.
2. For every job, `generation/project_scorer.py` ranks all 18 projects against the JD
   (no Claude call) and the generation prompt receives only the top 3: problem statement,
   target metrics and reference bullets, plus the JD skills to emphasize.
3. Resume bullets for a portfolio project may use only that spec's target metrics.
4. Stage 2 screening sees one line per project and may raise confidence by at most 1
   for a skill gap a project covers.
5. Each application records its 3 projects (SQLite `feedback.projects_used`, the Applied
   tab's Notes column, `_metadata.json`). On a callback, build that project's
   interview-ready core first. `python feedback_report.py` shows callbacks per project.

Editing a spec's skill tags changes selection immediately; check the effect with
`python scripts/replay_project_scorer.py`.

## Coverage (replay of the production scorer)

Share of a JD's weighted skills covered by the 3 selected projects, averaged over the 1,563 applied JDs with descriptions:

| Project pool | Mean coverage |
|---|---|
| Existing 3 (DiaSense, TerraSecure, Intelligent Job Search) | 30.0% |
| Existing 3 + these 15 | 72.4% |

## Catalog, in coverage-ranked build order

The order is by marginal coverage lift — each project is the one that adds the most
coverage on top of everything above it. An interview request for a specific project
overrides this order.

| # | Project | Focus | Lift | Picked on | Days |
|---|---|---|---|---|---|
| 1 | [BlueWatch](11-bluewatch.md) | SIEM detections, incident response, hardening | +8.4 | 18% | 3 |
| 2 | [CloudBase](08-cloudbase.md) | Multi-cloud landing zone (AWS + GCP), FinOps | +5.6 | 13% | 3 |
| 3 | [RestorePoint](02-restorepoint.md) | Backup, DR, virtualization, storage | +4.0 | 12% | 3 |
| 4 | [OpsAgent](13-opsagent.md) | Tool-calling AI triage agent over MCP | +3.1 | 34% | 2 |
| 5 | [StreamLedger](15-streamledger.md) | Go microservices on Kafka, tracing | +2.8 | 13% | 3 |
| 6 | [AzureBridge](09-azurebridge.md) | Azure landing zone, AKS, Azure DevOps | +2.5 | 11% | 3 |
| 7 | [NetCore](03-netcore.md) | DNS/DHCP, firewall, VPN, routing as code | +2.3 | 18% | 3 |
| 8 | [PagerZero](06-pagerzero.md) | SLOs, observability, incident response | +2.1 | 19% | 3 |
| 9 | [FleetForge](04-fleetforge.md) | Linux fleet hardening, patching, Ansible | +1.5 | 17% | 2 |
| 10 | [SupplyGuard](10-supplyguard.md) | DevSecOps supply chain, CSPM | +1.5 | 14% | 2 |
| 11 | [HybridID](01-hybridid.md) | AD, Entra ID, Intune, PowerShell | +1.4 | 15% | 3 |
| 12 | [InferenceStack](14-inferencestack.md) | LLM inference on K8s GPUs, MLOps | +1.3 | 8% | 3 |
| 13 | [DocFlow](07-docflow.md) | Serverless AWS pipeline | +0.9 | 10% | 2 |
| 14 | [ShipYard](05-shipyard.md) | GitOps Kubernetes platform | +0.6 | 16% | 3 |
| 15 | [RunbookRAG](12-runbookrag.md) | RAG assistant with eval harness | +0.6 | 30% | 2 |

"Lift" = percentage points of mean coverage added (prototype run that set the order).
"Picked on" = share of the 1,563 replayed resumes where the production scorer
includes it. Low lift with a high pick rate (RunbookRAG, ShipYard) means the project is often chosen but overlaps skills an earlier project
already covers.

Total estimated build time: ~40 days at the listed pace; each spec has a 1–2 day
"interview-ready core" to build first when an interview lands.

## Spec format

Every spec has: problem, impact, approach, architecture, interview-ready core, day-by-day
build plan, target metrics, draft resume bullets, likely interview questions. Target metrics
are the only numbers resume bullets may use, so every company sees the same claims — and
they are the numbers to hit while building.
