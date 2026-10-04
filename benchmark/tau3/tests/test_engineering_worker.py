"""Response recovery contracts; all generation is scripted, never paid."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from engineering_diagnostics import EvaluatorPayloadError  # noqa: E402
from engineering_worker import EmptyUserOutput, ResponseAdapters, install_adapters  # noqa: E402
from frozen_study import read_jsonl  # noqa: E402
from study_worker import StudyBudget, StudyDeadline  # noqa: E402


class Response(SimpleNamespace):
    def model_copy(self, *, update):
        return Response(**{**vars(self), **update})


def response(content, calls=None):
    return Response(content=content, tool_calls=calls, raw_data={"choices": [{"finish_reason": "length"}]})


def generator(responses, seen):
    def generate(*args, **kwargs):
        seen.append(copy.deepcopy(kwargs))
        result = responses[len(seen) - 1]
        if isinstance(result, BaseException):
            raise result
        return result

    return generate


def test_empty_user_is_retried_once_with_identical_history_and_preserved_events(tmp_path):
    seen = []
    complete = response("hello")
    wrapped = ResponseAdapters(tmp_path, []).user(generator([response(None), complete], seen))
    history = [{"role": "user", "content": "request"}]
    assert wrapped(messages=history, max_completion_tokens=8192) is complete
    assert seen[0] == seen[1]
    assert len(history) == 1
    events = read_jsonl(tmp_path / "response_adapters.jsonl")
    assert [r["accepted"] for r in events] == [False, True]
    assert "hello" not in json.dumps(events)


def test_repeated_empty_output_remains_invalid(tmp_path):
    seen = []
    wrapped = ResponseAdapters(tmp_path, []).user(generator([response(""), response(" ")], seen))
    with pytest.raises(EmptyUserOutput):
        wrapped()
    assert len(seen) == 2
    assert len(read_jsonl(tmp_path / "response_adapters.jsonl")) == 2


@pytest.mark.parametrize("exception", [StudyBudget(), StudyDeadline(), ConnectionError("secret")])
def test_user_never_retries_cancellation_or_request_errors(tmp_path, exception):
    seen = []
    with pytest.raises(type(exception)):
        ResponseAdapters(tmp_path, []).user(generator([exception], seen))()
    assert len(seen) == 1


def test_user_tool_call_not_retried(tmp_path):
    seen = []
    tool_response = response(None, calls=[{"name": "fixture"}])
    assert ResponseAdapters(tmp_path, []).user(generator([tool_response], seen))() is tool_response
    assert len(seen) == 1


def test_evaluator_unwraps_without_changing_boolean_reward_or_raw_response(tmp_path):
    payload = {"results": [{"expectedOutcome": "x", "metExpectation": False, "reasoning": "no"}]}
    raw = response("```json\n" + json.dumps(payload) + "\n```")
    seen = []
    result = ResponseAdapters(tmp_path, ["x"]).evaluator(generator([raw], seen))()
    assert json.loads(result.content) == payload
    assert result.raw_data is raw.raw_data
    assert raw.content.startswith("```")
    assert len(seen) == 1


def test_evaluator_missing_assertion_cannot_become_vacuous_success(tmp_path):
    seen = []
    wrapped = ResponseAdapters(tmp_path, ["x"]).evaluator(generator([response('{"results":[]}')] * 3, seen))
    with pytest.raises(EvaluatorPayloadError):
        wrapped()
    assert len(seen) == 3


def test_evaluator_recovers_only_after_a_new_valid_response(tmp_path):
    seen = []
    valid = '{"results":[{"expectedOutcome":"x","metExpectation":true,"reasoning":"ok"}]}'
    wrapped = ResponseAdapters(tmp_path, ["x"]).evaluator(generator([response("bad"), response(valid)], seen))
    assert wrapped().content == valid
    assert len(seen) == 2


def test_scoped_patches_restore_after_budget_cancellation_and_record_safe_location(tmp_path):
    def cancel(*args, **kwargs):
        raise StudyBudget()

    user, evaluator = SimpleNamespace(generate=cancel), SimpleNamespace(generate=cancel)
    simulation = SimpleNamespace(run_simulation=cancel)
    with (
        pytest.raises(StudyBudget),
        install_adapters(
            ResponseAdapters(tmp_path, []),
            user_module=user,
            evaluator_module=evaluator,
            simulation_module=simulation,
            trusted_root=tmp_path,
        ),
    ):
        simulation.run_simulation()
    assert user.generate is evaluator.generate is simulation.run_simulation is cancel
    diagnostic = read_jsonl(tmp_path / "diagnostics.jsonl")[0]
    assert diagnostic["stage"] == "simulation"
    assert diagnostic["exception_type"] == "budget"
    assert all(r == {"source": "external"} for r in diagnostic["frames"])


def test_custom_exception_name_cannot_reach_frozen_outcome_writer(tmp_path):
    private_type = type("PrivateTokenInClassName", (ValueError,), {})

    def fail():
        raise private_type("private payload")

    user, evaluator = SimpleNamespace(generate=fail), SimpleNamespace(generate=fail)
    simulation = SimpleNamespace(run_simulation=fail)
    with (
        pytest.raises(RuntimeError) as captured,
        install_adapters(
            ResponseAdapters(tmp_path, []),
            user_module=user,
            evaluator_module=evaluator,
            simulation_module=simulation,
            trusted_root=tmp_path,
        ),
    ):
        simulation.run_simulation()
    assert type(captured.value) is RuntimeError
    serialized = (tmp_path / "diagnostics.jsonl").read_text()
    assert "PrivateToken" not in serialized and "private payload" not in serialized
