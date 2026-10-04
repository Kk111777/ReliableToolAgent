# Engineering repairs v2

[简体中文](engineering_v2.zh-CN.md) | [Project](../README.md)

This revision addresses three reproducible problems: a Guard false block after a state alias changes, evaluation interruptions caused by response formatting, and a terminal metric that misses partial WRITE completion. The old study keeps all 210 first attempts, scores, 93/105 valid pairs and failed engineering gate.

## Guard: match the execution target

Previously, two model calls with `{"order_id":"lookup"}` shared a failure key even when `state["lookup"]` changed from a missing order to a valid order. Each call now resolves state references once. The Guard, execution and failure history use that same effective argument snapshot.

Per-call records retain raw `arguments` and add `resolved_arguments`; `normalized_arguments` identifies the execution target. Different aliases for the same failed target can still match, while an alias pointing to a new target can execute. Alias chains still resolve one level only.

This fixes argument identity. External database changes with identical arguments, and concurrent calls before any failure is recorded, still require business-specific invalidation or idempotency. The Guard does not provide either guarantee.

Ordinary observational `execute_tool_call` hooks can still delegate to `super`. A hook that rewrites the tool or arguments after the Guard check is rejected before execution, keeping the checked target aligned with execution. Execution objects retain their identity; logs keep a pre-call JSON snapshot. Overrides that bypass the base method and execute tools themselves are outside this contract.

## Response adapters: bounded recovery with retained failures

The new [`engineering_worker.py`](../benchmark/tau3/scripts/engineering_worker.py) composes the original worker in an isolated process and restores adapters on exit. The frozen worker, Agent prompt, models, output cap and scorer stay unchanged.

- **Empty User response:** when both text and tool calls are absent, regenerate once with identical input. Both responses are billed and recorded. A second empty response remains an explicit error; no User text is fabricated. Connection errors, budget stops and cancellation propagate immediately.
- **Evaluator JSON:** unwrap only a complete outer `json` or unlabelled Markdown fence. Require the official fields, actual Boolean values, and exact expected assertion text/counts. Reject prose, broken JSON, duplicate keys, empty results and string Booleans; never change verdict values. At most two format retries are allowed, with response fingerprints and call indices retained.
- **Safe diagnostics:** retain fixed stages, allowlisted exception types, trusted relative source locations and cause types. Do not serialize exception messages, locals, headers or full responses. External source locations are redacted. New locations help diagnose future failures; they cannot establish the missing causal stack for the old nine ValueErrors.

These adapters define a new protocol. Additional requests change cost and generation, so new attempts cannot enter the old first-attempt denominator.

## Measurement v2: retain partial completion

[`measurement_v2.py`](../benchmark/tau3/scripts/measurement_v2.py) is a separate diagnostic entry point. Each successful tool response matches at most one reference WRITE occurrence; unknown results are not successes. A terminal message with any unmatched reference WRITE becomes a candidate, including trajectories that completed earlier actions but missed the last one.

Without an actual STOP/TRANSFER User message, `agent_after_terminal_user_v2` is unavailable. Missing reference actions or trajectories remain unknown.

On the old 197 valid traces, v2 flags 61 candidates versus 48 in v1. All 13 additional candidates have partial completion. C03 matches 2/3 and C07 3/4. This is a retrospective coverage correction, not new success, causal attribution or performance improvement. Equivalent business outcomes may use different arguments; exact reference matching does not replace official scoring.

## Validation and limits

Offline contracts cover aliases, duplicate identity, one-time resolution, empty-response retries, cancellation, format/schema rejection, diagnostic redaction, WRITE multiplicity and unknowns. All six retained fenced responses from the two old evaluator failures pass strict offline replay with unchanged contents and Boolean verdicts. No old attempt was rescored.

A separate four-slot integration check uses already exposed development tasks 0 and 5, once under U0/U2. It keeps the original model settings, a 600-second deadline, per-HTTP budget checks and historical cost accounting. No attempt retries, reward-based selection or automatic expansion. See the [engineering evidence](../reports/engineering-v2/README.md). This checks integration, not an error-rate reduction or a new holdout result.

Historical labels, cases and new measurement checks come from the same author and code review; no independent human validation is claimed. Public compact data can check row identities, source hashes and aggregate consistency. Raw semantic remeasurement requires local trajectories.

Shared mutable state objects retain their execution identity. Their contents are checked again before execution, rejecting in-place changes made by a hook. Mutation by other threads during a call is not isolated; callers need external synchronization.
