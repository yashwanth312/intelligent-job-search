---
id: streamledger
name: "StreamLedger"
tagline: "Event-driven Go microservices on Kafka with tracing and load-tested SLOs"
role_families: [infra, backend, platform, sre]
skills:
  core: [go, microservices, kafka_streaming, otel_tracing]
  supporting: [sql, nosql, capacity_perf, docker, release_eng, rest_api]
  touch: [kubernetes, grafana]
est_days: 3
lab_cost: "$0 — Docker Compose / kind, Redpanda or Kafka, Postgres, Redis, k6"
---

# StreamLedger — Event-Driven Go Microservices on Kafka

## Problem
Synchronous service-to-service calls create cascading failures: one slow dependency and
the whole request chain times out. Moving to events fixes that but introduces new
problems — duplicate messages, ordering, poison messages, and "where did my event go?"
debugging across services.

## Why it matters (impact)
- Decoupled services keep accepting work when a downstream is down (backpressure, not outage).
- Idempotent consumers + outbox pattern give effectively-once processing — no double charges.
- End-to-end tracing across async hops makes debugging minutes instead of hours.
- Load-tested capacity numbers replace guesswork for scaling decisions.

## Approach
1. Domain: simple payments/ledger flow — `orders-api` (Go, REST + gRPC) → Kafka →
   `ledger-svc` (Postgres) → `notifier-svc` (Redis rate limit) → `projection-svc` (read model).
2. Transactional outbox in `orders-api` (Postgres table + relay) → no lost events;
   idempotency keys in consumers → no duplicates; DLQ topic + retry with backoff.
3. Partitioning by account ID for ordering; consumer groups for horizontal scale.
4. OpenTelemetry tracing propagated through Kafka headers → Tempo/Jaeger; RED metrics to Prometheus.
5. Resilience: timeouts, circuit breaker, graceful shutdown with offset commit.
6. k6 load tests: find throughput ceiling, consumer-lag behavior, scale out consumers,
   re-measure; chaos: kill a broker/consumer mid-load and verify no loss/duplication.
7. Release: multi-stage distroless Docker builds, GitHub Actions with `go test -race`,
   golangci-lint, semantic versioned releases; Helm deploy to kind.

## Architecture
```
client ─> orders-api (Go) ─> Postgres + outbox ─relay─> Kafka (partitioned by account)
                                                         ├─> ledger-svc (idempotent) ─> Postgres
                                                         ├─> notifier-svc ─> Redis
                                                         └─> projection-svc ─> read model
OTel traces via Kafka headers ─> Tempo · Prometheus RED ─> Grafana      k6 load + broker-kill chaos
```

## Interview-ready core (days 1–2)
orders-api + ledger-svc in Go with outbox, idempotent consumer, DLQ, and a trace spanning
the Kafka hop; one k6 run with numbers.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Services, Kafka topics, outbox, idempotency, DLQ |
| 2 | OTel tracing through Kafka, metrics, resilience patterns, remaining services |
| 3 | k6 load + chaos tests, scaling experiment, CI (race tests, lint), Helm deploy |

## Target metrics (measure; replace with actuals)
- Sustained N events/s on a laptop-scale cluster with p99 end-to-end < 200 ms.
- 0 lost / 0 duplicated ledger entries across 3 broker/consumer kill tests under load.
- Scaling consumers 1 → 4 increases throughput ~3.5× (partition-bound).
- Trace coverage across all 4 services including async hops.

## Draft resume bullets
- Built event-driven Go microservices on Kafka using a transactional outbox, idempotent consumers and dead-letter topics, verified to produce zero lost or duplicated ledger entries across broker and consumer failures under load.
- Propagated OpenTelemetry traces through Kafka headers for end-to-end visibility across asynchronous hops, with RED metrics in Prometheus and Grafana.
- Load-tested with k6 to find throughput ceilings and consumer-lag behavior, scaling consumers to raise throughput about 3.5× while keeping p99 latency under 200 ms.

## Likely interview questions
- Exactly-once vs at-least-once; why the outbox pattern.
- Kafka partitions, consumer groups, rebalancing, ordering guarantees.
- Goroutines/channels, context cancellation, graceful shutdown in Go.
- How you'd find the bottleneck when consumer lag grows.
