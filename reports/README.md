# Reports and Evidence

Use these files to follow an experiment from its design to its recorded result.

| Question | Read |
|---|---|
| How were the studies designed, and what were the results? | [Technical report](final_technical_report.md) |
| What happened in the remaining failed task? | [T05 case analysis](residual_case_T05.md) |
| Which code and files support each number? | [Evidence index](artifact_index.md) |
| How can I check the repository or analyze saved runs? | [Reproduction guide](../docs/reproduction.md) · [中文](../docs/reproduction.zh-CN.md) |
| Why do the original and v2 toy scores differ? | [Source and scoring audit](packaging_audit_20261003.md) |

## Result Snapshots

| File | Contents |
|---|---|
| [Clean audit](tau3-clean-audit-summary.json) | Frozen configuration, attempted/valid counts, rewards, and residual case |
| [Simulator diagnostic](../benchmark/tau3/results/user_simulator_stability_summary.json) | Fixed-Agent U0/U2 conditions and valid-trial counts |
| [Existing evaluator-v2 ablation](evaluator-v2-ablation-summary.json) | Toy results after the recorded scoring correction |
| [Evidence snapshot](packaging_evidence_20261003.json) | Original toy, Guard, Simulator, and clean-audit values with source hashes |

The [τ³ guide](../benchmark/tau3/README.md) documents native benchmark setup and analysis. The [figure notes](../assets/README.md) explain how the chart uses saved counts. Raw model trajectories remain in the local workspace; the public repository contains compact snapshots and the code used to inspect them.
