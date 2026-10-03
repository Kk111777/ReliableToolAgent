# Budgeted study execution

**English** | [简体中文](budgeted_execution.zh-CN.md)

A saved experiment budget can become obsolete while requests are running. The [budgeted runner](../benchmark/tau3/scripts/run_budgeted_study.py) resumes the existing frozen schedule using a separate local spending policy. It leaves the Agent, prompts, scoring, output limits, task selection and original manifests unchanged. The original runner and supervisor remain available as historical implementations; their saved budget values do not authorize a resumed run.

## Cost accounting

The inventory reads every retained attempt in the policy's output directories, including the initial preflight, original smoke, formal execution and additional attempts. An attempt is identified by `study_id / slot_id / attempt`. Identical smoke copies count once; conflicting copies stop execution. A missing outcome, torn request ledger, altered artifact or changed historical balance anchor also stops execution.

The request ledger retains the original list-price calculation. A discount multiplier belongs to the local policy and requires explicit confirmation; a difference between approximate account balances is insufficient. Discounted estimates and provider invoices remain separate. Missing request usage retains its reservation at the same multiplier.

When a policy starts from a reported remaining balance, it saves the earlier attempt records and their hashes as an immutable anchor. Its total ceiling is:

```text
already measured list-price cost × confirmed multiplier + reported remaining balance
```

The current conservative debit includes both measured cost and missing-usage reservations. Subtracting that debit from the ceiling reserves historical unknown charges once. Later attempts consume the remaining allowance; restarting does not reset it. The balance is a reported input, not an independently verified provider invoice. Concurrent usage outside this study is outside this inventory.

## Interfaces and run commands

| Interface | Input | Output and checks |
|---|---|---|
| `CostInventory.records()` / `snapshot()` | Retained study directories | Unique paid records, request counts, measured cost, conservative debit and evidence hash |
| `BudgetPolicy.load()` | Local JSON policy and study root | Validated cap, discount, required historical outputs, frozen manifest hash and optional balance anchor |
| `BudgetPolicy.allowance()` | Current cost snapshot | Remaining **list-price** allowance for the unchanged worker; rounds down |
| `execute(..., run=False)` | Frozen study and local policy | Source, lock, ledger and budget checks; no credentials, worker or paid request |

The local policy records `combined_cap_rmb`, `discount_factor`, `discount_source`, `cost_basis`, `accounting_outputs`, `required_existing_outputs`, `frozen_manifest_sha256` and its execution readiness state. A balance policy also references a saved baseline's path and hash. Generate these from the retained inventory, then check the baseline and dry-run before setting the policy ready. Account balances and these operational files stay outside Git.

From the project root:

```bash
.venv/bin/python -m pytest -q benchmark/tau3/tests/test_budgeted_study.py

.venv/bin/python benchmark/tau3/scripts/run_budgeted_study.py \
  --input artifacts/frozen_study/retail-holdout-v1c \
  --policy artifacts/frozen_study/operational_budget_policy.json
```

Adding `--run` reads the ignored root `.env` and starts paid attempts only after these checks. The runner holds the global budget lock, old supervisor lock and study runner locks. Each job saves its historical cost snapshot, operational policy hash and runner hash. The frozen worker checks every HTTP request, including observable retries, against the assigned allowance. Under serial execution, the historical debit plus that per-worker allowance is the global cap.

`--limit N` stops after N new attempts. The ordinary path skips every existing slot, including scored failures and interrupted attempts. `--retry-infrastructure` is a separate secondary pass: it requires a diagnosed original outcome hash in the policy, never replays a valid or budget-stopped result, permits at most one additional attempt per slot, and respects the frozen total additional-attempt limit. A budget stop is final for the current operational run. Three consecutive execution failures require diagnosis.

Cancellation saves the current worker's partial evidence before releasing locks. A policy or runner edit during execution stops the next attempt; frozen source edits are also rejected. No request is launched if its reservation cannot fit. If returned usage exceeds a reservation, the excess is recorded and execution stops; the guard cannot undo a provider charge already incurred.

Known operator cancellations can be annotated by original outcome hashes retained in the immutable balance baseline. They keep their frozen `timeout / StudyDeadline` status and cost, but do not count as provider failures in the consecutive-failure stop gate. The runner rejects annotations for valid results, other error classes or outcomes absent from the baseline. Three genuine execution failures still stop the run.

## Validation and result boundary

The [contracts](../benchmark/tau3/tests/test_budgeted_study.py) cover reused smoke, preflight and retry costs, unknown usage, torn evidence, discounts, balance anchors, competing locks, dry-run isolation, and refusal before a request reaches the provider. They verify accounting and execution behavior, not model quality.

Two frozen diagnostic fields need care. `terminal_before_reference_write_candidate` checks whether **none** of the reference WRITE keys succeeded; it can miss a remaining WRITE after earlier ones completed. `agent_after_terminal_user` records an assistant turn after the last user message, and should be interpreted as a terminal-response check only when `terminal_marker` is STOP or TRANSFER. With no user message, this flag can be true. These limitations are reported without rewriting the frozen metrics.

The recorded study was paused after 108 of 210 formal first attempts: 101 valid, five infrastructure errors and two operator-cancelled attempts recorded by the frozen worker as timeouts. These interruptions remain separate from model failures. The 120-slot train replication had not started at that pause. This dated snapshot is not a completed benchmark result; final compact evidence and separate cohort reports follow execution and review.
