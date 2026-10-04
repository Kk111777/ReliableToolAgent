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

另有[上游回归流程](../.github/workflows/tests.yml)，使用 uv 0.12.23，在独立 CI 环境中分别检查 Python 3.10 和 3.12，测试及 Python 子进程使用同一个已激活的环境。它要求使用 `tokenizers` 预编译包：此前的依赖解析选择了 0.10.3，随后在 Python 3.12 的 Rust 源码构建阶段失败。[uv 的包选项](https://docs.astral.sh/uv/reference/cli/#uv-pip-install)让解析器选择兼容的预编译包，不覆盖依赖要求。应分别核对两个 job 的 pytest 结果，依赖解析成功本身不代表回归测试通过。

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

[独立的 train 分层计划](../benchmark/tau3/studies/retail-replication-v1/README.zh-CN.md)因主批次配对门槛未通过而没有启动。计划任务不能当作已测结果。

[精简证据命令](../benchmark/tau3/studies/retail-holdout-v1/README.zh-CN.md#精简证据复算)将本地原始记录核验／导出与公开离线汇总复算分开。复算检查身份、源码版本、费用覆盖和重算汇总，不调用模型，也不独立重评私有轨迹。现在可检查[主批次最终证据包](../reports/frozen_study/retail-holdout-v1/README.zh-CN.md)：210 个首次尝试保留，未达到工程验收。计划中的 train 批次没有启动，也没有模型成绩。

[单批次报告说明](study_results.zh-CN.md) 从一份已审计的精简包生成对应的中英文报告，显示首次、补跑和未启动槽位，也说明预算或工程条件停止时的结果边界。


当前付费执行使用[按预算恢复说明](budgeted_execution.zh-CN.md)，分别保留原价、已确认折扣、报告余额和缺失用量预留；旧 manifest 上限只代表历史计划。默认命令不调用模型。


## 复算已发布批次

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

输出使用新目录。生成的 `summary.json`、`report.md`、`report.zh-CN.md` 应与公开文件逐字节一致。检查不需要原始数据或付费调用，复核的是精简汇总和案例计数，不能独立核验原始官方评分。


## 工程修补 v2

参见[接口与故障恢复](engineering_v2.zh-CN.md)及[公开离线检查](../reports/engineering-v2/README.zh-CN.md)。新版本不改写旧冻结批次。
