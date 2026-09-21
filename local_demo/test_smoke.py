"""Tests for the deterministic end-to-end experiment harness."""

import pytest

from local_demo.cases import TASK_CASES
from local_demo.run import InventoryTool, OrderTool, final_output_matches, run_case


@pytest.mark.parametrize("case", TASK_CASES, ids=lambda case: case.task_id)
def test_deterministic_case_runs_end_to_end(case):
    report = run_case(case.task_id)
    metrics = report["metrics"]

    assert metrics["task_success"]
    assert metrics["tool_calls"] == case.expected["tool_calls"]
    assert metrics["errors_encountered"] == case.expected["errors"]
    assert metrics["recovered"] == case.expected["recovered"]
    assert report["run"]["state"] == "success"


def test_t03_error_is_recorded_before_repair_call():
    report = run_case("T03")
    trajectory = report["trajectory"]

    assert [record["tool_name"] for record in trajectory] == [
        "get_inventory",
        "get_order_detail",
        "get_inventory",
        "final_answer",
    ]
    assert trajectory[0]["error_type"] == "UnknownSKU"
    assert trajectory[1]["error"] is None
    assert trajectory[2]["result"] == {"sku": "SKU_C", "stock": 3}


def test_t05_counts_identical_failed_calls_without_duplicate_guard():
    report = run_case("T05")
    failed = [record for record in report["trajectory"] if record["error"]]

    assert report["metrics"]["same_failed_call_count"] == 2
    assert len(failed) == 2
    assert failed[0]["tool_name"] == failed[1]["tool_name"] == "get_inventory"
    assert failed[0]["normalized_arguments"] == failed[1]["normalized_arguments"]
    assert failed[0]["error_type"] == failed[1]["error_type"] == "UnknownSKU"


def test_fault_schedule_is_deterministic():
    first = run_case("T02")
    second = run_case("T02")

    assert first["metrics"] == second["metrics"]
    assert first["trajectory"] == second["trajectory"]


def test_evaluator_accepts_equivalent_natural_language_answer():
    assert final_output_matches(
        {"order_id": "ORDER_001", "sku": "SKU_A", "stock": 7},
        "ORDER_001 中的商品 SKU_A 当前库存为 7。",
    )
    assert not final_output_matches(
        {"order_id": "ORDER_001", "sku": "SKU_A", "stock": 7},
        "ORDER_001 中的商品 SKU_A 当前库存为 0。",
    )


def test_evaluator_can_use_verified_observation_for_omitted_intermediate_field():
    trajectory = [
        {
            "error": None,
            "result": {"order_id": "ORDER_001", "sku": "SKU_A"},
        },
        {
            "error": None,
            "result": {"sku": "SKU_A", "stock": 7},
        },
    ]
    assert final_output_matches(
        {"order_id": "ORDER_001", "sku": "SKU_A", "stock": 7},
        "ORDER_001 中商品的当前库存为 7。",
        trajectory,
    )


def test_legacy_tool_validation_still_reports_invalid_inputs():
    with pytest.raises(ValueError, match="Unknown SKU"):
        InventoryTool()(sku="ORDER_001")
    with pytest.raises(ValueError, match="Unknown order"):
        OrderTool()(order_id="missing")
