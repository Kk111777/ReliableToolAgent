# ReliableToolAgent

[English](README.md) | **简体中文**

**工具调用 LLM Agent 的可靠性评估与失败分析。**

项目包含一个 Hugging Face `smolagents` 运行时 fork，以及一项使用 τ³ 原生运行链的独立 retail 基准研究。

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB)](https://www.python.org/)
[![smolagents fork](https://img.shields.io/badge/Runtime-smolagents-FFD21E)](https://github.com/huggingface/smolagents)
[![τ³ retail](https://img.shields.io/badge/Evaluation-%CF%84%C2%B3%20retail-6F42C1)](benchmark/tau3/README.md)

## 核心工作（Highlights）

- 改造 Agent 运行时，加入逐工具调用轨迹、结构化错误和精确重复失败 Guard。
- 构建确定性故障测试，完成错误反馈 × 重试提示的受控消融。
- 实现 τ³ 离线分析器，检查工具执行、预期 WRITE 完成、重复调用、Simulator 终止和 reward 结果。
- 完成冻结的 **35 题 × 3 trial × 2 种 Simulator** 研究，保留全部 **210 个首次尝试**、请求费用及八个核验案例。
- 提供公开离线复算与任务级 bootstrap。有效配对为 **93/105**，未达到 90% 工程门槛，计划中的 train 复核没有启动。

最新工程修补补上了 state 引用变化误拦截、有限响应恢复与部分 WRITE 漏检，保留旧冻结结果。[修补设计与验证](docs/engineering_v2.zh-CN.md)。

<a id="key-findings"></a>

## 主要结果（Key Results）

WRITE 指改变业务状态的工具操作，例如换货或退货。

| 实验 | 结果 | 结论 |
|---|---|---|
| [Toy 错误反馈](reports/final_technical_report.md#4-structured-error--retry-framing-ablation)——每组 24 次 | retry ON 时，raw → structured 的重复失败为 **29 → 50** | 单靠错误元数据没有改善停止行为。 |
| [Toy Guard smoke](reports/final_technical_report.md#5-runtime-duplicate-guard)——每组 3 个任务 | 重复的**实际执行失败**为 **6 → 0** | 运行时阻止了已有失败历史的相同调用再次执行。 |
| [固定 Agent 的 Simulator 研究](reports/final_technical_report.md#9-user-simulator-confound)——每组 15 个 trial | 预期 WRITE 成功为 **5/15 → 14/15** | Simulator 选择改变了测得的 Agent 结果。 |
| [τ³ retail 审计](reports/final_technical_report.md#10-clean-benchmark-results)——20 次尝试 | 有效任务成功 **18/19**；跨轮精确重复 **0** | 在这个子集中，重试循环不是主要失败模式。 |
| [冻结 retail 主实验](reports/frozen_study/retail-holdout-v1/README.zh-CN.md)——210 个首次尝试 | U0 有效成功 **48/94**，U2 **93/103**；有效配对 **93/105** | 仍观察到 Simulator 敏感性，配对覆盖未达到工程门槛。 |

审计共 19 次有效运行，另有 T04 因评估器解析失败而无效。完整指标、模型配置及 toy 原始／v2 评分差异见[技术报告](reports/final_technical_report.md)。

冻结主实验保留 197 个有效评分、13 个无效尝试，没有新增正式补跑。完整三对 trial 的 25 个任务中，U2−U0 的任务级 reward 差为 **0.36 [0.24, 0.48]**。两组缺失情况不同，这个完整任务子集上的诊断不能证明 Agent 提升。[结果与边界](reports/frozen_study/retail-holdout-v1/README.zh-CN.md) · [English](reports/frozen_study/retail-holdout-v1/README.md)。

## 实现内容（What I Built）

### Agent 运行时

- 为每次调用记录工具名、规范化参数、结果／错误和执行状态，覆盖并行调用步骤。
- 将带有明确类型的工具错误传回 Agent 的 observation 和 memory。
- 对已记录为不可重试失败的相同调用加入 Guard，分别统计**尝试 / 执行 / 拦截**。

源码：[`agents.py`](src/smolagents/agents.py)、[`memory.py`](src/smolagents/memory.py)、[`utils.py`](src/smolagents/utils.py)。[Guard 测试](local_demo/test_duplicate_guard.py)覆盖拦截、合法重试及不同 run 的状态隔离。

### 评估框架

- 构建确定性的订单／库存任务、故障注入和业务结果检查，完成固定模型的 2×2 消融。
- 实现 τ³ 轨迹分析器，统计 READ/WRITE、精确重复、工具错误、终止、DB/NL reward、延迟和 token 使用。

源码：[`local_demo/`](local_demo/)、[`analyze_retail_observability.py`](benchmark/tau3/scripts/analyze_retail_observability.py)及 [`analyze_clean_u2_failure_audit.py`](benchmark/tau3/scripts/analyze_clean_u2_failure_audit.py)。

### 失败分析

固定 Agent，仅替换 User Simulator，调查预期 WRITE 为什么没有完成。将无效运行与已评分失败分开，沿消息、工具调用和最终业务状态分析案例。[八个新案例](reports/frozen_study/retail-holdout-v1/cases.zh-CN.md)涵盖动作顺序错误、原生恢复、终止和指标覆盖限制。

<a id="system--experiment-architecture"></a>

## 架构（Architecture）

```mermaid
flowchart LR
    T[任务] --> A[ToolCallingAgent]
    A --> C[工具调用尝试]
    C --> G{运行时重复失败 Guard}
    G -->|允许| E[工具 / toy 环境]
    G -->|拦截| B[拦截观察]
    E --> F[结果 / 结构化错误]
    F --> L[逐调用记录]
    B --> L
    L --> O[Observation / memory]
    O --> A
    L --> V[离线评估器]
```

Guard 检查**工具名 + 解析 state 引用后规范化且完全相同的参数 + 已记录的不可重试失败**，接下来的决策仍由 Agent 做出。被拦截的尝试会留下记录，但不会执行工具。

图中展示的是 toy 运行时。τ³ 研究使用官方 Agent 和 orchestrator；复用的是测量流程，Guard 留在 toy 实验中。

## 基准研究带来的发现（What the Benchmark Revealed）

Reward 为零可能来自 Agent 决策、工具执行、Simulator 行为，也可能来自评估器或基础设施错误。轨迹记录帮助区分这些情况，再判断是否需要恢复机制。

历史五任务开发研究中，替换 Simulator 使提前终止从 **8/15 降至 0/15**，预期 WRITE 完成从 **5/15 升至 14/15**。随后 20 题审计没有跨轮精确重复。新的 35 题研究观察到少量重复，其中包括成功的 READ；这不能证明重复失败循环或原生 Guard 收益。本轮仍停止扩展控制器。

![固定 Agent 的 Simulator 研究：WRITE 完成与提前终止](assets/simulator_ablation.png)

## 代表案例（Representative Case）

**T05** 是历史 20 题开发审计中唯一有效的 reward-zero 运行。台灯换货成功后，用户改为要求水瓶退货，Simulator 在预期 return WRITE 前结束并转接会话。轨迹没有工具失败或精确重复，完成行为与 Simulator 终止仍交织在一起。[查看案例分析](reports/residual_case_T05.md)。

## Retail 配对复核

[35 题 test 主实验](reports/frozen_study/retail-holdout-v1/README.zh-CN.md)于 2026-10-04 完成固定的 210 槽队列，有效配对覆盖 88.57%，低于预设的 90% 门槛。因此独立的 [20 题 train 计划](benchmark/tau3/studies/retail-replication-v1/README.zh-CN.md)没有启动：120 个计划槽位，无模型成绩。计划覆盖不等于已完成证据。

运行器保留每个首次尝试和中断轨迹，记录请求用量、未知费用预留和进程锁。公开精简包支持重算汇总与区间，八个脱敏案例支持复核工具计数；完整轨迹留在本地。[预算运行说明](docs/budgeted_execution.zh-CN.md)介绍保持冻结协议不变的费用核算。

[单批次报告说明](docs/study_results.zh-CN.md)介绍离线双语报告，以及未完成覆盖、基础设施失败和补跑的统计口径。

## 快速开始（Quick Start）

需要 Python 3.12 和 `uv`。以下检查不需要模型凭据。

```bash
git clone https://github.com/Kk111777/ReliableToolAgent.git
cd ReliableToolAgent
bash setup-local.sh
.venv/bin/python -m pytest -q local_demo
.venv/bin/python scripts/audit_packaging_evidence.py
.venv/bin/python benchmark/tau3/scripts/study_evidence.py audit \
  --input reports/frozen_study/retail-holdout-v1/public_evidence.json
```

这些命令运行确定性测试并检查公开证据，包括冻结批次的汇总与区间。[复现说明](docs/reproduction.zh-CN.md)另列出案例复核及双语报告再生成步骤。重新调用模型需要独立基准环境和凭据。

## 仓库结构（Repository Structure）

```text
src/smolagents/   运行时改动：调用记录、结构化错误、重复失败 Guard
local_demo/      受控可靠性实验与项目测试
benchmark/tau3/  原生基准运行脚本、分析器、结果快照
reports/         方法、完整结果、案例分析、证据索引
scripts/         证据检查、文档检查、图表生成
```

## 研究范围（Scope）

- Guard 在受控 toy 实验中验证，没有测得其在 τ³ 上的性能收益。
- 公开原生结果包括历史 20 题开发审计，以及未达到工程验收的独立 35 题配对 test 研究；两者都不是完整排行榜提交。
- Simulator 研究衡量固定 Agent 下的评估敏感性，不是模型通用排名。

## 进一步阅读（Further Reading）

- [技术报告](reports/final_technical_report.md)：实验设计、完整指标、评分说明及限制。
- [证据索引](reports/artifact_index.md)：代码、公开快照和本地保留来源。
- [复现说明](docs/reproduction.zh-CN.md)：新克隆的仓库能检查什么，哪些步骤需要原始轨迹或服务商凭据。

基于 Hugging Face `smolagents` commit `30bb1161095dbae2271e6bc3cc4c219cc3897a57`。保留上游归属及 [Apache 2.0 许可证](LICENSE)。
