# Retail 主实验：结果与边界

[English](README.md) | **简体中文** · [项目概览](../../../README.zh-CN.md)

固定原生 Agent，只改变 User Simulator，测得的 retail 结果就发生明显变化：U0 有效成功为 **48/94**，U2 为 **93/103**。在三对 trial 均有效的 25 个任务上，U2−U0 平均 reward 差为 **+0.36 [0.24, 0.48]**。这说明 Simulator 敏感性；两组缺失情况不对称限制了比较，不能据此宣称 Agent 提升。

固定的 35 题 test 队列于 2026-10-04 完成：**210/210 个首次尝试全部保留**，其中 197 个评分有效、13 个无效。**有效配对为 93/105（88.57%）**，低于冻结的 90% 工程门槛。本批次已完成执行计划，结果作为诊断证据发布。独立的 20 题 train 复核没有启动，120 个计划槽位没有模型成绩；正式槽位没有新增补跑。

## 比较的是什么

原生 Agent、prompt、工具、环境和评分规则保持固定，基准 commit 为 `b7ea9074c1cba482b30687fecdb5c8425fd6f619`。Agent 与 NL evaluator 使用 `openai/qwen3.5-flash-2026-02-23`；U0 的 User Simulator 使用同一 snapshot，U2 使用 `openai/qwen3.8-max-2026-09-02`。每题三个配对 trial，共享 seed。[public_evidence.json](public_evidence.json) 内的 manifest 保存实际冻结配置及来源哈希。

| 条件 | 首次尝试 | 有效评分 | 满分成功 / 有效 | 满分成功 / 计划 | 无效 |
|---|---:|---:|---:|---:|---:|
| U0 | 105 | 94 | 48/94（51.06%） | 48/105（45.71%） | 11 |
| U2 | 105 | 103 | 93/103（90.29%） | 93/105（88.57%） | 2 |

无效评分是缺失结果，不能当成已评分的 reward-zero 失败。按计划槽位计算的比例也包含执行覆盖的影响。两组缺失数量不同，因此仅比较有效评分中的成功率，不能视为对完整队列的无偏估计。[summary.json](summary.json) 列出全部 12 个缺少两份有效评分的配对；补跑不会替换首次尝试。

## 统计与行为诊断

冻结的任务级 bootstrap 只纳入**三个 trial 配对均有效的 25 个任务**，即 75 对。在该子集中，官方 reward 的平均差 U2−U0 为 **0.36**，95% 任务级 bootstrap 区间为 **[0.24, 0.48]**。前述 93 个有效配对包含 trial 不完整的任务，这些任务没有进入该区间。按共享用户实体聚类后区间为 [0.2533, 0.4815]；按预设方案排除近重复任务 T38 后，24 个完整任务的均值为 0.3472，区间为 [0.2222, 0.4722]。这些检查不能消除结果缺失偏差，也不能确认模型是否在训练时接触过公开任务。

[自动生成的报告](report.zh-CN.md) 保留冻结计算。其 summary 包含各 WRITE 业务家族的计划／有效分母、逐任务覆盖、延迟、终止、重复／错误计数及事件候选，同时列出全部首次和有效子集。家族结果只是小样本描述。候选事件和 Simulator 分数变化，都不能证明组件因果或 Agent 算法提升。

## 无效尝试与停止扩展

[无效尝试清单](invalid_first_attempts.json) 保存九个 simulation `ValueError`、两个 evaluator `JSONDecodeError`，以及两次人为取消后保留的 `timeout/StudyDeadline`。九个 simulation 异常的最后一次 User 返回均为 `length`，completion 为 8194 token，其中 reasoning 为 8192。这是可观察关联，保留日志不足以证明完整因果链。两次 evaluator 错误出现在带 Markdown fence 的异常 JSON 返回之后。预算纠正期间的人为取消保留原状态、用量预留和首次分母。

工程门槛还要求首次基础设施错误／超时不超过 10%，本批次为 13/210（6.19%）。配对完整度一项不通过，已经足以停止扩展。因此完成固定的主队列后，本轮不启动 [train 复核](../../../benchmark/tau3/studies/retail-replication-v1/README.zh-CN.md)，也不做付费次级补跑；没有为了修饰结果修改冻结的生成、评分或事件规则。

## 案例与测量限制

[八个核验案例](cases.zh-CN.md) 覆盖 WRITE 前终止、动作顺序错误、成功 READ 重复、原生查找恢复、评估无效、User 输出截断、部分 WRITE 完成和人为取消。[脱敏索引](case_index.json) 关联 attempt 哈希、消息位置和工具计数。案例由分析器作者有目的选择并检查，既不是随机抽样，也不是独立标注。此前的 30 条开发轨迹／180 字段检查也由同一作者完成。

两个冻结字段需要结合范围解释。`terminal_before_reference_write_candidate` 要求尚未完成任何参考 WRITE，因此会漏掉已部分完成后剩余的最后一次 WRITE。没有 User 消息时，`agent_after_terminal_user` 也可能为 True；报告只在实际 STOP／TRANSFER 标记下解释它。没有根据新结果修改这些字段。

Toy 的失败调用 Guard 没有接入原生 τ³。机制验证、Simulator 敏感性和原生 Agent 行为分别陈述。本轮停止扩展控制器：已检查的故障没有建立原生 Guard 的独立收益证据。

请求/token 核算用于复现，详情保存在[运行附录](../../../docs/operations/budget_accounting.zh-CN.md)。

## 在公开 clone 中复算

按[环境说明](../../../docs/reproduction.zh-CN.md)配置后，下列命令不需要 API key 或原生基准 checkout：

```bash
.venv/bin/python benchmark/tau3/scripts/study_evidence.py audit \
  --input reports/frozen_study/retail-holdout-v1/public_evidence.json
.venv/bin/python benchmark/tau3/scripts/audit_study_cases.py \
  --evidence reports/frozen_study/retail-holdout-v1/public_evidence.json \
  --cases reports/frozen_study/retail-holdout-v1/case_index.json
.venv/bin/python benchmark/tau3/scripts/report_study_evidence.py \
  --input reports/frozen_study/retail-holdout-v1/public_evidence.json \
  --output artifacts/recomputed-retail-holdout
```

报告输出必须使用新目录。证据复算从精简指标重算汇总和区间，案例复核重算工具计数；完整轨迹、参数值和凭据留在本地。哈希检查一致性并识别保留证据，不会独立认证官方 reward 或语义判断。[发布状态](release_status.json)记录本地收尾、文件哈希及 train 未启动的处置，属于作者检查记录。
