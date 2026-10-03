# Retail 分层补充复核

[English](README.md) | **简体中文**

这项补充实验在[原有 35 个 test 任务的主实验](../retail-holdout-v1/README.zh-CN.md)之外，增加 20 个不同的 retail 任务。固定 Agent、U0/U2 Simulator snapshot、生成限制、事件规则和三个配对 trial 均沿用主实验。两个批次合计 55 个不同任务、330 条计划主分析轨迹。

补充任务来自官方 **train split**，没有出现在保留的本地运行中。它们单独作为复核报告，不计为扩大的官方 test 成绩。选择过程只读取任务元数据和 ID，不读取新 reward，也不挑某个条件表现更好的案例。

| 业务分层 | 任务数 |
|---|---:|
| 退货 | 3 |
| 换货 | 3 |
| 待处理订单修改 | 4 |
| 取消订单 | 2 |
| 用户资料修改 | 1 |
| 多种 WRITE 操作 | 5 |
| 参考路径受策略限制或只读 | 2 |
| 合计 | 20 |

[任务审计](task_audit.json) 记录选择 seed `20261003`、配额、场景哈希、共享用户实体，以及因与开发任务或已安排主实验任务的场景相似度达到 0.90 而排除的五个候选。新样本内部的近似重复也会被排除。最终 ID 为 `21, 24, 29, 37, 41, 43, 44, 46, 54, 57, 76, 81, 83, 84, 85, 95, 96, 103, 104, 107`。

[计划 manifest](manifest.json) 在补充实验调用 API 前冻结任务选择。[一次性执行监督器](../../scripts/finish_retail_studies.py) 等待主实验结束，核验来源哈希和完整度，生成分析，再在补充实验的第一次请求前计算剩余预算。已经验证的四次 smoke 沿用原身份和哈希，累计费用只计一次。

两个批次合计采用 500 元保守上限。主实验保持原有上限，补充实验使用累计预算中的剩余额度。成功请求按返回用量估算，包含推理输出；缺失用量保留预留额度。服务商账单和余额未核对。连续三次基础设施错误／超时后停止并诊断。

监督器保留首次尝试、限制基础设施补跑，并分别生成本地报告：

```text
artifacts/frozen_study/retail-holdout-v1c/analysis/
artifacts/frozen_study/retail-replication-v1/analysis/
artifacts/frozen_study/combined_execution_status.json
```

[补充分析器](../../scripts/analyze_replication.py) 报告首次尝试分母、缺失配对、任务级 bootstrap、共享实体敏感性和全部七种业务分层。这个分层 train 样本不会与主实验 test 样本混成一个基准分数。计划轨迹数不等于已完成结果；运行及证据核验结束后再报告统计结论。

实现夹具与业务任务用途不同。本轮增加原生公开基准任务，已有 T01–T05 脚本机制测试保持固定。两个批次都不用于调优恢复控制器。

[精简证据导出与离线复算](../../scripts/study_evidence.py)也支持本批次。完成后将输入目录换为 `artifacts/frozen_study/retail-replication-v1`；程序使用补充任务审计和全部七种分层，保留 train split 标签，检查首次尝试与补跑身份。两个批次分别导出；计算累计费用时，沿用的 smoke 费用需要去重。实验进行中尚无最终证据包。
