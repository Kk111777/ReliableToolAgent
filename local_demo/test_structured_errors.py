"""Tests for Structured Error Feedback V1 without adding recovery policy."""

import json
from unittest.mock import MagicMock

import pytest

from local_demo.run import (
    InventoryTool,
    OrderDetailTool,
    PermissionDenied,
    run_case,
)
from smolagents import Model, Tool, ToolCallingAgent
from smolagents.agents import AgentToolCallError, AgentToolExecutionError
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole
from smolagents.utils import StructuredErrorType, build_structured_error, register_structured_error_exception


class PermissionTool(Tool):
    name = "read_restricted_resource"
    description = "Read a restricted resource."
    inputs = {"resource": {"type": "string", "description": "Resource identifier."}}
    output_type = "string"

    def forward(self, resource: str) -> str:
        raise PermissionDenied(f"Permission denied for {resource}")


def _agent(*tools: Tool, structured_error_feedback: bool = True) -> ToolCallingAgent:
    return ToolCallingAgent(
        tools=list(tools),
        model=MagicMock(),
        verbosity_level=0,
        structured_error_feedback=structured_error_feedback,
    )


def _structured_error(exc: AgentToolCallError | AgentToolExecutionError) -> dict:
    assert exc.structured_error is not None
    return exc.structured_error.dict()


def test_invalid_argument_is_structured_without_retry_policy():
    with pytest.raises(AgentToolCallError) as caught:
        _agent(InventoryTool()).execute_tool_call("get_inventory", {"sku": 123})

    error = _structured_error(caught.value)
    assert error["error_type"] == "INVALID_ARGUMENT"
    assert error["retryable_same_call"] is False
    assert error["scope"] == "current_call"


def test_internal_value_error_is_not_overmapped_to_invalid_argument():
    class InternalFailureTool(Tool):
        name = "internal_failure"
        description = "A fixture for an execution-time internal failure."
        inputs = {"value": {"type": "string", "description": "Input value."}}
        output_type = "string"

        def forward(self, value: str) -> str:
            raise ValueError(f"internal calculation failed for {value}")

    with pytest.raises(AgentToolExecutionError) as caught:
        _agent(InternalFailureTool()).execute_tool_call("internal_failure", {"value": "x"})

    assert caught.value.structured_error is None
    assert build_structured_error("internal_failure", {"value": "x"}, ValueError("internal")) is None
    assert (
        build_structured_error(
            "internal_failure", {"value": "x"}, ValueError("invalid"), argument_validation=True
        ).error_type.value
        == "INVALID_ARGUMENT"
    )


def test_domain_exception_can_use_explicit_registry_without_name_matching():
    class DomainUnavailable(Exception):
        pass

    register_structured_error_exception(DomainUnavailable, StructuredErrorType.TEMPORARY_UNAVAILABLE)
    error = build_structured_error("domain_tool", {}, DomainUnavailable("later"))

    assert error is not None
    assert error.error_type is StructuredErrorType.TEMPORARY_UNAVAILABLE


def test_raw_condition_keeps_raw_observation_without_changing_tool_behavior():
    with pytest.raises(AgentToolExecutionError) as caught:
        _agent(OrderDetailTool(), structured_error_feedback=False).execute_tool_call(
            "get_order_detail", {"order_id": "ORDER_999"}
        )

    assert caught.value.structured_error is None
    assert "OrderNotFound" in caught.value.to_observation()


def test_unknown_entity_is_structured():
    with pytest.raises(AgentToolExecutionError) as caught:
        _agent(InventoryTool()).execute_tool_call("get_inventory", {"sku": "ORDER_001"})

    error = _structured_error(caught.value)
    assert error["error_type"] == "UNKNOWN_ENTITY"
    assert error["retryable_same_call"] is False
    assert error["scope"] == "current_call"
    assert error["details"] == {"sku": "ORDER_001"}


def test_temporary_unavailable_is_feedback_only_and_not_retried():
    tool = InventoryTool(transient_failure=True)
    with pytest.raises(AgentToolExecutionError) as caught:
        _agent(tool).execute_tool_call("get_inventory", {"sku": "SKU_A"})

    error = _structured_error(caught.value)
    assert error["error_type"] == "TEMPORARY_UNAVAILABLE"
    assert error["retryable_same_call"] is True
    assert error["scope"] == "current_call"
    assert tool.attempts == 1


def test_target_not_found_is_structured():
    with pytest.raises(AgentToolExecutionError) as caught:
        _agent(OrderDetailTool()).execute_tool_call("get_order_detail", {"order_id": "ORDER_999"})

    error = _structured_error(caught.value)
    assert error["error_type"] == "TARGET_NOT_FOUND"
    assert error["retryable_same_call"] is False
    assert error["scope"] == "current_target"
    assert error["details"] == {"order_id": "ORDER_999"}


def test_permission_denied_is_structured():
    with pytest.raises(AgentToolExecutionError) as caught:
        _agent(PermissionTool()).execute_tool_call("read_restricted_resource", {"resource": "R1"})

    error = _structured_error(caught.value)
    assert error["error_type"] == "PERMISSION_DENIED"
    assert error["retryable_same_call"] is False
    assert error["scope"] == "tool_capability"


def test_success_path_is_unchanged():
    result = _agent(InventoryTool()).execute_tool_call("get_inventory", {"sku": "SKU_A"})

    assert json.loads(result) == {"sku": "SKU_A", "stock": 7}


def test_structured_error_is_in_next_model_context_without_runtime_recovery():
    class ErrorThenFinalModel(Model):
        model_id = "structured-error-test-model"

        def __init__(self):
            super().__init__(model_id=self.model_id)
            self.calls = 0
            self.second_context = None

        def generate(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content="",
                    tool_calls=[
                        ChatMessageToolCall(
                            id="call_1",
                            type="function",
                            function=ChatMessageToolCallFunction(
                                name="get_order_detail", arguments={"order_id": "ORDER_999"}
                            ),
                        )
                    ],
                )
            self.second_context = messages
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[
                    ChatMessageToolCall(
                        id="call_2",
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name="final_answer", arguments={"answer": "ORDER_999 不存在"}
                        ),
                    )
                ],
            )

    model = ErrorThenFinalModel()
    agent = ToolCallingAgent(tools=[OrderDetailTool()], model=model, max_steps=3, verbosity_level=0)
    result = agent.run("查询 ORDER_999", return_full_result=True)

    context = str(model.second_context)
    assert result.output == "ORDER_999 不存在"
    assert '"error_type": "TARGET_NOT_FOUND"' in context
    assert '"retryable_same_call": false' in context
    assert '"scope": "current_target"' in context
    assert '"tool": "get_order_detail"' in context
    assert model.calls == 2


def test_artifact_keeps_structured_error_fields_and_scripted_multi_target_continues():
    not_found = run_case("T04")
    record = not_found["trajectory"][0]
    assert record["error_type"] == "TARGET_NOT_FOUND"
    assert record["retryable_same_call"] is False
    assert record["scope"] == "current_target"
    assert record["message"] == "The requested target does not exist."
    assert record["details"] == {"order_id": "ORDER_999"}

    repaired = run_case("T03")
    assert [record["tool_name"] for record in repaired["trajectory"]] == [
        "get_inventory",
        "get_order_detail",
        "get_inventory",
        "final_answer",
    ]
