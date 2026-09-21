"""Deterministic benchmark cases for the local ReliableToolAgent harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScriptedAction:
    """One scripted model action in a deterministic trajectory."""

    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class FaultRule:
    """A deterministic fault keyed by task, tool, arguments, and call number."""

    task_id: str
    tool_name: str
    arguments: dict[str, Any]
    error_type: str
    message: str
    fail_on_calls: tuple[int, ...] = (1,)


@dataclass(frozen=True)
class TaskCase:
    """Task, scripted trajectory, expected answer, and evaluation contract."""

    task_id: str
    query: str
    actions: tuple[ScriptedAction, ...]
    expected: dict[str, Any]
    fault_rules: tuple[FaultRule, ...] = ()


TASK_CASES: tuple[TaskCase, ...] = (
    TaskCase(
        task_id="T01",
        query="查询 ORDER_001 中商品的当前库存。",
        actions=(
            ScriptedAction("get_order_detail", {"order_id": "ORDER_001"}),
            ScriptedAction("get_inventory", {"sku": "SKU_A"}),
            ScriptedAction("final_answer", {"answer": {"order_id": "ORDER_001", "sku": "SKU_A", "stock": 7}}),
        ),
        expected={
            "final_output": {"order_id": "ORDER_001", "sku": "SKU_A", "stock": 7},
            "tool_calls": 2,
            "errors": 0,
            "recovered": False,
        },
    ),
    TaskCase(
        task_id="T02",
        query="查询 ORDER_002 中商品的当前库存。",
        actions=(
            ScriptedAction("get_order_detail", {"order_id": "ORDER_002"}),
            ScriptedAction("get_inventory", {"sku": "SKU_B"}),
            ScriptedAction("get_inventory", {"sku": "SKU_B"}),
            ScriptedAction("final_answer", {"answer": {"order_id": "ORDER_002", "sku": "SKU_B", "stock": 12}}),
        ),
        expected={
            "final_output": {"order_id": "ORDER_002", "sku": "SKU_B", "stock": 12},
            "tool_calls": 3,
            "errors": 1,
            "recovered": True,
        },
        fault_rules=(
            FaultRule(
                task_id="T02",
                tool_name="get_inventory",
                arguments={"sku": "SKU_B"},
                error_type="TemporaryUnavailable",
                message="TemporaryUnavailable: retry this read-only call once",
            ),
        ),
    ),
    TaskCase(
        task_id="T03",
        query="查询 ORDER_003 中商品的当前库存。",
        actions=(
            ScriptedAction("get_inventory", {"sku": "ORDER_003"}),
            ScriptedAction("get_order_detail", {"order_id": "ORDER_003"}),
            ScriptedAction("get_inventory", {"sku": "SKU_C"}),
            ScriptedAction("final_answer", {"answer": {"order_id": "ORDER_003", "sku": "SKU_C", "stock": 3}}),
        ),
        expected={
            "final_output": {"order_id": "ORDER_003", "sku": "SKU_C", "stock": 3},
            "tool_calls": 3,
            "errors": 1,
            "recovered": True,
        },
    ),
    TaskCase(
        task_id="T04",
        query="查询 ORDER_999 中商品的当前库存。",
        actions=(
            ScriptedAction("get_order_detail", {"order_id": "ORDER_999"}),
            ScriptedAction("final_answer", {"answer": {"status": "order_not_found"}}),
        ),
        expected={
            "final_output": {"status": "order_not_found"},
            "tool_calls": 1,
            "errors": 1,
            "recovered": False,
        },
    ),
    TaskCase(
        task_id="T05",
        query="验证相同的失败库存调用是否会被完整记录。",
        actions=(
            ScriptedAction("get_inventory", {"sku": "ORDER_001"}),
            ScriptedAction("get_inventory", {"sku": "ORDER_001"}),
            ScriptedAction("final_answer", {"answer": {"status": "duplicate_failure_observed"}}),
        ),
        expected={
            "final_output": {"status": "duplicate_failure_observed"},
            "tool_calls": 2,
            "errors": 2,
            "recovered": False,
            "same_failed_call_count": 2,
        },
    ),
)


def get_case(task_id: str) -> TaskCase:
    """Return a case by ID with a useful error for unknown IDs."""

    for case in TASK_CASES:
        if case.task_id == task_id:
            return case
    available = ", ".join(case.task_id for case in TASK_CASES)
    raise KeyError(f"Unknown task_id {task_id!r}; choose one of: {available}")
