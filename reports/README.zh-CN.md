# 报告与证据

[English](README.md) | **简体中文**

从实现或实验设计，到保留的结果，再到公开复算入口，可以沿下面的文件检查。

| 内容 | 入口 |
|---|---|
| 已完成的工程修补 | [接口与边界](../docs/engineering_v2.zh-CN.md) · [验证记录](engineering-v2/README.zh-CN.md) |
| 冻结 35 题主实验 | [结果与分母](frozen_study/retail-holdout-v1/README.zh-CN.md) · [精简包](frozen_study/retail-holdout-v1/public_evidence.json) |
| 测量 v2 | [精简诊断](engineering-v2/measurement.json)：全部 210 个首次身份；有效轨迹的部分完成候选修正 |
| 另一会话模型复核 | [首份结果与规则分歧](model-review-v1/README.zh-CN.md) · [逐行标签记录](model-review-v1/summary.json) |
| 八个代表案例 | [案例说明](frozen_study/retail-holdout-v1/cases.zh-CN.md) · [工具计数与来源](frozen_study/retail-holdout-v1/case_index.json) |
| 历史受控与开发实验 | [技术报告](final_technical_report.md) · [T05 分析](residual_case_T05.md) |
| 每项指标的代码与来源 | [证据索引](artifact_index.md) |
| 离线运行与新克隆验证 | [复现说明](../docs/reproduction.zh-CN.md) |
| 历史 toy 评分版本差异 | [来源与评分审计](packaging_audit_20261003.md) |

新工程接通记录为四条有效尝试，但没有触发恢复分支。主实验固定队列已执行，93/105 有效配对低于工程门槛，train 扩展未启动。20 片段模型复核保留 117/120 一致及三处分歧，不能作为总体准确率。

运行 `make verify-project` 可检查项目测试、公开精简包和文档链接，不调用模型。完整原始轨迹保留在本地；公开复算检查汇总、计数和身份一致性，不认证未公开的业务语义。
