# Evidence Index

Each study below links its code and public snapshot to the retained local inputs. Start with the [project overview](../README.md) · [中文](../README.zh-CN.md), or use the [reproduction guide](../docs/reproduction.md) · [中文](../docs/reproduction.zh-CN.md) to check or run the project.

## Phase A — Controlled Toy Pilot

| Experiment | Scope | Public implementation / report | Local raw source of truth |
|---|---|---|---|
| Scripted baseline and fault harness | T01–T05; deterministic fake model | [`local_demo/run.py`](../local_demo/run.py), [`test_smoke.py`](../local_demo/test_smoke.py) | `artifacts/scripted-*.json` |
| Raw error baseline | Historical pilot: 48 task runs | [`pilot.py`](../local_demo/pilot.py), [technical report](final_technical_report.md) | `artifacts/raw-error/` |
| Structured error baseline | Historical pilot: 48 task runs | [`test_structured_errors.py`](../local_demo/test_structured_errors.py), [technical report](final_technical_report.md) | `artifacts/structured-error/` |
| Raw/structured comparison | Historical pilot: 48 paired runs | [`compare_runs.py`](../local_demo/compare_runs.py) | `artifacts/comparison/` |
| Retry-framing 2×2 | E0–E3; 24 runs per condition; 96 total | [`ablation.py`](../local_demo/ablation.py), [`evaluator-v2-ablation-summary.json`](evaluator-v2-ablation-summary.json) | `artifacts/qwen35-flash-ablation/` |
| Per-call logging | Success, failure, parallel-success, parallel-mixed steps | [`test_tool_call_logging.py`](../local_demo/test_tool_call_logging.py) | Generated test trajectories |
| Duplicate Failure Guard V1 | P03–P05; G0/G1 smoke run | [`test_duplicate_guard.py`](../local_demo/test_duplicate_guard.py), [technical report](final_technical_report.md) | `artifacts/qwen35-flash-guard-v1/` |

Important scope boundary: the Guard evidence is a three-task toy smoke run. It is not a completed public-benchmark intervention experiment and is not presented as a τ³ improvement.

The 48-run baselines/paired comparison are historical pilots, distinct from the E0–E3 four-condition ablation. E2 original success is 23/24, whereas the existing v2 rescore is 24/24: one P04/r01 wording correction, with unchanged answer/trajectory. See the [score-version audit](packaging_audit_20261003.md). The original table and v2 JSON remain separately identified.

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

## Presentation and verification (2026-10-03)

| Item | Entry | Scope |
|---|---|---|
| Project overview | [English](../README.md) · [中文](../README.zh-CN.md) | Implementation, result summary, one runtime diagram, one diagnostic chart |
| Setup and reproduction | [English](../docs/reproduction.md) · [中文](../docs/reproduction.zh-CN.md) | Public checks, retained-raw checks, separate benchmark execution |
| Read-only evidence check | [`audit_packaging_evidence.py`](../scripts/audit_packaging_evidence.py) | Public snapshot consistency; optional retained-raw re-analysis and source hashes |
| Presentation snapshot | [`packaging_evidence_20261003.json`](packaging_evidence_20261003.json) | Existing toy, Guard, Simulator, clean-audit values; no new experiment |
| Packaging/source audit | [`packaging_audit_20261003.md`](packaging_audit_20261003.md) | Claim provenance, scoring discrepancy, denominator and interpretation boundaries |
| Simulator figure | [Asset notes](../assets/README.md), [generator](../scripts/build_presentation_assets.py) | Plots existing saved counts; source and figure hashes |
| Documentation checks | [`check_markdown_links.py`](../scripts/check_markdown_links.py) | Local links, Markdown anchors, image existence; no external URL fetches |

Launchers run the studies; analyzers read saved trajectories. Historical pilots and raw inputs remain in their existing locations. `examples/` and most `docs/source/` are inherited upstream framework material.

## Fast review order

1. [README](../README.md)
2. [`final_technical_report.md`](final_technical_report.md)
3. [Reproduction guide](../docs/reproduction.md)
4. [`packaging_audit_20261003.md`](packaging_audit_20261003.md)
5. [`residual_case_T05.md`](residual_case_T05.md)
6. [`local_demo/run.py`](../local_demo/run.py)
7. [`analyze_retail_observability.py`](../benchmark/tau3/scripts/analyze_retail_observability.py)


## Frozen primary release (2026-10-04)

The new test cohort is separate from the historical development results above: 35 tasks, all 210 first attempts retained, 197 valid scores and 13 invalid attempts. Valid pairs were 93/105, below the frozen engineering gate; the 20-task train plan was not started and has no model scores.

| Public artifact | What it supports | Retained local input |
|---|---|---|
| [Results and limits](frozen_study/retail-holdout-v1/README.md) · [中文](frozen_study/retail-holdout-v1/README.zh-CN.md) | Final interpretation and disposition | Completed first-attempt schedule |
| [Compact bundle](frozen_study/retail-holdout-v1/public_evidence.json) | Offline identity, source, aggregate, interval and usage checks | `artifacts/frozen_study/retail-holdout-v1c/attempts.jsonl` and per-attempt outcome/simulation/request files |
| [Generated summary](frozen_study/retail-holdout-v1/summary.json) | Every missing pair, task/family denominators and frozen diagnostics | Audited compact bundle |
| [Case index](frozen_study/retail-holdout-v1/case_index.json) | Attempt/source matching and tool-counter recomputation | Same-author raw review; positions and semantics cannot be authenticated from hashes alone |
| [Invalid attempts](frozen_study/retail-holdout-v1/invalid_first_attempts.json) | Original classes, request metadata and cancellation annotations | Retained calls and outcomes |
| [Release status](frozen_study/retail-holdout-v1/release_status.json) | Author closure attestation, artifact hashes and unstarted train disposition | Local locks, finished jobs and raw hash checks |

No paid secondary retries were made. Complete raw logs, datasets, account balances and credentials remain outside Git. The manifest's old budget cap is historical metadata, not the actual bill or current spending authority.
