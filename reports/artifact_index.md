# Artifact Index

This index separates files intended for GitHub review from raw local artifacts. Raw model trajectories are retained locally but omitted from the repository because they are large, provider-generated, and unnecessary for a first-pass code review.

## Phase A — Controlled Toy Pilot

| Experiment | Scope | Public implementation / report | Local raw source of truth |
|---|---|---|---|
| Scripted baseline and fault harness | T01–T05; deterministic fake model | [`local_demo/run.py`](../local_demo/run.py), [`test_smoke.py`](../local_demo/test_smoke.py) | `artifacts/scripted-*.json` |
| Raw error baseline | 48 task runs | [`pilot.py`](../local_demo/pilot.py), [technical report](final_technical_report.md) | `artifacts/raw-error/` |
| Structured error baseline | 48 task runs | [`test_structured_errors.py`](../local_demo/test_structured_errors.py), [technical report](final_technical_report.md) | `artifacts/structured-error/` |
| Raw/structured comparison | Paired 48-run comparison | [`compare_runs.py`](../local_demo/compare_runs.py) | `artifacts/comparison/` |
| Retry-framing 2×2 | E0–E3; 24 runs per condition; 96 total | [`ablation.py`](../local_demo/ablation.py), [`evaluator-v2-ablation-summary.json`](evaluator-v2-ablation-summary.json) | `artifacts/qwen35-flash-ablation/` |
| Per-call logging | Success, failure, parallel-success, parallel-mixed steps | [`test_tool_call_logging.py`](../local_demo/test_tool_call_logging.py) | Generated test trajectories |
| Duplicate Failure Guard V1 | P03–P05; G0/G1 smoke run | [`test_duplicate_guard.py`](../local_demo/test_duplicate_guard.py), [technical report](final_technical_report.md) | `artifacts/qwen35-flash-guard-v1/` |

Important scope boundary: the Guard evidence is a three-task toy smoke run. It is not a completed public-benchmark intervention experiment and is not presented as a τ³ improvement.

## Phase B — τ³ Public Benchmark Migration

| Item | Public evidence | Local source of truth |
|---|---|---|
| Upstream benchmark | Repository `sierra-research/tau2-bench`, commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619` | `tau2-bench-baseline/` detached checkout |
| Clean 20×1 launcher | [`run_clean_u2_retail_20x1.py`](../benchmark/tau3/scripts/run_clean_u2_retail_20x1.py) | Same script in the pinned checkout during execution |
| Evaluator parse stabilization | [`evaluator_retry_wrapper.py`](../benchmark/tau3/scripts/evaluator_retry_wrapper.py) | `data/simulations/*/evaluator_retry.json` |
| Exact-call observability | [`analyze_retail_observability.py`](../benchmark/tau3/scripts/analyze_retail_observability.py) | `data/analysis/retail-observability/` |
| Packaging and reproduction notes | [τ³ evidence bundle](../benchmark/tau3/README.md) | Independent `.venv` managed by `uv` |

The launcher fixed model/runtime parameters and the wrapper retried only malformed evaluator output. Neither changed the official Agent policy, tools, tasks, RetailDB environment, orchestrator, or evaluator scoring.

## Phase C — User Simulator Confound Study

| Item | Public evidence | Local raw source of truth |
|---|---|---|
| U0/U2 launcher | [`run_user_simulator_ablation.py`](../benchmark/tau3/scripts/run_user_simulator_ablation.py) | `data/simulations/tau3-retail-user-simulator-ablation-*/` |
| Offline diagnostic logic | [`analyze_user_simulator_ablation.py`](../benchmark/tau3/scripts/analyze_user_simulator_ablation.py) | Generated analysis JSON/Markdown |
| Three-trial stability aggregation | [`analyze_user_simulator_stability.py`](../benchmark/tau3/scripts/analyze_user_simulator_stability.py) | `data/analysis/retail-observability/user-simulator-stability-0-4/` |
| Compact result snapshot | [`user_simulator_stability_summary.json`](../benchmark/tau3/results/user_simulator_stability_summary.json) | `per_trial_metrics.json` and `stability_report.md` in the local analysis directory |

Fixed Agent: `openai/qwen3.5-flash-2026-02-23`

U0 User Simulator: `openai/qwen3.5-flash-2026-02-23`

U2 User Simulator: `openai/qwen3.8-max-2026-09-02`

This is a development diagnostic comparison, not an official τ³ leaderboard comparison or a general model ranking.

## Phase D — Clean Public Benchmark Audit

| Item | Public evidence | Local raw source of truth |
|---|---|---|
| Frozen config and aggregate metrics | [`clean_audit_summary.json`](../benchmark/tau3/results/clean_audit_summary.json) | `data/simulations/tau3-retail-clean-u2-20x1/clean_config.json` |
| General observability metrics | [`analyze_retail_observability.py`](../benchmark/tau3/scripts/analyze_retail_observability.py) | `task_metrics.json`, `summary.json`, and case files under the local analysis directory |
| Agent completion analysis | [`analyze_clean_u2_failure_audit.py`](../benchmark/tau3/scripts/analyze_clean_u2_failure_audit.py) | `agent_completion_metrics.json`, `agent_completion_summary.json` |
| Residual reward-zero case | [`residual_case_T05.md`](residual_case_T05.md) | T05 trajectory in local `results.json` |
| Full interpretation | [`final_technical_report.md`](final_technical_report.md) | All retained local trajectories and evaluator records |

Clean-audit local paths:

```text
tau2-bench-baseline/data/simulations/tau3-retail-clean-u2-20x1/results.json
tau2-bench-baseline/data/simulations/tau3-retail-clean-u2-20x1/evaluator_retry.json
tau2-bench-baseline/data/analysis/retail-observability/clean-u2-20x1/
```

T04 is infrastructure-invalid and excluded from Agent-behavior rates. T05 is the only valid reward-zero residual case; no repair method was implemented after the audit.

## Fast review order

1. [`final_technical_report.md`](final_technical_report.md)
2. [τ³ evidence bundle](../benchmark/tau3/README.md)
3. [`clean_audit_summary.json`](../benchmark/tau3/results/clean_audit_summary.json)
4. [`residual_case_T05.md`](residual_case_T05.md)
5. [`evaluator-v2-ablation-summary.json`](evaluator-v2-ablation-summary.json)
6. [`local_demo/run.py`](../local_demo/run.py)
7. [`analyze_retail_observability.py`](../benchmark/tau3/scripts/analyze_retail_observability.py)
