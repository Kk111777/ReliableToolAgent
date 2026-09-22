"""Tests for Duplicate Failure Guard V1 only."""

from unittest.mock import MagicMock

from local_demo.run import InventoryTool, OrderDetailTool, _trajectory
from smolagents import Model, Tool, ToolCallingAgent
from smolagents.memory import ActionStep
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole
from smolagents.monitoring import Timing
from smolagents.utils import AgentError


class CountingOrderDetailTool(OrderDetailTool):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def forward(self, order_id: str) -> str:
        self.calls += 1
        return super().forward(order_id)


class PairFailureTool(Tool):
    name = "pair_failure"
    description = "A fixture that always returns a non-retryable failure."
    inputs = {
        "a": {"type": "integer", "description": "First value."},
        "b": {"type": "integer", "description": "Second value."},
    }
    output_type = "string"

    class DomainFailure(Exception):
        structured_error_type = "TARGET_NOT_FOUND"

    def __init__(self):
        super().__init__()
        self.calls = 0

    def forward(self, a: int, b: int) -> str:
        self.calls += 1
        raise self.DomainFailure(f"pair unavailable: {a}, {b}")


def _call(call_id: str, tool_name: str, arguments: dict) -> ChatMessageToolCall:
    return ChatMessageToolCall(
        id=call_id,
        type="function",
        function=ChatMessageToolCallFunction(name=tool_name, arguments=arguments),
    )


def _agent(*tools: Tool, guard: bool = True) -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=list(tools),
        model=MagicMock(),
        max_tool_threads=1,
        verbosity_level=0,
        structured_error_feedback=True,
        retry_framing=False,
        duplicate_guard=guard,
    )


def _process(agent: ToolCallingAgent, *calls: ChatMessageToolCall) -> list[dict]:
    step = ActionStep(step_number=1, timing=Timing(start_time=0.0))
    message = ChatMessage(role=MessageRole.ASSISTANT, content="", tool_calls=list(calls))
    try:
        list(agent.process_tool_calls(message, step))
    except AgentError:
        pass
    return _trajectory({"steps": [step.dict()]})


def test_exact_duplicate_non_retryable_failure_is_blocked_without_second_execution():
    tool = CountingOrderDetailTool()
    agent = _agent(tool)

    first = _process(agent, _call("call_1", "get_order_detail", {"order_id": "ORDER_999"}))
    second = _process(agent, _call("call_2", "get_order_detail", {"order_id": "ORDER_999"}))

    assert first[0]["status"] == "error"
    assert second[0]["status"] == "blocked"
    assert second[0]["block_reason"] == "duplicate_non_retryable_failure"
    assert second[0]["previous_error_type"] == "TARGET_NOT_FOUND"
    assert tool.calls == 1


def test_different_arguments_are_not_blocked():
    tool = CountingOrderDetailTool()
    agent = _agent(tool)

    _process(agent, _call("call_1", "get_order_detail", {"order_id": "ORDER_999"}))
    records = _process(agent, _call("call_2", "get_order_detail", {"order_id": "ORDER_888"}))

    assert records[0]["status"] == "error"
    assert tool.calls == 2


def test_retryable_failure_is_not_blocked():
    tool = InventoryTool(transient_failure=True)
    agent = _agent(tool)

    first = _process(agent, _call("call_1", "get_inventory", {"sku": "SKU_A"}))
    second = _process(agent, _call("call_2", "get_inventory", {"sku": "SKU_A"}))

    assert first[0]["status"] == "error"
    assert first[0]["retryable_same_call"] is True
    assert second[0]["status"] == "success"
    assert tool.attempts == 2


def test_argument_key_order_is_normalized():
    tool = PairFailureTool()
    agent = _agent(tool)

    _process(agent, _call("call_1", "pair_failure", {"a": 1, "b": 2}))
    records = _process(agent, _call("call_2", "pair_failure", {"b": 2, "a": 1}))

    assert records[0]["status"] == "blocked"
    assert tool.calls == 1
    assert records[0]["normalized_arguments"] == '{"a":1,"b":2}'


def test_identifier_variants_are_not_semantic_duplicates():
    tool = CountingOrderDetailTool()
    agent = _agent(tool)

    _process(agent, _call("call_1", "get_order_detail", {"order_id": "ORDER_999"}))
    records = _process(agent, _call("call_2", "get_order_detail", {"order_id": "ORDER-999"}))

    assert records[0]["status"] == "error"
    assert tool.calls == 2


def test_successful_previous_call_is_not_blocked():
    tool = InventoryTool()
    agent = _agent(tool)

    first = _process(agent, _call("call_1", "get_inventory", {"sku": "SKU_A"}))
    second = _process(agent, _call("call_2", "get_inventory", {"sku": "SKU_A"}))

    assert first[0]["status"] == "success"
    assert second[0]["status"] == "success"
    assert tool.attempts == 2


class RepeatThenFinalModel(Model):
    model_id = "duplicate-guard-isolation-model"

    def __init__(self):
        super().__init__(model_id=self.model_id)
        self.contexts = []

    def generate(self, messages, **kwargs):
        self.contexts.append(messages)
        if len(messages) < 4:
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[_call("first", "get_order_detail", {"order_id": "ORDER_999"})],
            )
        if len(messages) < 6:
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[_call("repeat", "get_order_detail", {"order_id": "ORDER_999"})],
            )
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[_call("answer", "final_answer", {"answer": "ORDER_999 不存在"})],
        )


def test_failure_records_are_isolated_between_agent_runs():
    tool = CountingOrderDetailTool()
    model = RepeatThenFinalModel()
    agent = ToolCallingAgent(
        tools=[tool],
        model=model,
        max_steps=4,
        max_tool_threads=1,
        verbosity_level=0,
        structured_error_feedback=True,
        retry_framing=False,
        duplicate_guard=True,
    )

    first = agent.run("check order", return_full_result=True)
    second = agent.run("check order again", return_full_result=True)

    first_statuses = [
        record["status"] for step in first.dict()["steps"] for record in (step.get("tool_call_results") or [])
    ]
    second_statuses = [
        record["status"] for step in second.dict()["steps"] for record in (step.get("tool_call_results") or [])
    ]
    assert first_statuses[:2] == ["error", "blocked"]
    assert second_statuses[:2] == ["error", "blocked"]
    assert any("REPEATED_FAILED_CALL" in str(context) for context in model.contexts)
    assert tool.calls == 2
