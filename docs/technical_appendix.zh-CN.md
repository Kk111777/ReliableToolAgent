# 技术附录

[English](technical_appendix.md) | **简体中文** · [项目概览](../README.zh-CN.md)

首页介绍实现与主要发现。以下记录用于复现检查，并追溯这些发现的依据。

## 复现与来源证据

- [复现说明](reproduction.zh-CN.md)：环境安装、离线命令与原生基准要求。
- [证据索引](../reports/artifact_index.md)：实现位置、研究版本与来源记录。
- [历史技术报告](../reports/final_technical_report.md)：结构化错误消融、toy Guard 检查与 τ³ 迁移。
- [评分与来源核对](../reports/packaging_audit_20261003.md)：toy 原始评分与修订评分的差异。

## 研究与工程记录

- [主实验数据与自动报告](../reports/frozen_study/retail-holdout-v1/report.zh-CN.md)：分母、缺失配对、bootstrap 与请求/token 记录。
- [八个案例](../reports/frozen_study/retail-holdout-v1/cases.zh-CN.md)：选定失败轨迹及解释边界。
- [工程验证](../reports/engineering-v2/README.zh-CN.md)：保留响应回放、原生接通与测量 v2。
- [另一会话模型复核](../reports/model-review-v1/README.zh-CN.md)：首次标签、保留分歧与自动项目背景披露；不称严格独立盲审或人工验证。
- [发布协议](study_results.zh-CN.md)：精简数据检查与结果处理。

## 运行记录

- [用量与费用核算](operations/budget_accounting.zh-CN.md)：按批次保存的估算及覆盖范围。
- [预算执行](budgeted_execution.zh-CN.md)：历史执行护栏与逐请求预留，不表示应恢复已完成实验。

公开检查复算计数和汇总。完整轨迹语义与官方 reward 核验需要本地保留的原始输入，来源哈希本身不能认证它们。
