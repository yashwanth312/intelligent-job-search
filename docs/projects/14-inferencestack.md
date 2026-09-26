---
id: inferencestack
name: "InferenceStack"
tagline: "Self-hosted LLM inference platform on Kubernetes GPUs — vLLM, autoscaling, MLOps"
role_families: [mlops, ai_infra, platform, ai_engineer]
skills:
  core: [gpu_inference, mlops, kubernetes, ml_frameworks]
  supporting: [llm, ml_platforms, prometheus, capacity_perf, docker, helm, data_pipeline]
  touch: [finops, storage]
est_days: 3
lab_cost: "$10–25 — spot GPU on RunPod/Lambda Labs/GKE for a few hours; CPU fallback with small models on kind"
---

# InferenceStack — Self-Hosted LLM Inference on Kubernetes

## Problem
Companies moving from API-based LLMs to self-hosted open models (for cost, data residency
or latency) hit infra problems quickly: GPUs are expensive and sit idle, naive serving
gets a fraction of the possible throughput, model versions are deployed by hand, and
nobody knows the cost per 1,000 tokens.

## Why it matters (impact)
- Continuous batching (vLLM) gives several times the throughput of naive HF serving on the
  same GPU → far lower cost per token.
- Queue-depth autoscaling with scale-to-zero stops paying for idle GPUs.
- Model registry + canary rollout makes model updates as safe as app deploys.
- Measured $/1M tokens vs a hosted API gives a real build-vs-buy answer.

## Approach
1. Kubernetes with a GPU node pool (GKE or RunPod k8s; NVIDIA device plugin / GPU operator);
   CPU fallback path with a small model on kind for local dev.
2. Serving: vLLM OpenAI-compatible server for an open model (e.g. Llama/Qwen 7–8B, AWQ
   quantized), packaged as a Helm chart; model weights cached on a PVC / object storage.
3. Gateway: LiteLLM or small FastAPI router — auth, rate limits, per-tenant usage,
   fallback to hosted API when saturated.
4. Autoscaling: KEDA on queue depth / `vllm:num_requests_waiting`, scale-to-zero off hours.
5. MLOps: MLflow model registry (versions, eval scores, lineage); promotion pipeline:
   register → eval (accuracy set + latency benchmark) → canary 10% → full.
6. Observability: Prometheus + Grafana for tokens/s, TTFT, p95 latency, GPU util/memory (DCGM exporter).
7. Benchmark report: naive HF transformers vs vLLM; FP16 vs AWQ; cost per 1M tokens vs hosted API.

## Architecture
```
clients ─> gateway (auth, rate limit, usage, fallback) ─> vLLM pods (GPU node pool, Helm)
                                                              ▲ KEDA (queue depth, scale-to-zero)
MLflow registry ─> eval + benchmark ─> canary ─> promote        DCGM + Prometheus ─> Grafana (TTFT, tok/s, GPU%)
```

## Interview-ready core (days 1–2)
vLLM on a GPU node via Helm, gateway, Grafana dashboard for TTFT/tokens-per-second/GPU
utilization, and the HF-vs-vLLM throughput benchmark.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | GPU cluster, vLLM Helm chart, model cache, benchmarks |
| 2 | Gateway, KEDA autoscaling + scale-to-zero, DCGM/Prometheus/Grafana |
| 3 | MLflow registry, eval-gated promotion + canary, cost-per-token report |

## Target metrics (measure; replace with actuals)
- Throughput: vLLM vs naive HF serving on same GPU (target ≥ 5× tokens/s at concurrency 32).
- AWQ quantization: ~60% less GPU memory with < 2 pt eval drop.
- p95 TTFT < 500 ms at target load; scale-to-zero idle cost $0.
- Measured $/1M tokens vs hosted API at given utilization.

## Draft resume bullets
- Built a self-hosted LLM inference platform on Kubernetes GPU nodes with vLLM packaged as a Helm chart, delivering over 5× the throughput of naive Hugging Face serving on the same GPU.
- Implemented KEDA queue-depth autoscaling with scale-to-zero and a gateway handling auth, rate limits, per-tenant usage and fallback to a hosted API, with GPU, time-to-first-token and throughput dashboards via DCGM and Prometheus.
- Added an MLflow model registry with evaluation-gated canary promotion and published a cost-per-million-tokens comparison, including AWQ quantization cutting GPU memory about 60%.

## Likely interview questions
- What continuous batching and PagedAttention do; why KV cache dominates memory.
- TTFT vs inter-token latency; what drives each.
- How you'd size GPUs for a given QPS and context length.
- Quantization trade-offs (AWQ/GPTQ/FP8).
