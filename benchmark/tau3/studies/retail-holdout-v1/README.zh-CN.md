# Retail 配对留出集复核

[English](README.md) | **简体中文**

这项实验检查：旧开发集上观察到的 User Simulator 敏感性，是否也出现在本地尚未运行过的 retail 任务中。原生 Agent、prompt、工具、环境和官方评分规则保持固定。U0 的 User Simulator 使用 Qwen3.5 Flash，U2 使用 Qwen3.8 Max。实验衡量评估配置的影响，不将结果描述为 Agent 能力提升。

## 已发布状态

[最终主批次](../../../../reports/frozen_study/retail-holdout-v1/README.zh-CN.md)于 2026-10-04 保留全部 210 个正式首次尝试：197 个有效评分、13 个无效尝试、0 新增正式补跑。有效配对 93/105（88.57%），低于冻结的 90% 工程门槛。固定队列已完成，train 复核和付费次级补跑没有启动。公开精简包内的 effective manifest 标识实际运行；本页保留原设计说明。

## 冻结设计

| 项目 | 配置 |
|---|---|
| 基准 | `sierra-research/tau2-bench`，`b7ea9074c1cba482b30687fecdb5c8425fd6f619` |
| 任务 | 从官方 retail test split 中排除本地已运行 ID 后剩余的 35 个任务 |
| 配对 | 每任务三个 trial，U0/U2 使用相同 seed；105 对、210 个计划主分析槽位 |
| 顺序 | 相邻任务／trial 对交替采用 U0/U2 顺序，串行运行 |
| Agent 与 NL evaluator | `openai/qwen3.5-flash-2026-02-23` |
| User Simulator | U0 使用同一 Flash snapshot；U2 使用 `openai/qwen3.8-max-2026-09-02` |
| 生成参数 | `temperature=0`、`max_tokens=512`、`max_completion_tokens=8192` |
| 限制 | 请求超时 60s、请求重试 3 次、评估器解析重试 2 次、200 steps |
| 完整尝试 | 含评估阶段在内最多 600s；父进程取消时保留部分轨迹 |
| 补跑 | 基础设施错误最多补跑十次，采用新 attempt ID；已评分的失败不补跑 |

