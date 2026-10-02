"""Unit tests for pilot task definitions and observational metrics."""

import json

from local_demo.pilot import evaluate_pilot
from local_demo.pilot_tasks import PILOT_TASKS, get_pilot_task


class FakeResult:
    def __init__(self, output, run):
        self.output = output
        self._run = run

    def dict(self):
        return self._run


def _step(number, name, arguments, *, error=None, observation=None):
    call = {"id": f"call_{number}", "type": "function", "function": {"name": name, "arguments": arguments}}
    return {
        "step_number": number,
        "model_output_message": {"tool_calls": [call]},
        "tool_calls": [] if error else [call],
        "error": error,
        "observations": observation,
    }


def test_pilot_catalog_has_two_categories_and_sixteen_tasks():
    assert len(PILOT_TASKS) == 16
    assert sum(task.category == "single_terminal" for task in PILOT_TASKS) == 8
    assert sum(task.category == "multi_continue" for task in PILOT_TASKS) == 8
    assert len({task.task_id for task in PILOT_TASKS}) == 16


def test_single_terminal_pilot_detects_extra_call_after_order_not_found():
    task = get_pilot_task("P01")
    error = {"type": "AgentToolExecutionError", "message": "OrderNotFound: ORDER_999"}
    run = {
        "state": "success",
        "steps": [
            _step(1, "get_order_detail", {"order_id": "ORDER_999"}, error=error),
            _step(
                2,
                "get_inventory",
                {"sku": "ORDER_999"},
                error={"type": "AgentToolExecutionError", "message": "UnknownSKU"},
            ),
            _step(3, "final_answer", {"answer": "ORDER_999 不存在"}, observation="ORDER_999 不存在"),
        ],
    }

    report = evaluate_pilot(task, FakeResult("ORDER_999 不存在", run))

    assert report["metrics"]["business_success"]
    assert report["metrics"]["terminal_violation"]
    assert report["metrics"]["task_success"]
    assert report["metrics"]["unrecoverable_observation"]
    assert report["metrics"]["unnecessary_tool_call_count"] == 1
    assert not report["metrics"]["premature_termination"]


def test_multi_continue_pilot_records_success_after_missing_order():
    task = get_pilot_task("P09")
    error = {"type": "AgentToolExecutionError", "message": "OrderNotFound: ORDER_999"}
    run = {
        "state": "success",
        "steps": [
            _step(1, "get_order_detail", {"order_id": "ORDER_999"}, error=error),
            _step(
                2,
                "get_order_detail",
                {"order_id": "ORDER_001"},
                observation=json.dumps({"order_id": "ORDER_001", "sku": "SKU_A"}),
            ),
            _step(3, "get_inventory", {"sku": "SKU_A"}, observation=json.dumps({"sku": "SKU_A", "stock": 7})),
            _step(
                4,
                "final_answer",
                {"answer": "ORDER_999 不存在，ORDER_001 库存为 7"},
                observation="ORDER_999 不存在，ORDER_001 库存为 7",
            ),
        ],
    }

    report = evaluate_pilot(task, FakeResult("ORDER_999 不存在，ORDER_001 库存为 7", run))

    assert report["metrics"]["business_success"]
    assert report["metrics"]["continued_after_error"]
    assert report["metrics"]["existing_orders_completed"] == ["ORDER_001"]
    assert report["metrics"]["unrecoverable_observation"]
    assert report["metrics"]["unnecessary_tool_call_count"] == 0
    assert not report["metrics"]["premature_termination"]


def test_pilot_unnecessary_calls_union_terminal_and_duplicate_failures():
    task = get_pilot_task("P01")
    not_found = {"type": "AgentToolExecutionError", "message": "OrderNotFound: ORDER_999"}
    unknown_sku = {"type": "AgentToolExecutionError", "message": "UnknownSKU: ORDER_999"}
    run = {
        "state": "success",
        "steps": [
            _step(1, "get_order_detail", {"order_id": "ORDER_999"}, error=not_found),
            _step(2, "get_inventory", {"sku": "ORDER_999"}, error=unknown_sku),
            _step(3, "get_inventory", {"sku": "ORDER_999"}, error=unknown_sku),
            _step(4, "final_answer", {"answer": "ORDER_999 不存在"}, observation="ORDER_999 不存在"),
        ],
    }

    report = evaluate_pilot(task, FakeResult("ORDER_999 不存在", run))

    assert report["metrics"]["terminal_violation_count"] == 2
    assert report["metrics"]["duplicate_failed_calls"] == 1
    assert report["metrics"]["unnecessary_tool_call_count"] == 2


