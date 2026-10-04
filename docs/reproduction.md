# Reproduction Guide

**English** | [简体中文](reproduction.zh-CN.md) · [Project overview](../README.md)

The project has three different checks. Choose the one that matches the files and credentials you have.

| Goal | Required inputs | Model API calls |
|---|---|---|
| Check the published evidence and deterministic tests | This repository and its local Python environment | None |
| Recheck the recorded experiments | Retained raw trajectories and existing rescores | None |
| Run the τ³ study again | A separate pinned benchmark checkout and provider credentials | Yes |

## Set up the project environment

Install `uv` and use Python 3.12. From a fresh clone:

```bash
git clone https://github.com/Kk111777/ReliableToolAgent.git
cd ReliableToolAgent
bash setup-local.sh
```

The setup script creates `.venv` with Python 3.12.14, installs `requirements-local.lock`, and checks dependencies. Use `.venv/bin/python` below so the commands run with that environment.

## Check the public files

```bash
.venv/bin/python -m pytest -q local_demo
.venv/bin/python scripts/audit_packaging_evidence.py
.venv/bin/python scripts/check_markdown_links.py
```

The tests cover the scripted fault harness, error handling, per-call logging, and Guard behavior. They use no model API. The evidence check compares public snapshots, scoring versions, and figure provenance. The Markdown check verifies local document links, anchors, and images without fetching external URLs.

A fresh clone contains compact result snapshots, not the raw model trajectories. These commands check the implementation and published files; they do not independently recompute all experimental results or rerun the benchmark.

The separate [upstream regression workflow](../.github/workflows/tests.yml) runs Python 3.10 and 3.12 in fresh CI environments with uv 0.12.23. Parent tests and Python subprocesses use the same activated environment. It requires a prebuilt `tokenizers` wheel because an earlier resolution selected 0.10.3 and failed its Rust source build on Python 3.12. The [uv package option](https://docs.astral.sh/uv/reference/cli/#uv-pip-install) lets the resolver choose compatible wheels without overriding dependency requirements. Check each matrix job's pytest result; resolving dependencies alone does not establish a passed regression suite.

## Inspect retained raw evidence

For the original local workspace, the [evidence index](../reports/artifact_index.md) lists the raw paths. The complete audit needs:

```text
artifacts/qwen35-flash-ablation/
artifacts/rescored/ablation/
artifacts/qwen35-flash-guard-v1/
tau2-bench-baseline/data/simulations/
tau2-bench-baseline/data/analysis/retail-observability/
```

```bash
.venv/bin/python scripts/audit_packaging_evidence.py --local
.venv/bin/python -m local_demo.compare_ablation --task-id P03 --repeat 1
```

The first command recalculates recorded aggregates, compares original and existing v2 scores, and checks source hashes. The second prints a selected ablation trace comparison. Both read retained files without modifying them.

Original E2 task success is 23/24; the existing evaluator-v2 rescore is 24/24 for the same answers and trajectories. The [scoring audit](../reports/packaging_audit_20261003.md#discrepancy-original-e2-versus-evaluator-v2) explains the wording correction. Keep the two versions separate when reporting results.

## Run or analyze τ³

Follow the [τ³ guide](../benchmark/tau3/README.md) for the pinned commit, model configuration, independent environment, launchers, and offline analyzers. The launchers make paid model calls; offline analyzers read saved simulations and write derived analysis reports. The project environment above is separate from the benchmark environment.

The [technical report](../reports/final_technical_report.md#13-limitations) covers the development subset, Simulator configuration, evaluator retries, and unavailable cost estimates. To regenerate the figure from saved counts, use the [asset guide](../assets/README.md).

## Check the paired holdout protocol

The [holdout guide](../benchmark/tau3/studies/retail-holdout-v1/README.md) explains the new task selection, first-attempt denominators, output limits, request-cost records, and task-level bootstrap. These public checks run without API access:

```bash
.venv/bin/python -m pytest -q benchmark/tau3/tests
.venv/bin/python benchmark/tau3/scripts/audit_frozen_study.py
```

The 30 development inspection traces and 12 synthetic protocol fragments check event measurement. They are not additional benchmark outcomes or independent human annotations. Formal-run compact metrics, when published, support offline aggregate recomputation; full official reward verification still needs the local raw trajectories.

The [separate stratified train plan](../benchmark/tau3/studies/retail-replication-v1/README.md) remains unstarted because the primary pair-completeness gate failed. Planned tasks are not observed results.

The [compact evidence commands](../benchmark/tau3/studies/retail-holdout-v1/README.md#compact-evidence-checks) separate local raw verification/export from public offline aggregate checks. The audit verifies identities, source versions, billing coverage and recomputed summaries; it does not call a model or independently rescore private trajectories. The [completed primary bundle](../reports/frozen_study/retail-holdout-v1/README.md) is now available: 210 first attempts retained, below engineering acceptance. The planned train cohort was not started and has no model scores.

The [cohort report guide](study_results.md) generates matching English and Chinese reports from one audited bundle. It keeps first attempts, additional attempts and unstarted slots visible, including the boundary for a study stopped by budget or engineering conditions.


Recorded paid execution uses the [budgeted resume guide](budgeted_execution.md). It separates original list prices, confirmed discounts, reported balances and missing-usage reservations; old manifest caps are historical. The default command makes no model calls.


## Recompute the released cohort

```bash
.venv/bin/python benchmark/tau3/scripts/study_evidence.py audit \
  --input reports/frozen_study/retail-holdout-v1/public_evidence.json
.venv/bin/python benchmark/tau3/scripts/audit_study_cases.py \
  --evidence reports/frozen_study/retail-holdout-v1/public_evidence.json \
  --cases reports/frozen_study/retail-holdout-v1/case_index.json
.venv/bin/python benchmark/tau3/scripts/report_study_evidence.py \
  --input reports/frozen_study/retail-holdout-v1/public_evidence.json \
  --output artifacts/recomputed-retail-holdout
```

Use a new output directory. The three generated files (`summary.json`, `report.md`, `report.zh-CN.md`) should match the published files byte for byte. This checks compact aggregation and case counters without raw data or paid calls; it does not independently validate the original official rewards.


## Engineering repairs v2

See [interfaces and response recovery](engineering_v2.md) and [public offline checks](../reports/engineering-v2/README.md). The revision does not rewrite the frozen cohort.
