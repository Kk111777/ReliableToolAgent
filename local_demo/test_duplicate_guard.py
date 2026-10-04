"""Tests for Duplicate Failure Guard V1 only."""

from threading import Barrier
from unittest.mock import MagicMock

import pytest

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


def _process_step(agent: ToolCallingAgent, *calls: ChatMessageToolCall) -> ActionStep:
    step = ActionStep(step_number=1, timing=Timing(start_time=0.0))
    message = ChatMessage(role=MessageRole.ASSISTANT, content="", tool_calls=list(calls))
    try:
        list(agent.process_tool_calls(message, step))
    except AgentError:
        pass
    return step


def _process(agent: ToolCallingAgent, *calls: ChatMessageToolCall) -> list[dict]:
    return _trajectory({"steps": [_process_step(agent, *calls).dict()]})


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


def test_changed_state_alias_allows_the_new_effective_target():
    tool = CountingOrderDetailTool()
    agent = _agent(tool)
    arguments = {"order_id": "lookup"}
    agent.state["lookup"] = "ORDER_999"
    first = _process_step(agent, _call("call_1", "get_order_detail", arguments))

    agent.state["lookup"] = "ORDER_001"
    second = _process_step(agent, _call("call_2", "get_order_detail", arguments))

    assert first.tool_call_results[0]["status"] == "error"
    assert second.tool_call_results[0]["status"] == "success"
    assert second.tool_call_results[0]["arguments"] == {"order_id": "lookup"}
    assert second.tool_call_results[0]["resolved_arguments"] == {"order_id": "ORDER_001"}
    assert second.tool_call_results[0]["normalized_arguments"] == '{"order_id":"ORDER_001"}'
    assert tool.calls == 2
    assert arguments == {"order_id": "lookup"}


@pytest.mark.parametrize("second_reference", ["lookup", "another_lookup", "ORDER_999"])
def test_same_effective_failed_target_is_blocked_for_any_reference(second_reference):
    tool = CountingOrderDetailTool()
    agent = _agent(tool)
    agent.state.update(lookup="ORDER_999", another_lookup="ORDER_999")
    _process_step(agent, _call("call_1", "get_order_detail", {"order_id": "lookup"}))

    step = _process_step(agent, _call("call_2", "get_order_detail", {"order_id": second_reference}))

    record = step.tool_call_results[0]
    assert record["status"] == "blocked"
    assert record["arguments"] == {"order_id": second_reference}
    assert record["resolved_arguments"] == {"order_id": "ORDER_999"}
    assert record["normalized_arguments"] == '{"order_id":"ORDER_999"}'
    assert tool.calls == 1


@pytest.mark.parametrize("direct", [False, True])
def test_state_alias_chain_is_resolved_only_once(direct):
    tool = CountingOrderDetailTool()
    agent = _agent(tool)
    agent.state.update(lookup="ORDER_001", ORDER_001="ORDER_999")

    if direct:
        agent.execute_tool_call("get_order_detail", {"order_id": "lookup"})
    else:
        step = _process_step(agent, _call("call_1", "get_order_detail", {"order_id": "lookup"}))
        assert step.tool_call_results[0]["status"] == "success"
        assert step.tool_call_results[0]["resolved_arguments"] == {"order_id": "ORDER_001"}
    assert tool.calls == 1


def test_guard_history_and_execution_use_the_same_snapshot_if_state_changes(monkeypatch):
    tool = CountingOrderDetailTool()
    agent = _agent(tool)
    agent.state["lookup"] = "ORDER_999"
    resolve = agent._substitute_state_variables
    resolutions = []

    def resolve_then_change_state(arguments):
        snapshot = resolve(arguments)
        resolutions.append(snapshot)
        agent.state["lookup"] = "ORDER_001"
        return snapshot

    monkeypatch.setattr(agent, "_substitute_state_variables", resolve_then_change_state)
    step = _process_step(agent, _call("call_1", "get_order_detail", {"order_id": "lookup"}))

    record = step.tool_call_results[0]
    assert resolutions == [{"order_id": "ORDER_999"}]
    assert record["status"] == "error"
    assert record["resolved_arguments"] == {"order_id": "ORDER_999"}
    assert "ORDER_999" in record["error"]
    assert next(iter(agent._failure_records.values())).normalized_arguments == '{"order_id":"ORDER_999"}'
    assert tool.calls == 1


