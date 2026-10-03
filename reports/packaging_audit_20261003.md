# Packaging and Evidence Audit — 2026-10-03

This is a read-only review of existing experiments for repository presentation. It introduces documentation, a derived presentation snapshot, one data-derived figure, and verification scripts. It does not create benchmark results, invoke model APIs, modify Agent behavior, change existing numeric artifacts, or relocate raw evidence.

## Sources and checked claims

The [verification script](../scripts/audit_packaging_evidence.py) recalculates toy aggregates from individual recorded reports and public-benchmark aggregates from saved simulations using the existing pure analysis helpers. The new [presentation snapshot](packaging_evidence_20261003.json) preserves original values and records source SHA-256 hashes. Existing JSON summaries are unchanged.

| Study | Retained source | Rechecked result |
|---|---|---|
| E0–E3 toy ablation | `artifacts/qwen35-flash-ablation/E*/r*/P*.json` and `summary.json` | 24 runs each; original success 24/24, 24/24, 23/24, 24/24; timely stop 4/24, 1/24, 5/24, 3/24 |
| Toy execution burden | Same reports | Terminal violations 32, 53, 36, 40; duplicate failures 29, 50, 33, 40; average tool calls 2.3333, 3.2083, 2.5000, 2.6667; average model calls 3.3333, 4.2083, 3.5000, 3.6667 |
| Existing v2 rescore | `artifacts/rescored/ablation/` and [public v2 snapshot](evaluator-v2-ablation-summary.json) | E2 24/24; one score-label correction; no trajectory/answer change across the 96 paired files |
| Guard smoke | `artifacts/qwen35-flash-guard-v1/G*/r01/P*.json` and `summary.json` | 3/3 success each; duplicate executed failures 6→0; blocked 0→3; executed calls 9→3; terminal/unnecessary attempts 6→3 |
| U0/U2 Simulator diagnostic | `tau2-bench-baseline/data/simulations/tau3-retail-user-simulator-ablation-{u0,u2}-0-4/results.json` | 15 valid each; premature termination 8/15 vs 0/15; expected WRITE, DB and final reward each 5/15 vs 14/15 |
| Clean development audit | `tau2-bench-baseline/data/simulations/tau3-retail-clean-u2-20x1/results.json` | 20 attempted, 19 valid; final/DB 18/19, NL 19/19, expected WRITE 16/17; zero simulation timeouts |
| Clean tool behavior | Same saved simulations and frozen tool classification | Cross-turn exact repeat 0; same-message duplicate 2 calls in 1 task; explicit failures 3 calls across 3 tasks |
| Residual T05 | Same simulation, raw task id `5` | Sole valid reward-zero task; final/DB=0, NL=1, TRANSFER, no tool failures or exact repeats |

The saved Simulator snapshot matches the raw aggregate. The two existing clean-audit copies ([benchmark](../benchmark/tau3/results/clean_audit_summary.json), [reports](tau3-clean-audit-summary.json)) are identical. Task labels T04/T05 in reports refer to raw ids `4`/`5`, not a shift to one-based numbering.

## Discrepancy: original E2 versus evaluator-v2

The technical report and original artifact record E2 success `0.9583` (23/24). The existing public evaluator-v2 snapshot records `1.0000` (24/24).

The differing file is `E2_raw_no_retry/r01/P04.json`. Its answer already said:

> 无法找到订单 ORDER_MISSING，因此无法查询其库存。请提供有效的订单ID以继续查询。

The original metrics were `task_success=false`, `business_success=false`, and `premature_termination=true`. The existing v2 rescore recognizes “无法找到” as correct missing-order wording, changing those fields to `true`, `true`, and `false`. All other pre-existing metric values, the answer, and the recorded `run` are equal; the other 95 paired reports have unchanged pre-existing values. Separately, v2 adds `correct_continue_behavior=false` to all 96 single-terminal reports; it does not change the displayed stopping or duplicate counts. Current evaluator wording coverage is visible in [`local_demo/test_pilot.py`](../local_demo/test_pilot.py).

Presentation decision: retain the original four-condition success table and label it **original**; disclose v2 alongside it. No success value in either existing artifact is edited, and the difference is not framed as model improvement. Timely-stop and duplicate counts agree across versions.

