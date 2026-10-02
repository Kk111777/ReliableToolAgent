# τ³ Retail Evidence Bundle

This directory contains the small, reviewable part of the τ³ retail study used by ReliableToolAgent. It deliberately does **not** vendor the upstream benchmark or publish raw model trajectories.

## Scope

- Upstream repository: `sierra-research/tau2-bench`
- Pinned commit: `b7ea9074c1cba482b30687fecdb5c8425fd6f619`
- Domain: text-based `retail`
- Official Agent, tools, tasks, RetailDB environment, orchestrator, and reward logic were kept unchanged.
- Project additions are limited to fixed launchers, an evaluator parse-retry wrapper for infrastructure stability, and offline observability analysis.

The Qwen User Simulator configuration is a project development setup, not an official τ³ leaderboard submission.

## Contents

```text
benchmark/tau3/
├── README.md
├── results/
│   ├── clean_audit_summary.json
│   └── user_simulator_stability_summary.json
└── scripts/
    ├── evaluator_retry_wrapper.py
    ├── run_clean_u2_retail_20x1.py
    ├── analyze_retail_observability.py
    ├── analyze_clean_u2_failure_audit.py
    ├── run_user_simulator_ablation.py
    ├── analyze_user_simulator_ablation.py
    ├── analyze_user_simulator_u2_pilot.py
    └── analyze_user_simulator_stability.py
```

## Frozen clean-audit configuration

```yaml
agent: openai/qwen3.5-flash-2026-02-23
user_simulator: openai/qwen3.8-max-2026-09-02
nl_evaluator: openai/qwen3.5-flash-2026-02-23
temperature: 0
max_tokens: 512
request_timeout: 60s
request_retries: 3
simulation_timeout: unset
max_steps: 200
runner_retries: 0
concurrency: 1
seed: 300
```

The evaluator wrapper retries only invalid JSON or structured-output parsing, at most twice. It does not alter the trajectory, prompt, model, temperature, reward logic, or select results by reward.

## Reproduce in an independent checkout

The commands below intentionally keep the benchmark environment separate from this repository's toy harness.

```bash
git clone https://github.com/sierra-research/tau2-bench.git
cd tau2-bench
git checkout --detach b7ea9074c1cba482b30687fecdb5c8425fd6f619
uv sync
```

Configure the provider credentials required by LiteLLM, then run the launcher from the τ³ checkout so its relative `data/` paths stay inside that checkout:

```bash
uv run python /absolute/path/to/ReliableToolAgent/benchmark/tau3/scripts/run_clean_u2_retail_20x1.py
```

Generate the exact-call observability outputs:

```bash
uv run python /absolute/path/to/ReliableToolAgent/benchmark/tau3/scripts/analyze_retail_observability.py \
  --input data/simulations/tau3-retail-clean-u2-20x1/results.json \
  --output-dir data/analysis/retail-observability/clean-u2-20x1

uv run python /absolute/path/to/ReliableToolAgent/benchmark/tau3/scripts/analyze_clean_u2_failure_audit.py
```

The launch command makes paid external model calls. The checked-in files under `results/` are the compact evidence snapshot; re-running is not required to review the project.

## Analysis semantics

- Exact duplicate key: `tool_name + canonical_json(arguments)`.
- Same-message duplicate and cross-turn repeat are reported separately.
- No fuzzy or semantic duplicate matching is used.
- Expected WRITE actions are used only in offline analysis and are never exposed to the Agent or User Simulator.
- Infrastructure-invalid simulations are excluded from Agent-behavior rates and recorded separately.

## What is intentionally omitted

- The full upstream τ³ checkout.
- Provider credentials and local environment files.
- Raw trajectories containing long model/tool payloads.
- Claims that the toy Guard improved τ³ performance; that experiment was not run.

For interpretation and limitations, see the [final technical report](../../reports/final_technical_report.md) and [artifact index](../../reports/artifact_index.md).
