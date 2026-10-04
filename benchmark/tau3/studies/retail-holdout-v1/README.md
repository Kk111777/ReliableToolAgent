# Paired Retail Holdout Study

**English** | [简体中文](README.zh-CN.md)

This study checks whether the earlier User Simulator diagnostic carries over to retail tasks that had not appeared in the retained local runs. The native Agent, its prompt, the retail tools, environment, and official scoring stay fixed. U0 uses Qwen3.5 Flash as the User Simulator; U2 uses Qwen3.8 Max. This is an evaluation-sensitivity study, not a claim that the Agent has improved.

## Released status

The [final cohort](../../../../reports/frozen_study/retail-holdout-v1/README.md) retained all 210 formal first attempts on 2026-10-04: 197 valid scores, 13 invalid attempts and zero additional formal attempts. Valid pair coverage was 93/105 (88.57%), below the frozen 90% engineering threshold. The fixed schedule is complete; train replication and paid secondary retries were not started. The effective manifest in the public bundle identifies the actual run; this page retains the original design.

## Frozen design

| Item | Setting |
|---|---|
| Benchmark | `sierra-research/tau2-bench`, `b7ea9074c1cba482b30687fecdb5c8425fd6f619` |
| Tasks | 35 remaining official retail test IDs after excluding IDs seen in retained local runs |
| Pairing | Three trials per task, identical seeds across U0/U2; 105 pairs, 210 planned primary slots |
| Order | Alternate U0/U2 order within successive task/trial pairs; serial execution |
| Agent and NL evaluator | `openai/qwen3.5-flash-2026-02-23` |
| User Simulator | U0: the same Flash snapshot; U2: `openai/qwen3.8-max-2026-09-02` |
| Generation | `temperature=0`, `max_tokens=512`, `max_completion_tokens=8192` |
| Limits | Request timeout 60s, request retries 3, evaluator parse retries 2, 200 steps |
| Whole attempt | 600s including evaluation; parent cancellation saves the partial trajectory |
| Additional attempts | At most ten infrastructure reruns, separate attempt IDs; no rerun of scored failures |

The [manifest](manifest.json) freezes the schedule, source hashes, analyzer version, prices, limits, and stop rules before formal execution. An initial smoke request revealed that `max_tokens` did not bound reasoning output. That attempt is retained separately. The revised protocol adds a total-output bound; it is not pooled with historical runs that had neither this bound nor the whole-attempt deadline. [Provider parameter reference](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions).

“Holdout” means unseen in retained local runs. These are public benchmark tasks, so model-training exposure is unknown. The [task audit](task_audit.json) records scenario hashes, nearest development tasks, write families, and shared user entities. T36 and T38 share a scenario template and order but require different outcomes. Both remain in the primary set; a user-entity-cluster bootstrap and a prespecified analysis excluding T38 check sensitivity to this dependence.

## Measurement checks

The [measurement panel](measurement_panel.json) contains 30 compact development trajectories and inspection labels. The [audit](measurement_audit.json) checks 180 fields; its selected panel has eight positive and 22 negative terminal-confirmation candidates. These labels came from Codex trace inspection by the same author who implemented the analyzer. This is an implementation audit, not independent human annotation or an estimate of accuracy on new tasks.

Twelve [synthetic protocol fragments](../../tests/fixtures/event_fragments.json) cover explicit error flags, missing results, duplicate batches, reused IDs, changed arguments, confirmations, and changed requests. They add no benchmark tasks. Tool responses match call IDs only within the following response window; missing or ambiguous matches remain unknown. Text containing “failed” is insufficient evidence of a tool error.

Official final/DB reward is reported separately from reference-action coverage. A missing expected WRITE may indicate an unfinished request, an alternative valid path, or a policy constraint. Confirmation words and terminal markers produce candidate events for inspection, not ground-truth failure causes.

## Run and inspect

From the project root, these checks require no credentials and make no model calls:

```bash
.venv/bin/python -m pytest -q benchmark/tau3/tests
.venv/bin/python benchmark/tau3/scripts/audit_frozen_study.py
.venv/bin/python benchmark/tau3/scripts/run_frozen_study.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --output artifacts/frozen_study/retail-holdout-v1c --phase formal
```

The following original-run commands are retained for historical smoke/replay context. Resume of the recorded study must use the [external budget policy](../../../../docs/budgeted_execution.md), because the original saved cap is obsolete. For paid execution, keep a separate pinned checkout at `tau2-bench-baseline/` with its own `.venv`. Put `OPENAI_API_KEY` and `OPENAI_API_BASE` in the project root's ignored `.env`. The runner reads credentials only with `--run`, then invokes the benchmark interpreter:

