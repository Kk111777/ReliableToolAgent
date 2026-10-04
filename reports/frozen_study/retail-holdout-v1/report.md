# Retail cohort evidence report

Study: `retail-holdout-v1c-20261003`. Split: `test`.

**All primary slots retained**；engineering gate=`false`.

Condition | Planned | First retained | Valid | Reward=1 | Scored non-success | Invalid | Unstarted | Additional
--- | --- | --- | --- | --- | --- | --- | --- | ---
U0 | 105 | 105 | 94 | 48 | 46 | 11 | 0 | 0
U2 | 105 | 105 | 103 | 93 | 10 | 2 | 0 | 0

Unstarted slots have no model outcome. Invalid first attempts include infrastructure failures, timeouts or budget interruptions; they are not scored model failures. Additional attempts are secondary coverage and never change first-attempt denominators or the engineering gate. Success means reward=1; valid fractional rewards remain in the source evidence.

Condition | Success/valid first | Success/retained first | Success/planned slots
--- | --- | --- | ---
U0 | 48/94 | 48/105 | 48/105
U2 | 93/103 | 93/105 | 93/105

First-attempt pair coverage

Planned | Both retained | Both valid | One unstarted | Both unstarted | Without two valid first attempts
--- | --- | --- | --- | --- | ---
105 | 105 | 93 | 0 | 0 | 12

Frozen task-level mean reward difference and 95% interval (U2−U0)

Analysis | Complete tasks | Resampling clusters | Mean difference | 95% CI
--- | --- | --- | --- | ---
paired_reward_bootstrap | 25 | 25 | 0.3600 | [0.2400, 0.4800]
user_entity_cluster_bootstrap_sensitivity | 25 | 21 | 0.3600 | [0.2533, 0.4815]
exclude_near_duplicate_task38_sensitivity | 24 | 24 | 0.3472 | [0.2222, 0.4722]

Role usage and list-price estimates; this bundle only, not account totals or invoices

Role | HTTP | Missing usage | Input tokens | Output tokens | Known RMB | Reserved RMB
--- | --- | --- | --- | --- | --- | ---
agent | 2477 | 2 | 17980379 | 867316 | 5.330708 | 0.042365
user | 1201 | 25 | 1335689 | 1040799 | 16.448545 | 1.124368
evaluator | 69 | 0 | 316091 | 43346 | 0.149910 | 0.000000

See summary.json for per-task and family coverage, every missing pair, first-attempt statuses, event candidates, latency and full role usage. Tokens count returned usage only; reasoning is part of output, not an additional charge. Missing usage retains its reservation.

Do not pool this cohort with another split as an official test score. Intervals use complete three-trial tasks and do not count repeated trials as independent tasks. Candidate events do not establish component causality or Agent improvement. See the budgeted execution guide for the frozen field limits: a remaining WRITE can be missed after earlier ones completed; agent_after_terminal_user can be true without a user message, so this report counts it only with a real STOP/TRANSFER marker. An incomplete snapshot does not prove execution stopped; final publication still needs lock, stop-reason and retained-evidence checks.

Evidence SHA256: `958b52e1ecbcd36e40fbc33daf00983cd2ca1daa9b18cb1281820e2edee35335`
Report source SHA256: `a397ebf66086c0c3402cc4b22e0516c98adb180d1d054e174cf904f22e865b8c`
