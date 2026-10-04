# Reports and Evidence

**English** | [简体中文](README.zh-CN.md)

Use these files to follow an experiment from its design to its recorded result.

| Question | Read |
|---|---|
| What does the completed engineering revision implement? | [Interfaces](../docs/engineering_v2.md) · [Validation record](engineering-v2/README.md) |
| What did the new frozen 35-task study find? | [Final results](frozen_study/retail-holdout-v1/README.md) · [中文](frozen_study/retail-holdout-v1/README.zh-CN.md) |
| What did the separate model review check? | [First-response comparison and limits](model-review-v1/README.md) · [中文](model-review-v1/README.zh-CN.md) |
| How were the historical studies designed, and what were the results? | [Technical report](final_technical_report.md) |
| What happened in the historical audit's remaining failed task? | [T05 case analysis](residual_case_T05.md) |
| Which code and files support each number? | [Evidence index](artifact_index.md) |
| How can I check the repository or analyze saved runs? | [Reproduction guide](../docs/reproduction.md) · [中文](../docs/reproduction.zh-CN.md) |
| Why do the original and v2 toy scores differ? | [Source and scoring audit](packaging_audit_20261003.md) |

## Result Snapshots

| File | Contents |
|---|---|
| [Engineering integration](engineering-v2/integration.json) | Four new attempts and request accounting; no recovery branch triggered |
| [Measurement v2](engineering-v2/measurement.json) | All 210 first-attempt identities; reference-action diagnostics and partial-completion candidates |
| [Model review](model-review-v1/summary.json) | Twenty selected excerpts, first/protocol labels, 117/120 agreements and all three count disagreements |
| [Frozen primary evidence](frozen_study/retail-holdout-v1/public_evidence.json) | 210 first attempts, source hashes, task bootstrap, missing pairs, request usage and costs; below engineering acceptance |
| [Eight case records](frozen_study/retail-holdout-v1/case_index.json) | Sanitized positions and tool counters; [English](frozen_study/retail-holdout-v1/cases.md) · [中文](frozen_study/retail-holdout-v1/cases.zh-CN.md) |
| [Release status](frozen_study/retail-holdout-v1/release_status.json) | Primary closure, failed engineering gate and train plan with zero started slots |
| [Clean audit](tau3-clean-audit-summary.json) | Frozen configuration, attempted/valid counts, rewards, and residual case |
| [Simulator diagnostic](../benchmark/tau3/results/user_simulator_stability_summary.json) | Fixed-Agent U0/U2 conditions and valid-trial counts |
| [Existing evaluator-v2 ablation](evaluator-v2-ablation-summary.json) | Toy results after the recorded scoring correction |
| [Evidence snapshot](packaging_evidence_20261003.json) | Original toy, Guard, Simulator, and clean-audit values with source hashes |

The [τ³ guide](../benchmark/tau3/README.md) documents native benchmark setup and analysis. The [figure notes](../assets/README.md) explain how the chart uses saved counts. Raw model trajectories remain in the local workspace; the public repository contains compact snapshots and the code used to inspect them.
