# Stratified Retail Replication

**English** | [简体中文](README.zh-CN.md)

This supplementary study adds 20 different retail tasks to the [35-task test-split primary study](../retail-holdout-v1/README.md). It uses the same fixed Agent, U0/U2 Simulator snapshots, generation limits, event rules, and three paired trials. The two cohorts have 55 distinct tasks and 330 planned primary trajectories in total.

The supplementary tasks come from the official **train split** and had not appeared in retained local runs. They form a separate replication, not an enlarged official test score. Selection reads task metadata and task IDs only; it does not read new rewards or choose cases where a condition performed well.

| Business stratum | Tasks |
|---|---:|
| Return | 3 |
| Exchange | 3 |
| Pending-order modification | 4 |
| Cancellation | 2 |
| User-profile modification | 1 |
| Multiple WRITE types | 5 |
| Policy-limited or read-only reference | 2 |
| Total | 20 |

The [task audit](task_audit.json) records selection seed `20261003`, quotas, scenario hashes, shared user entities, and five rejected candidates with scenario similarity at least 0.90 to development or reserved primary tasks. Selection also rejects near-duplicates within the new sample. The selected IDs are `21, 24, 29, 37, 41, 43, 44, 46, 54, 57, 76, 81, 83, 84, 85, 95, 96, 103, 104, 107`.

The [plan manifest](manifest.json) freezes this selection before any replication calls. The one-shot [supervisor](../../scripts/finish_retail_studies.py) waits for the primary run, checks its source hashes and completeness, analyzes it, then materializes the replication's remaining budget before starting its first request. The four validated smoke attempts are reused with their original identities and hashes. Combined cost accounting counts those paid attempts once.

Both cohorts together have a RMB 500 conservative cap. The primary study retains its original limit; the supplementary study receives the remaining combined allowance. Successful requests use observed usage, including reasoning output; missing usage retains its reservation. Provider invoices and balance are not verified. Three consecutive infrastructure/deadline failures stop execution for diagnosis.

The supervisor preserves first attempts, limits infrastructure reruns, and produces separate local reports:

```text
artifacts/frozen_study/retail-holdout-v1c/analysis/
artifacts/frozen_study/retail-replication-v1/analysis/
artifacts/frozen_study/combined_execution_status.json
```

The [replication analyzer](../../scripts/analyze_replication.py) reports first-attempt denominators, missing pairs, task-level bootstrap, shared-entity sensitivity, and all seven business strata. It does not pool this stratified train sample with the primary test sample into a single benchmark score. Planned trajectories are not completed results; statistical findings are reported after execution and evidence checks.

An implementation fixture is different from a business task. The larger run adds real native benchmark tasks while the existing T01–T05 scripted mechanism tests remain fixed. No recovery controller is tuned on either cohort.

The [compact evidence exporter](../../scripts/study_evidence.py) and its offline audit work for this cohort too. Use `artifacts/frozen_study/retail-replication-v1` as the input directory after completion. It selects the replication audit and all seven strata, keeps the train-split label, and checks first-attempt and retry identities. Export each cohort separately; their reused smoke costs must be deduplicated before computing a combined bill. No final bundle is available while execution is in progress.
