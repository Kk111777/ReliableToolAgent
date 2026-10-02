"""Tests for independent per-tool-call logging."""

from unittest.mock import MagicMock

from local_demo.run import InventoryTool, OrderDetailTool, _trajectory
from smolagents import ToolCallingAgent
from smolagents.memory import ActionStep
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole
from smolagents.monitoring import Timing
from smolagents.utils import AgentToolExecutionError


def _call(call_id: str, tool_name: str, arguments: dict[str, str]) -> ChatMessageToolCall:
    return ChatMessageToolCall(
        id=call_id,
        type="function",
        function=ChatMessageToolCallFunction(name=tool_name, arguments=arguments),
    )


def _process(*calls: ChatMessageToolCall) -> dict:
    agent = ToolCallingAgent(
        tools=[OrderDetailTool(), InventoryTool()],
        model=MagicMock(),
        max_tool_threads=2,
        verbosity_level=0,
    )
    step = ActionStep(step_number=2, timing=Timing(start_time=0.0))
    message = ChatMessage(role=MessageRole.ASSISTANT, content="", tool_calls=list(calls))
    try:
        list(agent.process_tool_calls(message, step))
    except AgentToolExecutionError:
        pass
    return step.dict()


def _records(*calls: ChatMessageToolCall) -> list[dict]:
    step = _process(*calls)
    return _trajectory({"steps": [step]})


def test_single_success_has_independent_success_record():
    records = _records(_call("call_1", "get_inventory", {"sku": "SKU_A"}))

    assert records == [
        {
            "step_index": 2,
            "call_index": 1,
            "tool": "get_inventory",
            "tool_name": "get_inventory",
            "arguments": {"sku": "SKU_A"},
            "normalized_arguments": '{"sku":"SKU_A"}',
            "status": "success",
            "result": {"sku": "SKU_A", "stock": 7},
            "error": None,
            "error_type": None,
            "retryable_same_call": None,
            "scope": None,
            "message": None,
            "details": None,
            "block_reason": None,
            "previous_error_type": None,
        }
    ]


def test_single_failure_has_independent_error_record():
    records = _records(_call("call_1", "get_order_detail", {"order_id": "ORDER_999"}))

    assert records[0]["status"] == "error"
    assert records[0]["error_type"] == "TARGET_NOT_FOUND"
    assert records[0]["result"] is None
    assert "ORDER_999" in records[0]["error"]["message"]


def test_parallel_successes_keep_call_order_and_results_separate():
    records = _records(
        _call("call_1", "get_order_detail", {"order_id": "ORDER_001"}),
        _call("call_2", "get_order_detail", {"order_id": "ORDER_002"}),
    )

    assert [(record["call_index"], record["status"]) for record in records] == [(1, "success"), (2, "success")]
    assert [record["result"]["sku"] for record in records] == ["SKU_A", "SKU_B"]


def test_parallel_success_and_failure_are_not_merged():
    records = _records(
        _call("call_1", "get_order_detail", {"order_id": "ORDER_001"}),
        _call("call_2", "get_order_detail", {"order_id": "ORDER_999"}),
    )

    assert [record["status"] for record in records] == ["success", "error"]
    assert records[0]["result"] == {"order_id": "ORDER_001", "sku": "SKU_A"}
    assert records[1]["result"] is None
    assert records[1]["error_type"] == "TARGET_NOT_FOUND"