## Narrative clarifications

- **Historical 48-pair pilot versus four-condition ablation:** the former reported a small average duplicate-failure reduction with structured feedback; the latter has higher duplicates with structured feedback under both retry settings. The report now names the studies separately, so the historical result cannot stand in for the controlled 2×2 finding.
- **Interaction direction:** the additional average tool-call burden of structured feedback is 0.8750 with retry ON and 0.1667 with retry OFF. This is descriptive small-sample evidence, not a statistical interaction test.
- **Simulator versus evaluator:** the U0/U2 intervention changes the model generating user turns and terminal signals, not the Agent or reward evaluator. Expected-WRITE differences are measured-outcome differences under a fixed Agent, not Agent algorithm gains.
- **Diagnostic replacement:** the retained stability report and [`analyze_user_simulator_stability.py`](../benchmark/tau3/scripts/analyze_user_simulator_stability.py) disclose an initial U0 T04 trial 1 infrastructure parse failure. It was replaced using the same task/trial configuration before aggregating the final 15 valid trials. This is separate from clean-audit T04, which remains infrastructure-invalid in the 20 attempted / 19 valid accounting.
- **Native runtime with infrastructure wrapper:** the official Agent interface, tools, orchestrator, and reward rules are preserved. The external [wrapper](../benchmark/tau3/scripts/evaluator_retry_wrapper.py) allows up to two extra evaluator parse retries; it changes infrastructure handling. The project does not claim a fully unwrapped upstream execution path.
- **Duplicate definition:** “2 same-message duplicate calls” counts the two calls in the duplicate group, not two additional redundant calls beyond the first. Cross-turn matching uses exact tool/normalized arguments, not semantic similarity; zero exact repeats does not mean zero conceivable inefficiency.
- **No-go scope:** the clean subset does not support continued controller work for a dominant retry-loop failure. It does not prove such loops never occur in other configurations. T05 remains unresolved observational evidence rather than an Agent-only defect.
- **Cost:** missing Qwen price-map entries make displayed zero-dollar costs unavailable evidence, not a free-run claim.

## Figure provenance

The [Simulator figure](../assets/simulator_ablation.png) reads the existing diagnostic counts through the presentation snapshot and checks it against the public summary before rendering. The [provenance JSON](../assets/simulator_ablation.provenance.json) records its sources, hashes, plotting version, denominators, and plotted values. It has no fabricated runs, confidence intervals, or significance labels. See [regeneration instructions](../assets/README.md).

## Offline verification

```bash
# Public files only: checks snapshot consistency, without credentials.
.venv/bin/python scripts/audit_packaging_evidence.py

# With the retained raw directories: recomputes metrics and checks source hashes.
.venv/bin/python scripts/audit_packaging_evidence.py --local

# Local document links, Markdown anchors, and images; external URLs are not fetched.
.venv/bin/python scripts/check_markdown_links.py
git diff --check
```

A fresh public clone lacks ignored raw trajectories. Public checks establish snapshot consistency; local checks establish agreement with retained recorded metrics and benchmark-analysis definitions. Neither is a new benchmark execution or an independent causal validation of the attribution heuristic.

The packaging scope excludes runtime source, existing tests, model/training code, Project B, and remote repository settings. Negative results, T04, T05, scoring provenance, and research limitations remain visible. The [artifact index](artifact_index.md) supplies navigation without moving potentially useful historical files.

## Completed presentation checks

- Public snapshot, v2 scoring-version, and figure provenance checks: passed.
- Retained-raw re-analysis and all 207 recorded source hashes: passed.
- Preservation check across 1,559 retained experiment/data files: no changed or missing files.
- Offline Markdown check: 9 project-facing documents, 96 local links/anchors/images, no failures; 6 external URLs were counted and not fetched.
- Ruff check and format check for the three new presentation scripts: passed.
- `git diff --check` and whitespace/newline checks on added text files: passed.
- Runtime source, existing tests, and existing benchmark/result JSON files: no diff. No new API experiment or runtime test run is claimed by this update.

The README is approximately 1,939 whitespace-delimited words. This check covers the project-facing navigation, not the inherited upstream documentation corpus. These checks were completed locally before publication; commit and merge status are recorded in Git history and the associated pull request.
