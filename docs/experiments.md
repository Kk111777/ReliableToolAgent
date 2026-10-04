# Experiments and findings

**English** | [简体中文](experiments.zh-CN.md) · [Project overview](../README.md)

The experiments ask two questions: can a runtime safeguard prevent a specific repeated failure, and does that failure remain important in native retail tasks?

## Controlled tool failures

The initial 2×2 experiment varied raw versus structured error feedback and retry framing. Under retry framing, structured feedback increased repeated failures from 29 to 50 in the recorded toy runs. A clearer error message alone did not reliably induce a better stopping decision.

A separate three-task Guard smoke reduced repeated executed failures from 6 to 0. The Guard checks known non-retryable failures; state-alias regression tests additionally verify that a changed execution target remains callable. The smoke and regression checks answer different questions.

[Historical technical report](../reports/final_technical_report.md) · [Scoring versions](../reports/packaging_audit_20261003.md) · [Guard tests](../local_demo/test_duplicate_guard.py)

## Native retail evaluation

The τ³ pipeline uses the official Agent, tools, environment, and scoring. It does not deploy the smolagents Guard. The earlier clean development audit found no cross-turn exact repeats in its valid runs, which weakened the case for extending the toy controller directly to retail.

The subsequent fixed study used 35 official test tasks, three trials each, under U0/U2 User Simulator configurations. Valid successes were 48/94 and 93/103. On 25 tasks with all three valid pairs, mean reward difference U2−U0 was +0.36, with a 95% task-bootstrap interval [0.24, 0.48]. This identifies sensitivity to the Simulator while holding the Agent fixed.

The schedule finished all 210 first attempts. Pair coverage was 93/105, below the preset 90% gate, and the train extension stayed unstarted. Missing outcomes were asymmetric, so the complete-task interval is a conditional diagnostic.

[Completed study](../reports/frozen_study/retail-holdout-v1/README.md) · [Historical audit](../reports/final_technical_report.md#10-clean-benchmark-results)

## Partial-completion analysis

The original terminal metric only marked trajectories where no reference WRITE had succeeded. The revised analyzer matches reference actions one occurrence at a time and also records tasks that stop after completing some actions. On 197 valid trajectories, it added 13 partial-completion candidates. In case C03, two of three reference WRITEs succeeded before the final User termination.

[Measurement design](engineering_v2.md#measurement-v2-retain-partial-completion) · [Cases](../reports/frozen_study/retail-holdout-v1/cases.md)

## Supporting records

Response adapters, retained-response replay, review records and execution accounting are in the [technical appendix](technical_appendix.md). Offline reproduction starts with the [reproduction guide](reproduction.md). The project stopped controller expansion because the inspected native failures did not provide stronger evidence for it.
