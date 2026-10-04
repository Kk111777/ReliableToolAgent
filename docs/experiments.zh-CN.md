# 实验与发现

[English](experiments.md) | **简体中文** · [项目概览](../README.zh-CN.md)

实验围绕两个问题展开：运行时防护能否阻止一种明确的重复失败，这种失败在原生 retail 任务中是否仍然重要？

## 受控工具失败

最初的 2×2 实验改变原始/结构化错误反馈，以及是否启用重试引导。启用重试引导时，结构化反馈让记录中的重复失败从 29 增至 50；更清楚的错误信息本身没有稳定带来更好的停止决策。

另一项三个任务的 Guard smoke 把重复的实际执行失败从 6 降至 0。Guard 检查已知不可重试失败；state 别名回归测试另外验证目标改变后仍可调用。Smoke 与回归检查回答的是不同问题。

[历史技术报告](../reports/final_technical_report.md) · [评分版本](../reports/packaging_audit_20261003.md) · [Guard 测试](../local_demo/test_duplicate_guard.py)

## 原生 retail 评估

τ³ 分析链使用官方 Agent、工具、环境与评分，没有部署 smolagents Guard。早期干净开发审计的有效运行没有出现跨轮精确重复调用，这削弱了直接把 toy 控制器扩展到 retail 的依据。

随后固定研究使用 35 个官方 test 任务，每题三个 trial，对比 U0/U2 User Simulator 配置。有效成功分别为 48/94 和 93/103。在三对 trial 均有效的 25 个任务上，U2−U0 平均 reward 差为 +0.36，95% 任务级 bootstrap 区间为 [0.24, 0.48]，表明固定 Agent 下的结果对 Simulator 敏感。

队列完成全部 210 个首次尝试。配对覆盖为 93/105，低于预设 90% 门槛，train 扩展保持未启动。两组缺失情况不对称，因此完整任务区间属于有条件的诊断。

[已完成研究](../reports/frozen_study/retail-holdout-v1/README.zh-CN.md) · [历史审计](../reports/final_technical_report.md#10-clean-benchmark-results)

## 部分完成分析

原终止指标只标记“任何参考 WRITE 都没成功”的轨迹。修订后的分析器按出现次数逐个匹配参考动作，也保留“完成了一部分动作后停止”的任务。在 197 条有效轨迹中，新增 13 个部分完成候选；案例 C03 在最后一条 User 终止消息前完成了三个参考 WRITE 中的两个。

[测量设计](engineering_v2.zh-CN.md#测量-v2把部分完成保留下来) · [案例](../reports/frozen_study/retail-holdout-v1/cases.zh-CN.md)

## 支持记录

响应适配、保留响应回放、复核与执行核算见[技术附录](technical_appendix.zh-CN.md)，离线复现从[复现说明](reproduction.zh-CN.md)开始。已检查的原生故障没有提供进一步扩展控制器所需的证据，因此本轮停在失败分析与评估。