def test_retryable_failure_through_state_alias_is_not_blocked():
    tool = InventoryTool(transient_failure=True)
    agent = _agent(tool)
    agent.state["inventory"] = "SKU_A"

    first = _process(agent, _call("call_1", "get_inventory", {"sku": "inventory"}))
    second = _process(agent, _call("call_2", "get_inventory", {"sku": "inventory"}))

    assert first[0]["retryable_same_call"] is True
    assert second[0]["status"] == "success"
    assert tool.attempts == 2


def test_public_execute_override_delegates_with_the_original_intent_and_one_resolution():
    class InstrumentedAgent(ToolCallingAgent):
        def execute_tool_call(self, tool_name, arguments):
            self.seen.append((tool_name, dict(arguments)))
            return super().execute_tool_call(tool_name, arguments)

    tool = CountingOrderDetailTool()
    agent = InstrumentedAgent(tools=[tool], model=MagicMock(), verbosity_level=0, duplicate_guard=True)
    agent.seen = []
    agent.state.update(lookup="ORDER_001", ORDER_001="ORDER_999")

    step = _process_step(agent, _call("call_1", "get_order_detail", {"order_id": "lookup"}))

    assert agent.seen == [("get_order_detail", {"order_id": "lookup"})]
    assert step.tool_call_results[0]["status"] == "success"
    assert step.tool_call_results[0]["resolved_arguments"] == {"order_id": "ORDER_001"}
    # The dispatch context was reset: a later direct call resolves its own arguments.
    assert "ORDER_002" in agent.execute_tool_call("get_order_detail", {"order_id": "ORDER_002"})
    assert tool.calls == 2


def test_tool_can_make_an_independent_direct_call_on_the_same_agent():
    class NestedLookupTool(Tool):
        name = "nested_lookup"
        description = "Delegates one lookup through the public direct-call API."
        inputs = {"order_id": {"type": "string", "description": "Order identifier."}}
        output_type = "string"

        def forward(self, order_id: str) -> str:
            return self.agent.execute_tool_call("get_order_detail", {"order_id": order_id})

    detail_tool = CountingOrderDetailTool()
    nested_tool = NestedLookupTool()
    agent = _agent(detail_tool, nested_tool)
    nested_tool.agent = agent
    agent.state["lookup"] = "ORDER_001"

    step = _process_step(agent, _call("call_1", "nested_lookup", {"order_id": "lookup"}))

    assert step.tool_call_results[0]["status"] == "success"
    assert "ORDER_001" in step.tool_call_results[0]["result"]
    assert detail_tool.calls == 1


@pytest.mark.parametrize("rewrite_tool", [False, True])
def test_override_rewrite_is_rejected_before_execution_and_does_not_poison_guard(rewrite_tool):
    class RewritingAgent(ToolCallingAgent):
        def execute_tool_call(self, tool_name, arguments):
            if self.rewrite:
                if rewrite_tool:
                    tool_name = "final_answer"
                else:
                    arguments = {"order_id": "ORDER_002"}
            return super().execute_tool_call(tool_name, arguments)

    tool = CountingOrderDetailTool()
    agent = RewritingAgent(tools=[tool], model=MagicMock(), verbosity_level=0, duplicate_guard=True)
    agent.rewrite = True
    first = _process_step(agent, _call("call_1", "get_order_detail", {"order_id": "ORDER_001"}))

    assert first.tool_call_results[0]["status"] == "error"
    assert "Unsupported execute_tool_call override rewrite" in first.tool_call_results[0]["error"]
    assert first.tool_call_results[0]["retryable_same_call"] is None
    assert all(record.retryable_same_call is not False for record in agent._failure_records.values())
    assert tool.calls == 0

    agent.rewrite = False
    # An exceptional dispatch must also reset its context before a direct call.
    assert "ORDER_002" in agent.execute_tool_call("get_order_detail", {"order_id": "ORDER_002"})
    second = _process_step(agent, _call("call_2", "get_order_detail", {"order_id": "ORDER_001"}))
    assert second.tool_call_results[0]["status"] == "success"
    assert tool.calls == 2


