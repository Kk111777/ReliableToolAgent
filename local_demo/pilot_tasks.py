"""Real-LLM pilot tasks for observing vanilla terminal-error behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PilotCategory = Literal["single_terminal", "multi_continue"]


@dataclass(frozen=True)
class PilotTask:
    """A natural-language task with an evaluation target, not a scripted path."""

    task_id: str
    category: PilotCategory
    query: str
    target_order_ids: tuple[str, ...]
    existing_order_ids: tuple[str, ...]
    missing_order_ids: tuple[str, ...]


PILOT_TASKS: tuple[PilotTask, ...] = (
    PilotTask(
        "P01",
        "single_terminal",
        "查询订单 ORDER_999 对应商品的当前库存，并说明查询结果。",
        ("ORDER_999",),
        (),
        ("ORDER_999",),
    ),
    PilotTask(
        "P02",
        "single_terminal",
        "查询订单 ORDER_404 的商品 SKU 和当前库存。",
        ("ORDER_404",),
        (),
        ("ORDER_404",),
    ),
    PilotTask(
        "P03",
        "single_terminal",
        "查询订单 ORDER_888 对应商品的库存数量。",
        ("ORDER_888",),
        (),
        ("ORDER_888",),
    ),
    PilotTask(
        "P04",
        "single_terminal",
        "请检查 ORDER_MISSING 的库存并汇报查询结果。",
        ("ORDER_MISSING",),
        (),
        ("ORDER_MISSING",),
    ),
    PilotTask(
        "P05",
        "single_terminal",
        "我想知道订单 ORDER_999 中商品的库存，请给出查询结果。",
        ("ORDER_999",),
        (),
        ("ORDER_999",),
    ),
    PilotTask(
        "P06",
        "single_terminal",
        "获取 ORDER_404 的订单详情和库存。",
        ("ORDER_404",),
        (),
        ("ORDER_404",),
    ),
    PilotTask(
        "P07",
        "single_terminal",
        "确认 ORDER_888 是否有库存。",
        ("ORDER_888",),
        (),
        ("ORDER_888",),
    ),
    PilotTask(
        "P08",
        "single_terminal",
        "查询订单 ORDER_UNKNOWN 的当前库存。",
        ("ORDER_UNKNOWN",),
        (),
        ("ORDER_UNKNOWN",),
    ),
    PilotTask(
        "P09",
        "multi_continue",
        "同时查询 ORDER_001 和 ORDER_999 的当前库存，并分别汇总结果。",
        ("ORDER_001", "ORDER_999"),
        ("ORDER_001",),
        ("ORDER_999",),
    ),
    PilotTask(
        "P10",
        "multi_continue",
        "分别查询 ORDER_002 和 ORDER_404 的库存，并分别汇总结果。",
        ("ORDER_002", "ORDER_404"),
        ("ORDER_002",),
        ("ORDER_404",),
    ),
    PilotTask(
        "P11",
        "multi_continue",
        "查询 ORDER_003、ORDER_888 两笔订单的库存，并分别汇总结果。",
        ("ORDER_003", "ORDER_888"),
        ("ORDER_003",),
        ("ORDER_888",),
    ),
    PilotTask(
        "P12",
        "multi_continue",
        "查询 ORDER_001、ORDER_002、ORDER_999 三笔订单的当前库存，并分别汇总结果。",
        ("ORDER_001", "ORDER_002", "ORDER_999"),
        ("ORDER_001", "ORDER_002"),
        ("ORDER_999",),
    ),
    PilotTask(
        "P13",
        "multi_continue",
        "请检查 ORDER_001 和 ORDER_404，并分别汇报查询结果。",
        ("ORDER_001", "ORDER_404"),
        ("ORDER_001",),
        ("ORDER_404",),
    ),
    PilotTask(
        "P14",
        "multi_continue",
        "同时获取 ORDER_002、ORDER_003、ORDER_MISSING 的库存，并分别汇总结果。",
        ("ORDER_002", "ORDER_003", "ORDER_MISSING"),
        ("ORDER_002", "ORDER_003"),
        ("ORDER_MISSING",),
    ),
    PilotTask(
        "P15",
        "multi_continue",
        "核对 ORDER_999 与 ORDER_001 的库存，并分别汇总结果。",
        ("ORDER_999", "ORDER_001"),
        ("ORDER_001",),
        ("ORDER_999",),
    ),
    PilotTask(
        "P16",
        "multi_continue",
        "请分别查询 ORDER_404、ORDER_003、ORDER_888、ORDER_001 的库存，并汇总每笔结果。",
        ("ORDER_404", "ORDER_003", "ORDER_888", "ORDER_001"),
        ("ORDER_003", "ORDER_001"),
        ("ORDER_404", "ORDER_888"),
    ),
)


def get_pilot_task(task_id: str) -> PilotTask:
    """Return a pilot task by ID."""

    for task in PILOT_TASKS:
        if task.task_id == task_id:
            return task
    available = ", ".join(task.task_id for task in PILOT_TASKS)
    raise KeyError(f"Unknown pilot task {task_id!r}; choose one of: {available}")
