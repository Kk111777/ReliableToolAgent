# τ³ Retail Study

The study uses the native τ³ Agent and orchestrator. This directory contains the project launchers, an evaluator parse-retry wrapper, offline analyzers, and saved result snapshots. The benchmark checkout and raw trajectories are kept separately.

## Review the Saved Results

| Study | Scope | Snapshot |
|---|---|---|
| Fixed-Agent Simulator diagnostic | Five tasks × three valid trials per condition | [Simulator summary](results/user_simulator_stability_summary.json) |
| Clean retail audit | Twenty attempts, nineteen valid runs | [Audit summary](results/clean_audit_summary.json) |

The [technical report](../../reports/final_technical_report.md) explains the results. The [source audit](../../reports/packaging_audit_20261003.md) records scoring versions and invalid-trial handling; [T05](../../reports/residual_case_T05.md) traces the remaining valid reward-zero run.

## Frozen clean-audit configuration

Upstream: `sierra-research/tau2-bench`, commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619`, text-based retail, `base` task split.

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

The official Agent, tools, tasks, RetailDB environment, orchestrator, and reward rules are unchanged. The external wrapper adds at most two retries for malformed evaluator output, keeping the same prompt, model, generation settings, and parser. This changes infrastructure handling, not scoring rules.

## Benchmark Environment

Use a separate checkout and environment from the toy harness:

```bash
git clone https://github.com/sierra-research/tau2-bench.git
cd tau2-bench
git checkout --detach b7ea9074c1cba482b30687fecdb5c8425fd6f619
uv sync
```

Run the following commands from that checkout. Its relative `data/` paths are used for saved simulations and analysis output. Replace `/absolute/path/to/ReliableToolAgent` with the project checkout's path.

## Analyze Saved Trajectories

These commands require retained simulation files. They make no model calls and write derived analysis reports.

```bash
uv run python /absolute/path/to/ReliableToolAgent/benchmark/tau3/scripts/analyze_retail_observability.py \
  --input data/simulations/tau3-retail-clean-u2-20x1/results.json \
  --output-dir data/analysis/retail-observability/clean-u2-20x1

uv run python /absolute/path/to/ReliableToolAgent/benchmark/tau3/scripts/analyze_clean_u2_failure_audit.py
```

For the Simulator study, use [the diagnostic analyzer](scripts/analyze_user_simulator_ablation.py) and [three-trial aggregation](scripts/analyze_user_simulator_stability.py). The [evidence index](../../reports/artifact_index.md) lists their inputs.

## Run a New Evaluation

Configure the provider credentials required by LiteLLM, then run:

```bash
uv run python /absolute/path/to/ReliableToolAgent/benchmark/tau3/scripts/run_clean_u2_retail_20x1.py
```

The launcher makes paid external model calls. It is not needed to review the checked-in results. The Qwen User Simulator is a project development configuration, not an official leaderboard submission; the toy Guard is not part of this run.

## Analysis Definitions

- Calls match by `tool_name + canonical_json(arguments)`. Same-message duplicates and cross-turn repeats are counted separately, without fuzzy matching.
- Expected WRITE actions come from reward metadata for offline analysis; they are not exposed to the Agent or User Simulator.
- Infrastructure-invalid runs remain in attempted counts and are excluded from Agent-behavior rates.
- Tool errors, Simulator terminal signals, and evaluator failures are reported separately. The analyzer does not infer hidden model reasoning or assign a causal explanation from reward alone.

For project setup and public-file checks, see the [reproduction guide](../../docs/reproduction.md) · [中文](../../docs/reproduction.zh-CN.md).

## Paired Holdout Extension

The [paired holdout guide](studies/retail-holdout-v1/README.md) · [中文](studies/retail-holdout-v1/README.zh-CN.md) describes the frozen 35-task U0/U2 follow-up, measurement fixtures, attempt ledger, bounded worker, usage observation, and paired bootstrap. Use `run_frozen_study.py` for this study; the historical launchers above remain unchanged.

The [stratified replication](studies/retail-replication-v1/README.md) · [中文](studies/retail-replication-v1/README.zh-CN.md) adds a separately reported 20-task train sample. Both cohorts use fixed paired trials and a shared execution supervisor.