def _call_result(index, tool_name, arguments, *, status="success", result=None, error=None, error_type=None):
    return {
        "call_index": index,
        "tool_name": tool_name,
        "arguments": arguments,
        "status": status,
        "result": json.dumps(result, ensure_ascii=False) if result is not None else None,
        "error": error,
        "error_type": error_type,
    }


def _result_from_steps(output, steps):
    return FakeResult(output, {"state": "success", "steps": steps})


def test_single_target_accepts_correct_not_found_wording():
    task = get_pilot_task("P01")
    result = _result_from_steps(
        "ORDER_999 无法找到。",
        [
            {
                "step_number": 1,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_order_detail",
                        {"order_id": "ORDER_999"},
                        status="error",
                        error="OrderNotFound: ORDER_999",
                        error_type="OrderNotFound",
                    )
                ],
            }
        ],
    )

    report = evaluate_pilot(task, result)

    assert report["metrics"]["business_success"]
    assert not report["metrics"]["terminal_violation"]


def test_single_target_same_step_extra_call_is_terminal_violation():
    task = get_pilot_task("P01")
    result = _result_from_steps(
        "ORDER_999 不存在。",
        [
            {
                "step_number": 1,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_order_detail",
                        {"order_id": "ORDER_999"},
                        status="error",
                        error="OrderNotFound: ORDER_999",
                        error_type="OrderNotFound",
                    ),
                    _call_result(
                        2,
                        "get_inventory",
                        {"sku": "ORDER_999"},
                        status="error",
                        error="UnknownSKU: ORDER_999",
                        error_type="UnknownSKU",
                    ),
                ],
            }
        ],
    )

    report = evaluate_pilot(task, result)

    assert report["metrics"]["business_success"]
    assert report["metrics"]["terminal_violation"]
    assert report["metrics"]["unnecessary_tool_call_count"] == 1


def test_multi_target_requires_every_target_in_final_answer():
    task = get_pilot_task("P09")
    result = _result_from_steps(
        "ORDER_001 的库存为 7。",
        [
            {
                "step_number": 1,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_order_detail",
                        {"order_id": "ORDER_001"},
                        result={"order_id": "ORDER_001", "sku": "SKU_A"},
                    ),
                    _call_result(
                        2,
                        "get_order_detail",
                        {"order_id": "ORDER_999"},
                        status="error",
                        error="OrderNotFound: ORDER_999",
                        error_type="OrderNotFound",
                    ),
                ],
            },
            {
                "step_number": 2,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_inventory",
                        {"sku": "SKU_A"},
                        result={"sku": "SKU_A", "stock": 7},
                    )
                ],
            },
        ],
    )

    report = evaluate_pilot(task, result)

    assert not report["metrics"]["business_success"]
    assert report["metrics"]["premature_termination"]
    assert report["metrics"]["continued_after_error"]


def test_multi_target_rejects_wrong_inventory_value():
    task = get_pilot_task("P09")
    result = _result_from_steps(
        "ORDER_001 的库存为 999；ORDER_999 不存在。",
        [
            {
                "step_number": 1,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_order_detail",
                        {"order_id": "ORDER_001"},
                        result={"order_id": "ORDER_001", "sku": "SKU_A"},
                    ),
                    _call_result(
                        2,
                        "get_order_detail",
                        {"order_id": "ORDER_999"},
                        status="error",
                        error="OrderNotFound: ORDER_999",
                        error_type="OrderNotFound",
                    ),
                ],
            },
            {
                "step_number": 2,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_inventory",
                        {"sku": "SKU_A"},
                        result={"sku": "SKU_A", "stock": 999},
                    )
                ],
            },
        ],
    )

    report = evaluate_pilot(task, result)

    assert not report["metrics"]["business_success"]
    assert report["metrics"]["existing_orders_completed"] == []


def test_multi_target_same_step_parallel_success_counts_as_continuation():
    task = get_pilot_task("P09")
    result = _result_from_steps(
        "ORDER_001 的库存为 7；ORDER_999 不存在。",
        [
            {
                "step_number": 1,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_order_detail",
                        {"order_id": "ORDER_999"},
                        status="error",
                        error="OrderNotFound: ORDER_999",
                        error_type="OrderNotFound",
                    ),
                    _call_result(
                        2,
                        "get_order_detail",
                        {"order_id": "ORDER_001"},
                        result={"order_id": "ORDER_001", "sku": "SKU_A"},
                    ),
                ],
            },
            {
                "step_number": 2,
                "tool_call_results": [
                    _call_result(
                        1,
                        "get_inventory",
                        {"sku": "SKU_A"},
                        result={"sku": "SKU_A", "stock": 7},
                    )
                ],
            },
        ],
    )

    report = evaluate_pilot(task, result)

    assert report["metrics"]["business_success"]
    assert report["metrics"]["continued_after_error"]
    assert report["metrics"]["unnecessary_tool_call_count"] == 0
