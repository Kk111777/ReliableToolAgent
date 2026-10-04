# 用量与费用核算

[English](budget_accounting.md) | **简体中文** · [技术附录](../technical_appendix.zh-CN.md)

本记录覆盖已完成的 retail 批次，请求/token 核算用于复现。

## 冻结主批次

本证据包包括 210 个正式首次尝试和四个复用 smoke，smoke 只计一次：合计 214 个尝试、3747 次可观察 HTTP 请求。已知用量的原价估算为 **21.929163 元**，为 27 次缺失用量请求保留额度后，保守扣费为 **23.0958958 元**。按用户确认的五折，分别估算为 **10.9645815 元**和 **11.5479479 元**。这些数值只覆盖本证据包，不包括更早的 preflight 或其他账户活动，也不等于已经核对的服务商账单。

自动报告分别列出 Agent／User／evaluator 请求、已知输入／输出 token 及未知用量预留。Reasoning 已包含在输出 token 中。Manifest 中的原预算字段属于执行时已被覆盖的历史计划，既不是实际账单，也不是按该数额消费的授权。

来源：[精简证据](../../reports/frozen_study/retail-holdout-v1/public_evidence.json) · [自动报告](../../reports/frozen_study/retail-holdout-v1/report.zh-CN.md)。
