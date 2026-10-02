"""Round-trip tests for reliability-related ToolCallingAgent settings."""

from unittest.mock import MagicMock, patch

from smolagents import Tool, ToolCallingAgent


class EchoTool(Tool):
    name = "echo"
    description = "Return the supplied value."
    inputs = {"value": {"type": "string", "description": "Value."}}
    output_type = "string"

    def forward(self, value: str) -> str:
        return value


def test_tool_calling_agent_reliability_settings_round_trip():
    model = MagicMock()
    model.model_id = "serialization-test-model"
    model.to_dict.return_value = {"model_id": model.model_id}
    agent = ToolCallingAgent(
        tools=[EchoTool()],
        model=model,
        max_steps=7,
        max_tool_threads=3,
        structured_error_feedback=False,
        retry_framing=False,
        duplicate_guard=True,
        stream_outputs=False,
        verbosity_level=0,
    )

    serialized = agent.to_dict()

    assert serialized["structured_error_feedback"] is False
    assert serialized["retry_framing"] is False
    assert serialized["duplicate_guard"] is True
    assert serialized["max_tool_threads"] == 3

    model_class = MagicMock()
    restored_model = MagicMock()
    model_class.from_dict.return_value = restored_model
    with patch.dict("smolagents.models.MODEL_REGISTRY", {"MagicMock": model_class}):
        restored = ToolCallingAgent.from_dict(serialized)

    assert restored.structured_error_feedback is False
    assert restored.retry_framing is False
    assert restored.duplicate_guard is True
    assert restored.max_tool_threads == 3
    assert restored.max_steps == 7


def test_legacy_agent_dict_keeps_default_reliability_settings():
    model_class = MagicMock()
    model_class.from_dict.return_value = MagicMock()
    legacy = {
        "class": "ToolCallingAgent",
        "model": {"class": "MagicMock", "data": {}},
        "tools": [],
        "managed_agents": [],
    }
    with patch.dict("smolagents.models.MODEL_REGISTRY", {"MagicMock": model_class}):
        restored = ToolCallingAgent.from_dict(legacy)

    assert restored.structured_error_feedback is True
    assert restored.retry_framing is True
    assert restored.duplicate_guard is False