```bash
.venv/bin/python benchmark/tau3/scripts/run_frozen_study.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --output artifacts/frozen_study/retail-holdout-v1c --phase smoke --run

.venv/bin/python benchmark/tau3/scripts/run_frozen_study.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --output artifacts/frozen_study/retail-holdout-v1c --phase formal --run

.venv/bin/python benchmark/tau3/scripts/analyze_frozen_study.py \
  --input artifacts/frozen_study/retail-holdout-v1c \
  --output artifacts/frozen_study/retail-holdout-v1c/analysis
```

Repeating a runner command resumes missing slots without repeating paid attempts. `--retry-infrastructure` creates new attempts for infrastructure failures only. Original attempts remain in the ledger. A process lock rejects simultaneous runners; immutable job/outcome files and artifact hashes catch changed evidence.

Each attempt retains `identity.json`, `job.json`, `simulation.json`, `calls.jsonl`, `requests.jsonl`, optional evaluator records, and `outcome.json`. The parent appends `attempts.jsonl` and updates `status.json`. Request usage distinguishes Agent, User, and evaluator calls, including invalid evaluator output and observable SDK retries. No request prompts, headers, keys, or provider exception messages enter the billing ledger.

## Replay from a new clone

The original manifest also fingerprints private historical trajectories used to audit local exposure. Those are provenance inputs, not inputs to the native Agent. After preparing the pinned benchmark checkout, create a distinct replay manifest that keeps the historical hashes as provenance and verifies the public/runtime sources:

```bash
.venv/bin/python benchmark/tau3/scripts/prepare_frozen_replay.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --study-id my-retail-replay --output artifacts/my-retail-replay/manifest.json
```

Then use that manifest and a new output directory with the runner commands above. Preparation makes no API calls. A replay needs its own four smoke attempts and produces new outputs and fees; it is not the recorded original experiment. Check dated provider prices before a later paid replay.

## Analysis and stop rules

- Primary analysis uses first attempts. Report success over valid first attempts and over all planned slots; show infrastructure failures and timeouts explicitly. Restored valid runs are secondary.
- Confidence intervals resample tasks with all three trial pairs together: 5,000 draws, seed `20261003`. Shared-entity and task-family sensitivity results accompany the primary interval.
- At least 90% valid trial pairs and at most 10% infrastructure/timeout first attempts form an engineering gate, not a significance test. Missing pairs and incomplete three-trial tasks remain visible.
- Prices come from the [provider's Beijing price table](https://help.aliyun.com/zh/model-studio/model-pricing). Known returned usage uses list prices, including reasoning output. Missing usage and unfinished requests retain a conservative reservation. Estimates are not a verified invoice or account balance.
- The historical manifest records a RMB 300 cap; this has been superseded for operational execution. The external policy uses the confirmed discount, current authorized balance and historical request reserves. The original limit of at most 224 simulation attempts remains. Three consecutive infrastructure/deadline failures stop execution for diagnosis.
- Holdout outcomes do not tune the Agent, Guard, prompt, or event rules. A new recovery mechanism needs a separate hypothesis and evaluation set; fewer than five distinct tasks with the target failure stops controller expansion.

Full trajectories remain local. Published compact metrics support recomputing aggregates and confidence intervals; they do not independently verify every official reward. The selected development fragments support checking the event analyzer without API access.

## Compact evidence checks

[`study_evidence.py`](../../scripts/study_evidence.py) exports an immutable compact bundle after checking retained outcome, trajectory and request hashes. Its offline `audit` command recomputes the frozen aggregates, task-level intervals, missing-slot list, latency and usage by role. Input and completion tokens are counted only where usage was returned; reasoning tokens are a part of completion tokens. Missing usage keeps its budget reservation and is reported separately. Checksums identify files and detect inconsistencies; they do not authenticate a reward without the private trajectory.

The [released compact bundle](../../../../reports/frozen_study/retail-holdout-v1/public_evidence.json) contains all 210 first attempts and four smoke attempts. A public clone can audit that file directly. To export a new bundle from retained local raw evidence:

```bash
.venv/bin/python benchmark/tau3/scripts/study_evidence.py export \
  --input artifacts/frozen_study/retail-holdout-v1c \
  --output artifacts/frozen_study/retail-holdout-v1c/public_evidence.json

.venv/bin/python benchmark/tau3/scripts/study_evidence.py audit \
  --input artifacts/frozen_study/retail-holdout-v1c/public_evidence.json
```

Export requires the retained local evidence. Audit needs only the compact bundle and its matching public source version, without model credentials or the native benchmark checkout. The default export rejects incomplete studies and existing output files. `--allow-incomplete` is an explicit local diagnostic option; it labels the result incomplete and lists unstarted slots. The [contract tests](../../tests/test_study_evidence.py) exercise corrupted identities, altered summaries, missing usage and the separate replication strata.
