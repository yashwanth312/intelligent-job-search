---
id: opsagent
name: "OpsAgent"
tagline: "Tool-calling AI agent for incident triage over MCP, with guardrails and evals"
role_families: [ai_engineer, genai, sre, platform]
skills:
  core: [agents, llm, llm_eval, rest_api]
  supporting: [incident_response, observability, kubernetes, typescript_js, python]
  touch: [secrets_mgmt, postmortem]
est_days: 2
lab_cost: "< $5 — Claude API, kind cluster, Prometheus/Loki (reuse PagerZero stack if built)"
---

# OpsAgent — AI Incident Triage Agent over MCP

## Problem
When an alert fires at 3 a.m., the first 15–20 minutes are always the same: check
dashboards, grep logs, look at recent deploys, check pod status, find the runbook.
It's mechanical, slow, and error-prone for a sleepy on-call engineer — and giving an AI
unrestricted `kubectl` access to do it for you is dangerous.

## Why it matters (impact)
- Automated first-pass triage delivers a root-cause hypothesis + evidence in ~1 minute,
  cutting MTTR on common incidents.
- Read-only tools by default, human approval for any write action, full audit log —
  safe to put near production.
- Eval suite of replayed incidents proves the agent actually helps before anyone relies on it.

## Approach
1. MCP servers (Python or TypeScript) exposing scoped tools:
   `query_prometheus`, `search_logs` (Loki), `k8s_describe` / `k8s_events` (read-only RBAC
   service account), `recent_deploys` (Argo/GitHub), `find_runbook` (RunbookRAG if built).
2. Agent loop with Claude tool use: alert webhook → plan → call tools → summarize
   hypothesis, evidence (with links), confidence, suggested next step → post to Slack.
3. Guardrails: allowlisted read-only tools; write tools (`rollout_restart`, `scale`) require
   human approval via Slack button; token/step budget; PII/secret redaction on tool output;
   every call audit-logged.
4. Eval harness: 15 recorded incident scenarios (OOMKill, bad deploy, DB connection
   exhaustion, cert expiry, DNS failure…) with known root cause → score root-cause accuracy,
   steps taken, cost, time.
5. Cost controls: small model for routing/summarizing tool output, larger model for final
   reasoning; prompt caching.

## Architecture
```
Alertmanager webhook ─> OpsAgent (Claude tool use loop, step/token budget)
        ├─ MCP: Prometheus · Loki · K8s (read-only RBAC) · deploy history · runbooks
        ├─ guardrails: allowlist · approval for writes · redaction · audit log
        └─> Slack: hypothesis + evidence + confidence  [Approve restart?]
eval: 15 replayed incidents ─> root-cause accuracy · steps · cost · latency
```

## Interview-ready core (day 1)
3 MCP tools (Prometheus, Loki, K8s read-only), agent loop producing a triage summary for
5 injected incidents, with an audit log.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | MCP servers, agent loop, Slack output, audit log |
| 2 | Approval-gated write tools, redaction, 15-scenario eval harness, model routing + caching |

## Target metrics (measure; replace with actuals)
- Root-cause accuracy on 15 replayed incidents ≥ 80%.
- Median time to triage summary < 90 s; cost per triage ≈ $0.0X.
- 0 unapproved write actions (enforced + tested); 100% tool calls audit-logged.

## Draft resume bullets
- Built an AI incident-triage agent using Claude tool calling and Model Context Protocol servers for Prometheus, Loki and read-only Kubernetes access, producing an evidence-backed root-cause hypothesis within 90 seconds of an alert.
- Designed guardrails for production safety: allowlisted read-only tools, human approval in Slack for any write action, secret redaction, step and token budgets, and a full audit log.
- Evaluated the agent against 15 replayed incident scenarios, reaching over 80% root-cause accuracy, and cut per-triage cost with model routing and prompt caching.

## Likely interview questions
- Agent vs workflow — when you'd not use an agent.
- How MCP works (client/server, tools/resources) and why it's useful.
- Preventing prompt injection from log content reaching tool calls.
- How you evaluate a non-deterministic agent.
