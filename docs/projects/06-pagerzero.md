---
id: pagerzero
name: "PagerZero"
tagline: "SLO-driven observability & incident response — Prometheus, Grafana, OpenTelemetry"
role_families: [sre, devops, platform, infra]
skills:
  core: [slo, incident_response, postmortem, prometheus, grafana, observability]
  supporting: [otel_tracing, elk, capacity_perf, high_availability, chaos]
  touch: [kubernetes, datadog, python]
est_days: 3
lab_cost: "$0 — kind/k3d or Docker Compose; PagerDuty free tier; Grafana OSS stack"
---

# PagerZero — SLO-Driven Observability & Incident Response

## Problem
Most teams alert on causes (CPU > 80%) instead of symptoms users feel. The result is
alert fatigue — hundreds of pages, most not actionable — while real outages are found by
customers. Without SLOs there's no objective way to decide between shipping features and
fixing reliability, and postmortems are blame sessions rather than learning.

## Why it matters (impact)
- Symptom-based SLO burn-rate alerts cut page volume 70–90% while catching real impact faster.
- Unified metrics + logs + traces cut mean time to resolve (MTTR) by making root cause
  one click from the alert.
- Error budgets turn reliability into a data-driven decision.
- Runbooks + postmortems make incident response repeatable instead of heroic.

## Approach
1. Demo system: 4-service microservice app (e.g. OpenTelemetry demo or own
   API → worker → DB → cache) on Kubernetes.
2. Telemetry: OpenTelemetry SDK + Collector → Prometheus (metrics), Loki (logs),
   Tempo (traces); exemplars link metric spikes to traces.
3. SLOs defined as code (Sloth/Pyrra): availability 99.9%, p95 latency < 300 ms;
   multi-window multi-burn-rate alerts → Alertmanager → PagerDuty.
4. Grafana dashboards: RED/USE per service, SLO + error-budget panels.
5. Chaos + load: k6 load tests; chaos-mesh/litmus faults (pod kill, latency, DB outage).
6. Incident process: severity matrix, on-call rotation, runbooks linked from every alert,
   3 game-day incidents run end-to-end with blameless postmortems (template + timeline).
7. Alert hygiene: before/after audit of noisy threshold alerts vs SLO alerts.

## Architecture
```
microservices ─OTel SDK─> OTel Collector ─> Prometheus · Loki · Tempo ─> Grafana (SLO/RED/USE)
                                               │
                         Sloth SLO rules ─> burn-rate alerts ─> Alertmanager ─> PagerDuty ─> runbook
k6 load + chaos-mesh faults ─> game days ─> postmortems
```

## Interview-ready core (days 1–2)
Compose/kind demo app with OTel → Prometheus/Loki/Tempo, 2 SLOs with burn-rate alerts to
PagerDuty, one chaos game day with a written postmortem.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Demo app, OTel Collector, Prometheus/Loki/Tempo, Grafana dashboards |
| 2 | SLOs as code, burn-rate alerting → PagerDuty, runbooks |
| 3 | k6 + chaos experiments, 3 game days, postmortems, alert-noise before/after |

## Target metrics (measure; replace with actuals)
- Alert volume during a 1-week simulated load: threshold alerts vs SLO alerts → ≥ 80% fewer pages.
- Detection time for injected faults < 2 min; time from alert to root cause via trace < 5 min.
- 3 game days, 3 blameless postmortems, 10+ runbooks.

## Draft resume bullets
- Built full-stack observability for a microservice system with OpenTelemetry, Prometheus, Loki, Tempo and Grafana, linking metric spikes to traces so root cause was reachable within 5 minutes of an alert.
- Defined availability and latency SLOs as code with multi-window burn-rate alerting to PagerDuty, cutting page volume more than 80% versus threshold alerts while detecting injected faults in under 2 minutes.
- Ran chaos-engineering game days (pod kills, latency and database faults under k6 load) and wrote blameless postmortems and alert-linked runbooks.

## Likely interview questions
- SLI vs SLO vs SLA; how to choose an SLO target; error budget policy.
- Why burn-rate alerts beat threshold alerts.
- Walk me through an incident you handled (use a game day — timeline, comms, mitigation, RCA).
- Metrics vs logs vs traces; cardinality problems in Prometheus.
