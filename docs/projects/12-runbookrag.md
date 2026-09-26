---
id: runbookrag
name: "RunbookRAG"
tagline: "Retrieval-augmented assistant over internal docs, with an evaluation harness"
role_families: [ai_engineer, genai, mlops, platform]
skills:
  core: [rag, llm, llm_eval, rest_api]
  supporting: [python, typescript_js, sql, docker, ml_platforms]
  touch: [aws, observability]
est_days: 2
lab_cost: "< $5 — Postgres + pgvector (Docker), Claude/Bedrock API for generation, open embedding model"
---

# RunbookRAG — RAG Assistant over Internal Docs, with Evals

## Problem
Engineers and support staff spend hours hunting through Confluence, runbooks and old
tickets for answers that already exist. First-generation "chat with your docs" bots
answer confidently and wrong, with no way to measure whether a change made them better
or worse — so nobody trusts them.

## Why it matters (impact)
- Answers with citations in seconds vs 15–30 min of searching; fewer escalations.
- An eval harness makes quality measurable: every prompt/retrieval change is scored
  before release, like unit tests for an LLM system.
- Access-controlled retrieval keeps restricted docs out of answers.
- Cost and latency tracked per query so it can be run affordably.

## Approach
1. Ingestion: loaders for Markdown, PDF, HTML, Confluence export; structure-aware chunking
   (by heading, 300–800 tokens, overlap), metadata (source, section, ACL group, updated_at).
2. Storage: Postgres + pgvector; hybrid retrieval = BM25 (tsvector) + vector, fused with RRF,
   then cross-encoder rerank.
3. Generation: Claude via API/Bedrock with a grounded prompt — answer only from context,
   cite chunk IDs, say "not found" otherwise.
4. API: FastAPI `/ask` with streaming + a small TypeScript chat UI; per-user ACL filter
   applied at retrieval time.
5. **Eval harness**: 100-question golden set (question, expected answer, expected source);
   metrics: retrieval hit@5, MRR, answer faithfulness + correctness (LLM-as-judge with
   rubric, spot-checked by hand), citation accuracy, refusal correctness on unanswerable
   questions; runs in CI on every change with a regression threshold.
6. Telemetry: tokens, cost, latency per request; prompt caching for the system prompt.
7. Incremental re-index on doc change (content hash).

## Architecture
```
docs ─> loaders ─> chunker ─> embeddings ─> Postgres/pgvector (+tsvector, ACL metadata)
user ─> FastAPI /ask ─> hybrid retrieve (BM25+vector, RRF) ─> rerank ─> Claude (grounded, cited) ─> UI
CI ─> eval harness (golden set: hit@5, MRR, faithfulness, citation acc.) ─> pass/fail vs baseline
```

## Interview-ready core (day 1)
pgvector ingestion + hybrid retrieval + cited answers via FastAPI, and a 50-question eval
set with hit@5 and faithfulness scores.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Ingestion, chunking, pgvector, hybrid retrieval, grounded generation, API |
| 2 | Reranker, ACL filtering, UI, 100-question eval harness in CI, cost/latency telemetry, caching |

## Target metrics (measure; replace with actuals)
- Retrieval hit@5: naive vector baseline → hybrid + rerank (target +15–25 pts).
- Answer faithfulness ≥ 90% on golden set; correct refusal on ≥ 90% of unanswerable questions.
- p95 latency < 4 s; cost per query ≈ $0.00X with prompt caching.
- Eval suite runs in CI in < 5 min and blocks regressions.

## Draft resume bullets
- Built a retrieval-augmented assistant over internal documentation using Postgres/pgvector hybrid search (BM25 plus vectors with reciprocal rank fusion) and cross-encoder reranking, returning cited answers through a streaming FastAPI service.
- Created an evaluation harness with a 100-question golden set measuring retrieval hit@5, faithfulness, citation accuracy and refusal correctness, run in CI to block quality regressions.
- Added per-user access-controlled retrieval, prompt caching and per-request cost and latency telemetry, keeping p95 latency under 4 seconds.

## Likely interview questions
- Chunking strategy trade-offs; why hybrid search beats pure vector search.
- How you evaluate a RAG system; limits of LLM-as-judge.
- How to reduce hallucinations; handling "not in the docs".
- Cost/latency levers: caching, smaller models for routing, rerank depth.