def test_mutable_arguments_are_detached_in_raw_and_resolved_logs():
    class MutatingTool(Tool):
        name = "mutate_items"
        description = "Mutates a list to exercise invocation-time logging."
        inputs = {"items": {"type": "array", "description": "Items to mutate."}}
        output_type = "string"

        def forward(self, items: list) -> str:
            items.append("tool mutation")
            return "done"

    agent = _agent(MutatingTool())
    direct_items = ["direct"]
    state_items = ["state"]
    agent.state["saved_items"] = state_items
    direct = _process_step(agent, _call("call_1", "mutate_items", {"items": direct_items}))
    alias = _process_step(agent, _call("call_2", "mutate_items", {"items": "saved_items"}))

    assert direct_items == ["direct", "tool mutation"]
    assert state_items == ["state", "tool mutation"]
    assert direct.tool_call_results[0]["arguments"] == {"items": ["direct"]}
    assert direct.tool_call_results[0]["resolved_arguments"] == {"items": ["direct"]}
    assert alias.tool_call_results[0]["arguments"] == {"items": "saved_items"}
    assert alias.tool_call_results[0]["resolved_arguments"] == {"items": ["state"]}
    assert alias.tool_call_results[0]["normalized_arguments"] == '{"items":["state"]}'


def test_hook_cannot_mutate_the_resolved_state_target_before_delegating():
    class ListTool(Tool):
        name = "list_target"
        description = "Records a list target."
        inputs = {"items": {"type": "array", "description": "Items."}}
        output_type = "string"

        def forward(self, items: list) -> str:
            self.called = True
            return "executed"

    class RewritingAgent(ToolCallingAgent):
        def execute_tool_call(self, tool_name, arguments):
            self.state["lookup"].append("changed after matching")
            return super().execute_tool_call(tool_name, arguments)

    tool = ListTool()
    tool.called = False
    agent = RewritingAgent(tools=[tool], model=MagicMock(), verbosity_level=0, duplicate_guard=True)
    agent.state["lookup"] = ["original"]
    step = _process_step(agent, _call("call_1", "list_target", {"items": "lookup"}))
    assert step.tool_call_results[0]["status"] == "error"
    assert step.tool_call_results[0]["retryable_same_call"] is None
    assert step.tool_call_results[0]["resolved_arguments"] == {"items": ["original"]}
    assert tool.called is False


def test_parallel_calls_before_failure_history_are_not_in_flight_deduplicated():
    barrier = Barrier(2)

    class ConcurrentFailureTool(PairFailureTool):
        def forward(self, a: int, b: int) -> str:
            barrier.wait(timeout=5)
            return super().forward(a, b)

    tool = ConcurrentFailureTool()
    agent = _agent(tool)
    agent.max_tool_threads = 2
    agent.state.update(first=1, second=1)

    records = _process(
        agent,
        _call("call_1", "pair_failure", {"a": "first", "b": 2}),
        _call("call_2", "pair_failure", {"a": "second", "b": 2}),
    )
    assert [record["status"] for record in records] == ["error", "error"]
    assert tool.calls == 2

    later = _process(agent, _call("call_3", "pair_failure", {"a": 1, "b": 2}))
    assert later[0]["status"] == "blocked"
    assert tool.calls == 2


class RepeatThenFinalModel(Model):
    model_id = "duplicate-guard-isolation-model"

    def __init__(self, order_reference="ORDER_999"):
        super().__init__(model_id=self.model_id)
        self.contexts = []
        self.order_reference = order_reference

    def generate(self, messages, **kwargs):
        self.contexts.append(messages)
        if len(messages) < 4:
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[_call("first", "get_order_detail", {"order_id": self.order_reference})],
            )
        if len(messages) < 6:
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[_call("repeat", "get_order_detail", {"order_id": self.order_reference})],
            )
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[_call("answer", "final_answer", {"answer": "ORDER_999 不存在"})],
        )


@pytest.mark.parametrize("order_reference", ["ORDER_999", "lookup"])
def test_failure_records_are_isolated_between_agent_runs(order_reference):
    tool = CountingOrderDetailTool()
    model = RepeatThenFinalModel(order_reference)
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
    agent.state["lookup"] = "ORDER_999"

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
