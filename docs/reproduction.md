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
