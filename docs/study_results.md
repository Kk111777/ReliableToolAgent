# Reading and releasing study results

**English** | [简体中文](study_results.zh-CN.md)

The test-split study and the train-split replication are separate cohorts. Each report starts with execution coverage: planned slots, retained first attempts, valid results, scored non-successes, invalid attempts and unstarted slots. Repeated trials are not additional independent tasks.

## Offline reports

[`report_study_evidence.py`](../benchmark/tau3/scripts/report_study_evidence.py) reads one compact bundle, runs its source and aggregate audit, then writes `summary.json`, `report.md` and `report.zh-CN.md` into a new directory. It makes no model calls and requires neither credentials nor the native benchmark checkout. The bilingual reports use the same derived counts; existing outputs are never overwritten.

```bash
.venv/bin/python benchmark/tau3/scripts/report_study_evidence.py \
  --input artifacts/frozen_study/retail-holdout-v1c/public_evidence.json \
  --output artifacts/frozen_study/retail-holdout-v1c/cohort_report
```

The [compact export and audit](../benchmark/tau3/studies/retail-holdout-v1/README.md#compact-evidence-checks) verify local raw evidence before packaging. A public clone can regenerate the report from the matching compact bundle and source version. This recomputes reported metrics; it does not independently rescore private trajectories.

## Denominators and missing results

| Field | Meaning |
|---|---|
| Valid first attempts | First attempts with a retained official reward, including fractional rewards |
| Successful first attempts | Valid first attempts whose official reward is exactly 1 |
| Scored non-successes | Valid first attempts with reward below 1; distinct from infrastructure failures |
| Invalid first attempts | Retained attempts without a valid score; original statuses remain unchanged |
| Unstarted slots | Planned slots with no first attempt; no model outcome exists |
| Additional attempts | Separate attempts after an invalid first result; they never replace it |

Success is shown over valid first attempts, over all retained first attempts and over all planned slots. The latter two rates also reflect execution coverage; they are not pure model success rates. A zero denominator is `NA`. The secondary number of slots with a valid result after additional attempts does not change primary intervals or the engineering gate.

The report lists **every planned pair** without two valid first attempts, including trials where neither condition started. This supplements the frozen bootstrap's observed-row missing-pair list. The bootstrap itself is unchanged: all three valid U0/U2 trial pairs are required for a task to enter the primary interval. Task, shared-entity and near-duplicate sensitivity results stay separate. Family tables include their planned and valid denominators.

Event diagnostics are shown for both all retained first attempts and the valid subset. Candidate counts do not establish why a task failed. The [frozen field limitations](budgeted_execution.md#validation-and-result-boundary) still apply. Token and list-price totals cover all phases in this bundle, including its smoke and additional attempts; they exclude other historical studies and account usage. Reasoning tokens are already part of output tokens. Missing usage retains its reservation.

## Releasing a completed or stopped study

An incomplete report is a snapshot, even if the runner later stops. The generator cannot infer a stop reason or authorize publication. Before releasing a completed study or an incomplete diagnostic:

1. Confirm the relevant runner and worker have stopped and the global, supervisor and study locks are released. Reconcile every retained outcome; no paid attempt may be unfinished or omitted from the ledger.
2. Verify frozen sources and every outcome, trajectory and request hash. Preserve first attempts and all additional attempts. Keep the full-history cost audit local; report estimates and invoice verification separately.
3. Export from stable raw evidence. The default export requires all primary slots. For a budget or engineering stop, `--allow-incomplete` produces an explicitly incomplete diagnostic; it does not certify the stop.
4. State the saved stop reason, actual coverage, remaining slots, engineering-gate result and whether replication ran. Keep test and train evidence separate. Review representative cases against message positions and source hashes before making component claims.
5. Audit and regenerate each cohort in an independent public source copy. Publish only reviewed compact metrics, sources, cases and paired-language reports; raw logs, credentials, account balances and personal preparation stay outside Git.

Completion of a schedule means its first attempts were retained, not that every attempt was valid or that the Agent improved. A stopped study can still provide an auditable diagnostic boundary. The project should report that boundary directly instead of filling unstarted slots or repairing the primary denominator with retries.
