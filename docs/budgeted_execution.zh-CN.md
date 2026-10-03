# 按预算恢复实验

[English](budgeted_execution.md) | **简体中文**

实验运行期间，已保存的预算可能不再适用。[预算运行器](../benchmark/tau3/scripts/run_budgeted_study.py)用一份独立的本地费用策略恢复原冻结顺序，保持 Agent、prompt、评分、输出限制、任务选择及原始 manifest 不变。原运行器和监督器作为历史实现保留；其中保存的预算值不代表恢复运行时的授权。

## 费用口径

费用清单读取策略列出的全部实验目录，覆盖初始 preflight、原始 smoke、正式执行及补跑。每次尝试以 `study_id / slot_id / attempt` 标识。完全相同的 smoke 副本只计一次；副本冲突则停止。缺失 outcome、截断的请求账本、改变的证据或历史余额基线也会阻止执行。

请求账本保留原价计算。折扣乘数放在本地策略里，需要明确确认，不能从两个近似余额的差值猜测折扣。折后估算与服务商账单分别陈述；缺失请求用量仍按同一乘数保留预留费用。

如果从当前剩余额度开始，策略先保存历史尝试及其哈希作为不可变基线。合计上限为：

```text
历史已测量的原价费用 × 已确认的折扣乘数 + 当前报告的剩余额度
```

当前保守扣费同时包含已测量费用和缺失用量预留。从合计上限减去保守扣费，就会为历史未知请求预留一次费用。后续尝试继续消耗剩余额度，重启不会把它重置。余额是报告的输入，不是独立核对过的服务商账单；实验之外的并发调用不在这份清单里。

## 接口与运行命令

| 接口 | 输入 | 输出与检查 |
|---|---|---|
| `CostInventory.records()` / `snapshot()` | 保留的实验目录 | 去重付费记录、请求数、已测量费用、保守扣费和证据哈希 |
| `BudgetPolicy.load()` | 本地 JSON 策略和实验根目录 | 校验上限、折扣、必须保留的历史目录、冻结 manifest 哈希及可选余额基线 |
| `BudgetPolicy.allowance()` | 当前费用快照 | 分配给原 worker 的剩余**原价**额度，向下取整 |
| `execute(..., run=False)` | 冻结实验和本地策略 | 核验来源、锁、账本和预算，不读取凭据、不启动 worker 或付费请求 |

本地策略记录 `combined_cap_rmb`、`discount_factor`、`discount_source`、`cost_basis`、`accounting_outputs`、`required_existing_outputs`、`frozen_manifest_sha256` 及执行就绪状态。余额策略还引用已保存基线的路径和哈希。应从保留的费用清单生成这些字段，在基线检查及 dry-run 通过后设置就绪。账户余额及这些运行文件留在 Git 之外。

在项目根目录运行：

```bash
.venv/bin/python -m pytest -q benchmark/tau3/tests/test_budgeted_study.py

.venv/bin/python benchmark/tau3/scripts/run_budgeted_study.py \
  --input artifacts/frozen_study/retail-holdout-v1c \
  --policy artifacts/frozen_study/operational_budget_policy.json
```

增加 `--run` 后，运行器才读取被忽略的根目录 `.env`，并在上述检查通过后启动付费尝试。运行器同时持有全局费用锁、旧监督器锁及各实验运行锁。每个 job 保存历史费用快照、费用策略哈希和运行器哈希。冻结 worker 在每个 HTTP 请求前检查分配额度，观察到的重试也逐次计入。在串行执行下，历史扣费加上 worker 的剩余额度就是全局上限。

`--limit N` 在完成 N 个新尝试后停止。普通模式跳过所有已有槽位，包括已评分失败和中断记录。`--retry-infrastructure` 是独立的次级复核：策略必须记录已诊断的首次 outcome 哈希，不重跑 valid 或 budget-stop 结果，每个槽位最多增加一次尝试，并遵守冻结的补跑总数限制。预算停止意味着当前运行不能继续；连续三次执行故障需要诊断。

取消时，运行器先让当前 worker 保存部分证据，再释放锁。运行期间改变策略或运行器会阻止下一次尝试；冻结源码发生变化也会被拒绝。请求预留无法容纳时不会发出请求。如果返回用量超过预留，超额会被记录，执行停止；护栏无法撤销服务商已经产生的扣费。

## 验证与结果边界

[合同测试](../benchmark/tau3/tests/test_budgeted_study.py)覆盖复用 smoke、preflight 和补跑费用、缺失用量、截断证据、折扣、余额基线、竞争锁、dry-run 隔离及请求发出前的拒绝。它们验证费用记录和执行行为，不证明模型效果。

两个冻结诊断字段需要按其实际范围解释。`terminal_before_reference_write_candidate` 要求**没有任何**参考 WRITE key 成功，因此可能漏掉部分完成后仍缺少的 WRITE。`agent_after_terminal_user` 实际记录最后一条用户消息之后是否有 assistant；只有 `terminal_marker` 是 STOP 或 TRANSFER 时，才对应结束消息之后的响应检查。没有用户消息时该值也可能为 True。这些限制如实报告，不改写冻结指标。

本次实验曾在 210 个正式首次槽位中的 108 个完成后暂停：101 个 valid、五个基础设施错误，以及两次人为取消。冻结 worker 将这两次取消保存为 timeout，不能把它们算作模型失败。暂停时，120 槽位的 train 补充复核尚未启动。这是有日期的进度快照，不是完整 benchmark 结果；最终精简证据和两个批次报告在执行及审阅后发布。