[Manifest](manifest.json) 在正式运行前固定了顺序、源码哈希、分析器版本、价格、预算及停止条件。第一次 smoke 发现 `max_tokens` 没有限制推理 token，该尝试单独保留。修订后的配置增加总输出上限，历史实验没有这一限制，也没有完整尝试超时，因此两者不合并统计。[服务商参数说明](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。

“留出”仅表示这些任务没有出现在保留的本地运行记录中。它们是公开基准任务，无法确认模型训练时是否见过。[任务审计](task_audit.json) 记录了场景哈希、最接近的旧任务、WRITE 家族和共享用户实体。T36/T38 使用同一场景模板和订单，但要求不同业务结果；主分析保留二者，另按用户实体聚类 bootstrap，并预先规定排除 T38 的敏感性分析。

## 测量检查

[标注面板](measurement_panel.json) 包含 30 条精简开发轨迹及检查标签。[审计](measurement_audit.json) 核对 180 个字段，选定面板中有八条确认后终止候选和 22 条负例。标签由 Codex 检查轨迹得到，检查者与分析器作者相同；这是实现一致性检查，不是独立人工标注，也不能据此声称分析器在新任务上的准确率。

十二个[合成协议片段](../../tests/fixtures/event_fragments.json)覆盖明确错误标志、缺失返回、同消息重复、ID 重用、参数变化、确认和临时改需求，不增加基准任务。工具返回仅在当前调用后的响应窗口中按 ID 匹配，缺失或歧义返回保留为 unknown。返回文本包含“failed”不等于工具执行失败。

官方 final／DB reward 与参考动作覆盖率分别报告。没有匹配预期 WRITE，可能表示请求未完成、采用了其他有效路径，也可能涉及策略限制。确认词和终止标记只生成候选事件，不能直接判定失败原因。

## 运行与检查

在项目根目录执行下列检查，不需要凭据，也不调用模型：

```bash
.venv/bin/python -m pytest -q benchmark/tau3/tests
.venv/bin/python benchmark/tau3/scripts/audit_frozen_study.py
.venv/bin/python benchmark/tau3/scripts/run_frozen_study.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --output artifacts/frozen_study/retail-holdout-v1c --phase formal
```

以下原始命令保留作为历史 smoke／复跑说明。当前实验恢复必须使用[外部费用策略](../../../../docs/budgeted_execution.zh-CN.md)，原预算值已被覆盖。付费运行需要将独立固定版本基准放在 `tau2-bench-baseline/`，并为它创建自己的 `.venv`。项目根目录的 `.env` 保存 `OPENAI_API_KEY` 和 `OPENAI_API_BASE`，该文件已被 Git 忽略。运行器只有收到 `--run` 才读取凭据，随后调用基准自己的解释器：

```bash
.venv/bin/python benchmark/tau3/scripts/run_frozen_study.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --output artifacts/frozen_study/retail-holdout-v1c --phase smoke --run

.venv/bin/python benchmark/tau3/scripts/run_frozen_study.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --output artifacts/frozen_study/retail-holdout-v1c --phase formal --run

.venv/bin/python benchmark/tau3/scripts/analyze_frozen_study.py \
  --input artifacts/frozen_study/retail-holdout-v1c \
  --output artifacts/frozen_study/retail-holdout-v1c/analysis
```

再次执行同一运行命令，会继续缺失槽位，不重复已完成的付费尝试。`--retry-infrastructure` 只为基础设施错误创建新尝试，原始尝试保留在账本中。进程锁阻止同时启动两个运行器；不可覆盖的 job／outcome 文件和哈希用于检查证据变化。

每次尝试保留 `identity.json`、`job.json`、`simulation.json`、`calls.jsonl`、`requests.jsonl`、可选的评估器记录及 `outcome.json`。父进程追加 `attempts.jsonl`，更新 `status.json`。用量记录区分 Agent、User 和 evaluator，包含评估器无效输出及可观察到的 SDK 重试。费用账本不保存请求 prompt、header、密钥或服务商异常消息。

## 在新克隆的仓库中复跑

原始 manifest 也记录了用于核对本地任务暴露的历史私有轨迹哈希。这些属于来源证据，不是原生 Agent 的运行输入。准备好固定版本基准后，可以生成独立复跑 manifest：保留历史哈希作为来源记录，只核验公开文件与实际运行依赖。

```bash
.venv/bin/python benchmark/tau3/scripts/prepare_frozen_replay.py \
  --manifest benchmark/tau3/studies/retail-holdout-v1/manifest.json \
  --study-id my-retail-replay --output artifacts/my-retail-replay/manifest.json
```

随后将上方运行命令的 manifest 换为该文件，并使用新的输出目录。准备步骤不调用 API。复跑需要自己的四次 smoke，会产生新的输出和费用，不代表原实验记录。以后付费复跑前，应核对配置中注明日期的服务商价格。

## 分析与停止条件

- 主分析使用首次尝试。分别报告有效首次尝试中的成功率、全部计划槽位中的成功比例，以及基础设施错误／超时。补跑恢复后的结果单列为次级分析。
- 置信区间以任务为单位重采样，同一任务的三个 trial 对一起进入抽样；5,000 次，seed 为 `20261003`。同时报告共享实体聚类和任务家族敏感性结果。
- 有效配对完整度至少 90%、首次尝试中的基础设施错误／超时至多 10%，属于工程验收条件，不是显著性检验。缺失配对和不完整的三次 trial 任务不会隐藏。
- 价格来自[服务商北京地域价格表](https://help.aliyun.com/zh/model-studio/model-pricing)。已返回用量按原价估算，包含推理输出；缺失用量和未完成请求保留保守预算预留。估算不等于已核对账单或账户余额。
- 历史 manifest 记录了 300 元上限，当前执行已由外部策略覆盖；恢复按已确认折扣、当前授权余额及历史请求预留核算。原最多 224 次模拟尝试的限制保留。连续三次基础设施错误／超时后停止并诊断。
- 不根据留出集结果调整 Agent、Guard、prompt 或事件规则。新增恢复机制需要另立假设及评估集；目标失败不足五个不同公开任务时，停止扩展控制器。

完整轨迹保留在本地。公开精简指标支持重算汇总和置信区间，但不能独立核实每条官方 reward；选定的开发片段支持在没有 API 的情况下检查事件分析器。

## 精简证据复算

[`study_evidence.py`](../../scripts/study_evidence.py) 核对本地 outcome、轨迹和请求记录的哈希后，导出不可覆盖的精简证据包。它的离线 `audit` 入口重算冻结汇总、任务级区间、缺失槽位、延迟及各角色用量。只累加已返回用量的输入和输出 token；推理 token 已包含在输出中。缺失用量单列，并保留费用预留。校验和用于识别文件和检查一致性；没有私有轨迹时，它不能认证官方 reward。

[已发布精简包](../../../../reports/frozen_study/retail-holdout-v1/public_evidence.json)包含全部 210 个首次尝试与四个 smoke。公开 clone 可以直接复算该文件。保留本地原始记录时，可向新文件导出：

```bash
.venv/bin/python benchmark/tau3/scripts/study_evidence.py export \
  --input artifacts/frozen_study/retail-holdout-v1c \
  --output artifacts/frozen_study/retail-holdout-v1c/public_evidence.json

.venv/bin/python benchmark/tau3/scripts/study_evidence.py audit \
  --input artifacts/frozen_study/retail-holdout-v1c/public_evidence.json
```

导出需要保留的本地证据；复算只需精简证据包及对应版本的公开源码，不需要模型凭据或原生基准 checkout。默认拒绝未完成的实验和已存在的输出文件。`--allow-incomplete` 只用于明确标记的本地诊断，会注明未完成并列出尚未开始的槽位。[合同测试](../../tests/test_study_evidence.py)覆盖身份错乱、汇总篡改、用量缺失和补充实验的独立分层。
