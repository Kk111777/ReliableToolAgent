# GitHub publication checks — 2026-10-02

The public project evidence was on `research/reliability-guards` at `7e0708e`, while GitHub `main` remained at upstream `30bb116`. This publication brings the five existing project commits and the current progress note into the personal fork's main branch. It preserves the research/setup branches and upstream license.

## Scope

The existing project adds deterministic fault experiments, per-call observability, structured error semantics, an isolated toy Guard, public τ³ analyzers and compact evidence reports. The Guard was not evaluated as a τ³ intervention. No new API evaluation or benchmark run was performed during publication.

## Validation

- Project suite: `.venv/bin/python -m pytest -q local_demo` — **50 passed**.
- Additional upstream `tests/test_memory.py tests/test_agents.py`: **95 passed, 10 failed, 2 skipped, 2 errors** in the current light local environment.
- An untouched archive of `origin/main` (`30bb116`) was tested with the same interpreter and its own source path. It produced the **same counts and failed/error test IDs**. The observed failures therefore also occur on the original baseline in this environment.
- The additional `tests/test_utils.py` suite could not collect because IPython is absent. Missing optional search/model packages and shared-data fixtures also limit the broader upstream run. No packages were installed to change that baseline.
- Checked the publication diff for whitespace, credentials, ignored runtime artifacts, and result-claim boundaries. Compact results are public; raw provider trajectories and credentials remain outside Git.

The project-specific check is not a claim that the complete upstream regression suite passes or that the public benchmark was rerun.
