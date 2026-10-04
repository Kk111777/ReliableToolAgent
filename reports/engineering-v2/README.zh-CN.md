# 工程修补 v2：验证记录

[English](README.md) | [设计、接口与边界](../../docs/engineering_v2.zh-CN.md)

本目录记录 Guard 参数身份修补、响应适配器和测量 v2 的验证。冻结主实验仍为 210 个首次尝试、197 个有效评分、93/105 有效配对；它没有通过 90% 工程门槛。下面的材料不改写这个结论。

| 检查 | 证据 | 能说明什么 |
|---|---|---|
| state 引用改变的 Guard 反例 | [回归合同](../../local_demo/test_duplicate_guard.py) | 新目标不再被旧目标的失败误拦；同一目标仍可拦截。 |
| 历史 evaluator 格式故障 | [六响应离线回放](evaluator_replay.json) | 6/6 去完整围栏后通过严格校验，原 payload 值完全保持。 |
| 空 User 输出与请求费用 | [响应测试](../../benchmark/tau3/tests/test_engineering_worker.py)、[预算合同](../../benchmark/tau3/tests/test_engineering_pilot.py) | 空响应最多再生成一次；额外 HTTP 有费用记录，预算不足不请求，取消不重试。 |
| 197 条有效轨迹的测量覆盖 | [精简数据](measurement.json) | 终止时遗漏参考 WRITE 候选 48→61；新增 13 条为部分完成。 |
| 新原生接通检查 | [四槽记录](integration.json) | 工程协议的连接、运行和计费行为；不估计故障率或算法收益。 |

仅借助公开文件可复核汇总、身份和哈希，不能重新判断未公开轨迹的语义。六条历史响应来自两个已知失败，有目的选择；180 项旧开发字段及八案例核对不是独立人工验证。测量 v2 也是同作者回顾性检查。

最终接通检查 **4/4 有效**，保留 **67 次 HTTP 请求**；原价已测量费用 **0.4994654 元**，含一次未知用量预留的保守原价 **0.5175894 元**，不是服务商账单。本次没有触发空 User 重试或 evaluator 格式恢复，不能把接通成功作为恢复分支的线上效果证据。该分支由故障合同与六条真实保留响应回放验证。

## 离线复核

在仓库根目录运行，不需要凭据：

```bash
.venv/bin/python -m pytest -q local_demo benchmark/tau3/tests
.venv/bin/python benchmark/tau3/scripts/engineering_evidence.py \
  --audit reports/engineering-v2/integration.json
.venv/bin/python benchmark/tau3/scripts/measurement_v2.py audit \
  --input reports/engineering-v2/measurement.json \
  --evidence reports/frozen_study/retail-holdout-v1/public_evidence.json \
  --cases reports/frozen_study/retail-holdout-v1/case_index.json
```

`measurement.json` 的公开审核先验证 v1 包，再核对全部首次身份、源哈希和旧字段，重算新汇总与案例对应。原始语义复算入口为 `measurement_v2.py export`，需要本地保留的 raw 目录。

## 运行范围

工程接通任务为已暴露开发任务 0、5，各 U0/U2 一次，共四个计划槽。模型、提示、8192 completion 上限及 600 秒尝试截止沿用原设置；适配器规则单独版本化。全部首次保留，没有针对 reward 的重跑。旧 train 计划仍未启动。

历史 toy Guard 结果来自修补前的运行。本次 Guard 改动以接口合同验证；新的原生接通检查没有部署 smolagents Guard。只有发现真实目标故障并制定新对照实验，才能讨论原生控制器收益。
