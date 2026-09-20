import pytest

from local_demo.run import InventoryTool, OrderTool, run_case


@pytest.mark.parametrize("fault,attempts", [(False, 1), (True, 2)])
def test_real_agent_loop_and_trajectory(fault, attempts):
    report = run_case(fault=fault)
    assert report["passed"]
    assert report["inventory_attempts"] == attempts
    assert report["scope"] == "integration_smoke_only"
    assert report["run"]["state"] == "success"


def test_invalid_entity_is_not_silently_repaired():
    with pytest.raises(ValueError, match="Unknown SKU"):
        InventoryTool()(sku="ORDER_001")
    with pytest.raises(ValueError, match="Unknown order"):
        OrderTool()(order_id="missing")


def test_transient_failure_has_a_visible_first_attempt():
    tool = InventoryTool(transient_failure=True)
    with pytest.raises(TimeoutError):
        tool(sku="SKU_A")
    assert '"available": 7' in tool(sku="SKU_A")
    assert tool.attempts == 2
