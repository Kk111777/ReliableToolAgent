# Engineering repairs v2: validation record

[简体中文](README.zh-CN.md) | [Design, interfaces and limits](../../docs/engineering_v2.md)

This directory records validation of Guard argument identity, response adapters and measurement v2. The frozen study still has 210 first attempts, 197 valid scores and 93/105 valid pairs. It failed its 90% engineering gate; these materials do not revise that result.

| Check | Evidence | What it supports |
|---|---|---|
| Guard counterexample with a changed state alias | [Regression contracts](../../local_demo/test_duplicate_guard.py) | A new target is no longer blocked by the old target's failure; the same failed target can still be blocked. |
| Historical evaluator format failures | [Six-response offline replay](evaluator_replay.json) | 6/6 pass strict validation after full-fence removal, with identical payload values. |
| Empty User output and request cost | [Response tests](../../benchmark/tau3/tests/test_engineering_worker.py), [budget contracts](../../benchmark/tau3/tests/test_engineering_pilot.py) | One empty-response retry maximum; extra HTTP requests are billed, insufficient allowance prevents requests, cancellation is not retried. |
| Measurement coverage on 197 valid traces | [Compact data](measurement.json) | Terminal missing-reference-WRITE candidates change from 48 to 61; all 13 additions are partial completion. |
| New native integration check | [Four-slot record](integration.json) | Connection, execution and accounting under the engineering protocol; not an error-rate estimate or algorithm gain. |

Public files check aggregates, identities and hashes; they cannot re-evaluate private trajectory semantics. The six historical responses were purposefully selected from two known failures. The old 180 development-field checks and eight cases were not independent human validation. Measurement v2 is also a retrospective check by the same author.

The final integration check has **4/4 valid attempts** and retains **67 HTTP requests**. Measured list-price cost is **RMB 0.4994654**; the conservative list-price debit is **RMB 0.5175894**, including one unknown-usage reservation. These are not provider invoices. No empty-User retry or evaluator format recovery was triggered here. Recovery branches are validated by fault contracts and the six retained-response replays, not by this successful integration check.

## Offline checks

From the repository root, without credentials:

```bash
.venv/bin/python -m pytest -q local_demo benchmark/tau3/tests
.venv/bin/python benchmark/tau3/scripts/engineering_evidence.py \
  --audit reports/engineering-v2/integration.json
.venv/bin/python benchmark/tau3/scripts/measurement_v2.py audit \
  --input reports/engineering-v2/measurement.json \
  --evidence reports/frozen_study/retail-holdout-v1/public_evidence.json \
  --cases reports/frozen_study/retail-holdout-v1/case_index.json
```

The measurement audit verifies the v1 bundle first, then checks complete first-attempt identities, source hashes and old fields, and recomputes new summaries and case joins. `measurement_v2.py export` performs raw semantic remeasurement and needs locally retained trajectories.

## Execution scope

The integration check uses exposed development tasks 0 and 5, once with U0/U2: four planned slots. Models, prompts, the 8192 completion cap and 600-second attempt deadline retain the old settings; adapter rules have a separate version. Every first attempt is retained, without reward-based retries. The old train replication remains unstarted.

Historical toy Guard results came from the pre-repair runtime. This Guard change is validated with interface contracts; the new native integration check does not deploy the smolagents Guard. A native controller benefit would require observed target failures and a separately designed controlled experiment.
