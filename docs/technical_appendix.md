# Technical appendix

**English** | [简体中文](technical_appendix.zh-CN.md) · [Project overview](../README.md)

The overview presents the implementation and selected findings. These supporting records explain how to reproduce the checks and inspect the evidence behind them.

## Reproduction and source evidence

- [Reproduction guide](reproduction.md): environment setup, offline commands, and native benchmark requirements.
- [Evidence index](../reports/artifact_index.md): implementations, study versions, and source records.
- [Historical technical report](../reports/final_technical_report.md): structured-error ablations, toy Guard tests, and migration to τ³.
- [Scoring and source audit](../reports/packaging_audit_20261003.md): original versus revised toy scores.

## Study and engineering records

- [Primary study data and generated report](../reports/frozen_study/retail-holdout-v1/report.md): denominators, missing pairs, bootstrap, and request/token accounting.
- [Eight case records](../reports/frozen_study/retail-holdout-v1/cases.md): selected failure trajectories and interpretation limits.
- [Engineering validation](../reports/engineering-v2/README.md): retained-response replay, native integration, and measurement v2.
- [Separate-session model review](../reports/model-review-v1/README.md): first labels, preserved disagreements, and disclosed project context. This is not strict independent blind or human validation.
- [Publication protocol](study_results.md): compact-data checks and result disposition.

## Operations

- [Usage and cost accounting](operations/budget_accounting.md): cohort-specific estimates and accounting scope.
- [Budgeted execution](budgeted_execution.md): historical execution controls and per-request reservations; not an instruction to resume a completed experiment.

Public checks recompute counts and summaries. Full trajectory semantics and official rewards require the retained local inputs; source hashes alone do not authenticate them.
