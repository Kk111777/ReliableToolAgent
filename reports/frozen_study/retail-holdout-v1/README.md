# Completed retail study: results and limits

**English** | [简体中文](README.zh-CN.md) · [Project overview](../../../README.md)

The fixed 35-task test schedule finished on 2026-10-04: **210/210 first attempts retained**, with 197 valid scores and 13 invalid attempts. **93/105 trial pairs were valid (88.57%)**, below the frozen 90% engineering gate. This is a completed execution schedule with a diagnostic result boundary. The separate 20-task train replication was not started; its 120 planned slots have no model scores. No additional formal attempts were made.

## What was compared

The native Agent, prompt, tools, environment and scoring stayed fixed at benchmark commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619`. Agent and NL evaluator used `openai/qwen3.5-flash-2026-02-23`; the User Simulator used that same snapshot in U0 and `openai/qwen3.8-max-2026-09-02` in U2. Each task had three paired trials with shared seeds. The manifest inside [public_evidence.json](public_evidence.json) contains the actual frozen configuration and source hashes.

| Condition | First attempts | Valid scores | Reward=1 / valid | Reward=1 / planned | Invalid |
|---|---:|---:|---:|---:|---:|
| U0 | 105 | 94 | 48/94 (51.06%) | 48/105 (45.71%) | 11 |
| U2 | 105 | 103 | 93/103 (90.29%) | 93/105 (88.57%) | 2 |

Invalid scores are missing outcomes, not scored reward-zero failures. Rates over planned slots also describe execution coverage. The asymmetry in missingness matters: valid-only rates are not an unbiased comparison of the entire schedule. All 12 pairs without two valid scores are listed in [summary.json](summary.json); first attempts are never replaced by retries.

## Statistical and behavioral diagnostics

The frozen task bootstrap uses only **25 tasks with all three valid trial pairs** (75 pairs). Across that subset, the mean official reward difference U2−U0 is **0.36**, with a 95% task-bootstrap interval **[0.24, 0.48]**. The 93 valid pairs above include partially complete tasks that do not enter this interval. Shared-user-entity clustering gives [0.2533, 0.4815]; excluding the prespecified near-duplicate T38 gives a mean 0.3472 and interval [0.2222, 0.4722] across 24 complete tasks. These sensitivity checks do not resolve missing-outcome bias or model exposure to public tasks.

The [generated report](report.md) preserves the frozen calculations. Its summary includes planned and valid denominators for each WRITE family, per-task coverage, latency, termination, repeat/error counters and candidate events, for both all first attempts and the valid subset. Families are small descriptive subsets. Neither a candidate event nor a changed Simulator score establishes component causality or an improvement to the Agent algorithm.

## Invalid attempts and the expansion stop

The [invalid-attempt catalog](invalid_first_attempts.json) records nine simulation `ValueError` cases, two evaluator `JSONDecodeError` cases and two operational cancellations retained as `timeout/StudyDeadline`. In the nine simulation cases, the last User response ended with `length`, 8194 completion tokens and 8192 reasoning tokens. This is an observed association; the retained logs do not establish the full causal chain. The two evaluator failures followed malformed, fenced JSON outputs. Cancellations during a budget correction retain their original status, usage reservation and first-attempt denominator.

The engineering gate also limits infrastructure/timeout first attempts to 10%; the observed fraction is 13/210 (6.19%). The failed pair-completeness condition is sufficient to stop expansion. The fixed primary queue was finished, while [train replication](../../../benchmark/tau3/studies/retail-replication-v1/README.md) and paid secondary retries were skipped. Frozen generation, scoring and event rules were not changed to repair the result.

## Cases and measurement limits

[Eight reviewed cases](cases.md) cover termination before a WRITE, action-order errors, a successful repeated READ, native lookup recovery, invalid evaluation, truncated User output, partial WRITE completion and operational cancellation. Their [sanitized index](case_index.json) links attempt hashes, message positions and tool counters. Selection was purposive and reviewed by the analyzer author, not random sampling or independent annotation. The earlier 30-trace development panel and its 180 field checks likewise came from the same author.

Two frozen fields need care. `terminal_before_reference_write_candidate` requires that no reference WRITE has succeeded, so it misses a remaining WRITE after partial completion. `agent_after_terminal_user` can be true with no User message; the report interprets it only alongside an actual STOP/TRANSFER marker. Neither field was changed after observing new results.

The toy failed-call Guard was not deployed in native τ³. Its mechanism evidence, Simulator sensitivity and native Agent behavior are separate. This round stops controller expansion: the inspected failures do not establish an independently measured native Guard benefit.

## Usage and cost coverage

This cohort includes 210 formal first attempts and four reused smoke attempts, counted once: 214 attempts and 3747 observed HTTP requests. Known list-price usage totals **RMB 21.929163**; reserving 27 missing-usage requests raises the conservative debit to **RMB 23.0958958**. At the user-confirmed 50% discount these estimates are **RMB 10.9645815** and **RMB 11.5479479**, respectively. They cover this bundle only; earlier preflight and other account activity are excluded. These are estimates, not verified provider invoices.

The generated report separates Agent/User/evaluator requests, known input/output tokens and unknown-usage reserves. Reasoning is already included in output tokens. The manifest's original budget field is historical plan metadata, superseded during execution; it is neither the actual bill nor an authorization to spend that amount.

## Recompute from a public clone

After [local setup](../../../docs/reproduction.md), these commands need no API key or native benchmark checkout:

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

Report output must be a new directory. The audit recomputes aggregates and intervals from compact metrics, and the case audit recomputes tool counters. Full trajectories, argument values and provider credentials remain local. Hashes detect inconsistencies and identify retained evidence; they do not independently authenticate official rewards or semantic interpretations. [Release status](release_status.json) records closure checks, file hashes and the unstarted train disposition as author attestations.
