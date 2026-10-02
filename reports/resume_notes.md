# Resume Notes

## 中文简历 bullet

- 基于 HuggingFace `smolagents` 构建工具调用可靠性观测与故障归因平台，支持逐 tool-call 轨迹、错误/结果、并行调用和业务 reward 分离记录。
- 设计 raw/structured error 与 retry-framing 的固定模型消融实验，并实现独立 Duplicate Failure Guard smoke test；结果显示 toy intervention 影响混合，未将 Guard 结果外推到公共 benchmark。
- 将观测流水线迁移到固定 commit 的 Sierra τ³-bench retail，完成 20×1 clean audit：19 个有效 simulation 中 18 个 final reward=1，并定位 User Simulator 提前终止这一重要混杂因素。

## English resume bullets

- Built a tool-calling reliability observability and failure-attribution pipeline on a HuggingFace `smolagents` fork, with per-tool-call trajectories, parallel-call logging, error/result capture, and separate business-state evaluation.
- Designed controlled raw-vs-structured error and retry-framing ablations, plus an isolated Duplicate Failure Guard smoke test; results were mixed and were not extrapolated to the public benchmark.
- Migrated the measurement pipeline to a pinned Sierra τ³-bench retail checkout and completed a clean 20×1 audit: 19 valid simulations, 18/19 final reward=1, and a documented User Simulator termination confound.

## 60-second project introduction

我做的是一个工具调用 Agent 的可靠性观测与故障归因项目。最开始我先用一个确定性的订单/库存 toy environment，把 task loading、tool call、故障注入、trajectory、memory、evaluator 和 logger 全链路固定下来；然后加入逐 tool-call logging、结构化错误和小范围的 duplicate failure guard 实验。toy 实验的结果并不支持简单地说某个 intervention 一定有效，所以我没有直接把它迁移到真实 benchmark。之后我固定了 τ³-bench 的 retail commit，用官方 Agent 和运行循环完成了 20×1 public benchmark audit。结果是 19 个有效 simulation 中 18 个 reward=1，同时发现 User Simulator 的 terminal signal 会影响 Agent 是否还有机会执行 WRITE。最终项目的重点是可复现观测和失败归因，而不是声称已经提升了 benchmark 成绩。

## 3-minute project introduction

这个项目关注的是一个常见但容易混淆的问题：工具调用 Agent 的失败，到底来自模型决策、工具执行、环境状态、用户模拟器，还是 evaluator/runner 基础设施。

第一阶段是 controlled toy pilot。我实现了 T01–T05 的确定性任务，包括正常多步调用、temporary failure recovery、wrong entity repair、not-found 业务状态和 repeated failure。这样可以先验证完整实验平台，而不是一开始就用真实 LLM 的随机行为解释问题。随后我做了 raw error versus structured error，以及 structured/raw error 和 retry framing 的 2×2 ablation。每个条件都有固定模型和记录的 trajectory。结果显示结构化错误没有带来一致的及时停止或 task success 改善，retry framing 的影响也不稳定。

我还做了一个隔离的 Duplicate Failure Guard V1 smoke experiment。它只阻止同一 tool 和 canonical arguments 的重复 non-retryable failure，retryable failure 不会被 block，而且每次 Agent run 都清空 failure records。这个实验验证了 runtime instrumentation 和 blocking semantics，但样本太小，所以我没有把它描述成 τ³ 上的收益。

第二阶段迁移到公开的 Sierra τ³-bench retail。我固定了 commit，使用官方 Agent、tools、environment、orchestrator 和 evaluator，只在 runner 外围增加离线 observability analyzer。分析器使用 exact canonical argument normalization，能统计 READ/WRITE、explicit tool failure、same-message duplicate 和 cross-turn repeat，并保留完整 trajectory。

迁移过程中发现 User Simulator 是重要 confound。固定 Agent 后，Qwen3.5 Flash User 和 Qwen3.8 Max User 的 15-trial diagnostic 在 premature termination 和 WRITE completion 上差异很大。因此最终 development evaluation configuration 固定使用 Qwen3.8 Max User，并把它称为 development diagnostic，而不是官方 leaderboard 配置。

最后的 clean 20×1 audit 有 20 个记录、19 个有效 simulation。18/19 final reward=1，18/19 DB reward=1，19/19 NL reward=1，cross-turn exact repeat 为 0，只有一个 valid reward-zero residual case T05；另有 T04 evaluator parse failure，单独标为 infrastructure-invalid。项目到这里停止，不实现 Controller、Completion Guard 或 τ³ Duplicate Guard migration。

## Likely interview questions

1. 你定义的“可靠性”具体是什么？
2. 为什么先做 toy environment，而不是直接上 τ³？
3. raw error 和 structured error 的唯一实验变量是什么？
4. 结构化错误实验的结果是否支持它有效？
5. retry framing 和 recovery policy 有什么区别？
6. Duplicate Failure Guard 的 key 是什么？
7. 为什么 retryable failure 不 block？
8. 如何保证 blocked call 没有真正执行 tool？
9. 为什么要做 per-tool-call logging，而不是只看 ActionStep.error？
10. 一个 ActionStep 有多个并行 tool calls 时如何记录成功/失败？
11. τ³ 的官方执行链是什么？
12. 为什么 User Simulator 会成为实验变量或 confound？
13. U0/U2 的诊断结果能否称为模型能力比较？
14. T04 为什么不能算 Agent failure？
15. T05 是否足以支持实现 Completion Guard 或 Controller？

### Short answer discipline

面对这些问题，建议坚持三条边界：

- 只报告 artifact 中真正观察到的事实；
- 区分 valid behavior failure、simulator termination 和 infrastructure error；
- 不把 toy Guard 的局部 smoke 结果描述成 τ³ benchmark improvement。
