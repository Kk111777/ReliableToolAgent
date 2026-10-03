# 复现说明

[English](reproduction.md) | **简体中文** · [项目概览](../README.zh-CN.md)

项目提供三种不同的检查。根据手头的文件和凭据选择对应步骤。

| 目标 | 所需输入 | 模型 API 调用 |
|---|---|---|
| 检查公开证据与确定性测试 | 本仓库及其本地 Python 环境 | 无 |
| 重新核对已记录的实验 | 保留的原始轨迹与已有重评分 | 无 |
| 重新运行 τ³ 研究 | 独立的固定版本基准仓库与服务商凭据 | 有 |

## 配置项目环境

安装 `uv`，使用 Python 3.12。从新克隆的仓库开始：

```bash
git clone https://github.com/Kk111777/ReliableToolAgent.git
cd ReliableToolAgent
bash setup-local.sh
```

配置脚本使用 Python 3.12.14 创建 `.venv`，安装 `requirements-local.lock` 并检查依赖。下文使用 `.venv/bin/python`，确保命令在这一环境中运行。

## 检查公开文件

```bash
.venv/bin/python -m pytest -q local_demo
.venv/bin/python scripts/audit_packaging_evidence.py
.venv/bin/python scripts/check_markdown_links.py
```

测试覆盖脚本驱动的故障框架、错误处理、逐调用记录及 Guard 行为，不调用模型 API。证据检查核对公开快照、评分版本和图表来源；Markdown 检查核对本地文档链接、锚点和图片，不访问外部网址。

新克隆的仓库包含精简结果快照，不包含原始模型轨迹。这些命令检查实现和公开文件，不会独立复算全部实验结果，也不会重跑基准。

## 检查本地保留的原始证据

原始本地工作区的路径见[证据索引](../reports/artifact_index.md)。完整审计需要以下目录：

```text
artifacts/qwen35-flash-ablation/
artifacts/rescored/ablation/
artifacts/qwen35-flash-guard-v1/
tau2-bench-baseline/data/simulations/
tau2-bench-baseline/data/analysis/retail-observability/
```

```bash
.venv/bin/python scripts/audit_packaging_evidence.py --local
.venv/bin/python -m local_demo.compare_ablation --task-id P03 --repeat 1
```

第一条命令复算已记录的汇总指标，对照原始与已有 v2 评分，并检查来源哈希。第二条打印选定任务的消融轨迹对比。两者只读取保留文件，不修改它们。

E2 原始任务成功为 23/24，已有 evaluator-v2 重评分为 24/24，使用的是相同回答和轨迹。[评分审计](../reports/packaging_audit_20261003.md#discrepancy-original-e2-versus-evaluator-v2)解释了措辞修正。报告结果时应分别注明这两个版本。

## 运行或分析 τ³

[τ³ 文档](../benchmark/tau3/README.md)列出固定 commit、模型配置、独立环境、运行脚本及离线分析器。运行脚本会产生付费模型调用；离线分析器读取已保存的运行记录，并写出派生分析报告。上述项目环境与基准环境相互独立。

[技术报告](../reports/final_technical_report.md#13-limitations)说明开发子集、Simulator 配置、评估器重试及成本数据缺失。从已有计数重新生成图表的步骤见[图表说明](../assets/README.md)。

## 检查配对留出集协议

[留出集说明](../benchmark/tau3/studies/retail-holdout-v1/README.zh-CN.md) 介绍新任务选择、首次尝试分母、输出限制、请求费用记录和任务级 bootstrap。下列公开检查不调用 API：

```bash
.venv/bin/python -m pytest -q benchmark/tau3/tests
.venv/bin/python benchmark/tau3/scripts/audit_frozen_study.py
```

30 条开发集检查轨迹与十二个合成协议片段用于核对事件测量，不是新增基准结果，也不是独立人工标注。正式运行的精简指标发布后支持离线重算汇总；完整官方评分核验仍需要本地原始轨迹。

[独立的分层补充复核](../benchmark/tau3/studies/retail-replication-v1/README.zh-CN.md) 扩大任务覆盖，test 与 train 两个批次分别报告。

[精简证据命令](../benchmark/tau3/studies/retail-holdout-v1/README.zh-CN.md#精简证据复算)将本地原始记录核验／导出与公开离线汇总复算分开。复算检查身份、源码版本、费用覆盖和重算汇总，不调用模型，也不独立重评私有轨迹。最终证据包待运行及审阅完成后发布。
