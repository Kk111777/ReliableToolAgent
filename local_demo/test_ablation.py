"""Unit checks for the two independent ablation variables."""

import json
from unittest.mock import MagicMock

from local_demo.ablation import ABLATION_ROOT, CONDITIONS, MODEL_CONFIG, build_schedule
from local_demo.run import ARTIFACTS, InventoryTool, OrderDetailTool
from smolagents import ToolCallingAgent
from smolagents.memory import ActionStep
from smolagents.monitoring import Timing
from smolagents.utils import AgentToolExecutionError as UtilsAgentToolExecutionError


def _agent(condition: str) -> ToolCallingAgent:
    config = CONDITIONS[condition]
    model = MagicMock()
    model.model_id = "fixed-test-model"
    model.to_dict.return_value = {"model_id": "fixed-test-model", "temperature": 0.0}
    return ToolCallingAgent(
        tools=[OrderDetailTool(), InventoryTool()],
        model=model,
        verbosity_level=0,
        structured_error_feedback=config["error_mode"] == "structured",
        retry_framing=config["retry_framing"],
    )


def test_matrix_has_only_two_independent_variables():
    assert CONDITIONS == {
        "E0_raw_retry": {"error_mode": "raw", "retry_framing": True},
        "E1_structured_retry": {"error_mode": "structured", "retry_framing": True},
        "E2_raw_no_retry": {"error_mode": "raw", "retry_framing": False},
        "E3_structured_no_retry": {"error_mode": "structured", "retry_framing": False},
    }


def test_interleaved_schedule_is_deterministic_and_block_balanced():
    task_ids = ["P01", "P02"]
    conditions = list(CONDITIONS)
    first = build_schedule(task_ids, conditions, 2, seed=17)
    second = build_schedule(task_ids, conditions, 2, seed=17)

    assert first == second
    for offset in range(0, len(first), len(conditions)):
        block = first[offset : offset + len(conditions)]
        assert len({(repeat, task) for repeat, task, _ in block}) == 1
        assert {condition for _, _, condition in block} == set(conditions)


def test_retry_framing_on_and_off_have_no_replacement_instruction():
    raw_error = UtilsAgentToolExecutionError("raw tool failure", MagicMock())
    on = ActionStep(step_number=1, timing=Timing(start_time=0.0), error=raw_error, retry_framing=True)
    off = ActionStep(step_number=1, timing=Timing(start_time=0.0), error=raw_error, retry_framing=False)
    on_text = on.to_messages()[0].content[0]["text"]
    off_text = off.to_messages()[0].content[0]["text"]

    assert "Error:\nraw tool failure" in on_text
    assert "Now let's retry" in on_text
    assert off_text == "Error:\nraw tool failure"
    assert "retry" not in off_text.lower()
    assert "different approach" not in off_text.lower()


def test_four_conditions_keep_prompt_and_tool_schema_independent_of_flags():
    agents = [_agent(condition) for condition in CONDITIONS]
    assert len({agent.system_prompt for agent in agents}) == 1
    schemas = [
        sorted(
            (tool.name, tool.description, json.dumps(tool.inputs, sort_keys=True), tool.output_type)
            for tool in agent.tools.values()
        )
        for agent in agents
    ]
    assert all(schema == schemas[0] for schema in schemas)
    assert all(agent.model.to_dict() == agents[0].model.to_dict() for agent in agents)
    assert MODEL_CONFIG["temperature"] == 0.0
    assert MODEL_CONFIG["max_tokens"] == 512


def test_success_path_is_identical_across_conditions():
    results = [
        json.loads(_agent(condition).execute_tool_call("get_inventory", {"sku": "SKU_A"})) for condition in CONDITIONS
    ]
    assert results == [{"sku": "SKU_A", "stock": 7}] * 4


def test_ablation_artifacts_are_isolated_from_previous_pilot_artifacts():
    assert ABLATION_ROOT.name == "qwen35-flash-ablation"
    assert ABLATION_ROOT.parent == ARTIFACTS
    assert ABLATION_ROOT != ARTIFACTS / "api-pilot-summary.json"
