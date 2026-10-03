"""Protocol tests; these fixtures are not additional retail benchmark tasks."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from frozen_study import (  # noqa: E402
    analyze_simulation,
    budget_totals,
    call_events,
    digest,
    estimate_rmb,
    paired_bootstrap,
    read_json,
    read_jsonl,
    schedule,
    usage_cost,
    validate_manifest,
    write_json,
)
from run_frozen_study import reconcile, run_child, smoke_ready  # noqa: E402
from study_worker import BillingMonitor, StudyBudget  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures" / "event_fragments.json"


@pytest.mark.parametrize("fixture", read_json(FIXTURES), ids=lambda x: x["name"])
def test_event_fragments(fixture):
    measured = analyze_simulation(fixture["simulation"])
    for key, expected in fixture["expected"].items():
        assert measured[key] == expected, (fixture["name"], key)


def test_id_reuse_matches_local_response_window():
    simulation = {
        "messages": [
            {"role": "assistant", "tool_calls": [{"id": "a", "name": "lookup", "arguments": {}}]},
            {"role": "tool", "id": "a", "error": True},
            {"role": "assistant", "tool_calls": [{"id": "a", "name": "lookup", "arguments": {}}]},
            {"role": "tool", "id": "a", "error": False},
        ]
    }
    assert [e["status"] for e in call_events(simulation)] == ["error", "success"]


def test_seed_pairing_and_schedule_digest():
    m = {
        "base_seed": 300,
        "trials": 3,
        "task_ids": ["26", "27"],
        "smoke_tasks": ["0", "5"],
        "conditions": ["U0", "U2"],
    }
    rows = schedule(m, "formal")
    assert len(rows) == 12
    for i in range(0, len(rows), 2):
        assert rows[i].seed == rows[i + 1].seed
        assert rows[i].trial == rows[i + 1].trial
    assert [r.seed for r in rows[:6:2]] == [626729, 373753, 361454]
    assert digest([r.as_dict() for r in rows]) == digest([r.as_dict() for r in schedule(m, "formal")])


@pytest.mark.parametrize(
    "tokens,expected", [(128_000, 0.0256), (128_001, 0.1024008), (256_000, 0.2048), (256_001, 0.3072012)]
)
def test_tier_boundary(tokens, expected):
    assert estimate_rmb("openai/qwen3.5-flash-2026-02-23", tokens, 0) == pytest.approx(expected)


def test_missing_usage_and_unknown_model_are_not_free():
    assert usage_cost("openai/qwen3.8-max-2026-09-02", None) is None
    assert usage_cost("openai/qwen3.8-max-2026-09-02", {"prompt_tokens": 3}) is None
    with pytest.raises(ValueError):
        estimate_rmb("unknown", 3, 4)
    with pytest.raises(ValueError):
        estimate_rmb("qwen3.8-max-0902", 1_000_001, 4)


def test_interrupted_request_keeps_reservation():
    started = {"call_index": 1, "known_list_price_rmb": None, "budget_debit_rmb": 2}
    returned = {"call_index": 1, "known_list_price_rmb": 0.1, "budget_debit_rmb": 0.4}
    assert budget_totals([started])["usage_unknown_calls"] == 1
    assert budget_totals([started, returned])["budget_debit_rmb"] == 0.4


def test_budget_refuses_call_before_provider(tmp_path):
    monitor = BillingMonitor(tmp_path / "calls.jsonl", 0, {}, lambda: "user")
    monitor.original = lambda **kwargs: pytest.fail("provider must not be called")
    with pytest.raises(StudyBudget):
        monitor.completion(model="qwen3.8-max-0902", messages=[], max_tokens=512, num_retries=3)
    assert not monitor.path.exists()


def test_returned_calls_include_eval_and_conservative_retry_cost(tmp_path):
    usage = {"prompt_tokens": 100, "completion_tokens": 10}
    response = SimpleNamespace(usage=SimpleNamespace(model_dump=lambda: usage), choices=[], model="snapshot")
    monitor = BillingMonitor(tmp_path / "calls.jsonl", 100, {"attempt": 0}, lambda: "evaluator")
    monitor.original = lambda **kwargs: response
    assert monitor.completion(model="qwen3.8-max-0902", messages=[], max_tokens=512, num_retries=3) is response
    events = read_jsonl(monitor.path)
    assert events[-1]["role"] == "evaluator"
    assert events[-1]["budget_debit_rmb"] > events[-1]["known_list_price_rmb"]


def test_http_requests_capture_reasoning_usage_and_retry_attempts(tmp_path):
    import httpx

    counter = 0

    def handler(request):
        nonlocal counter
        counter += 1
        if counter == 1:
            return httpx.Response(429, json={"error": {"message": "fixture"}})
        return httpx.Response(200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 2332}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monitor = BillingMonitor(tmp_path / "calls.jsonl", 10, {}, lambda: "user")
    usage = {"prompt_tokens": 100, "completion_tokens": 2332}
    response = SimpleNamespace(usage=SimpleNamespace(model_dump=lambda: usage), choices=[], model="snapshot")

    def completion(**kwargs):
        payload = {
            "model": "qwen3.5-flash-2026-02-23",
            "messages": [],
            "max_tokens": 512,
            "max_completion_tokens": 8192,
        }
        client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload)
        client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload)
        return response

    module = SimpleNamespace(completion=completion)
    monitor.install(module)
    try:
        assert (
            module.completion(
                model="qwen3.5-flash-2026-02-23",
                messages=[],
                max_tokens=512,
                max_completion_tokens=8192,
                num_retries=3,
            )
            is response
        )
    finally:
        monitor.uninstall(module)
        client.close()
    requests = read_jsonl(monitor.request_path)
    assert budget_totals(requests)["calls"] == 2
    assert budget_totals(requests)["usage_unknown_calls"] == 1
    assert read_jsonl(monitor.path)[-1]["observed_http_requests"] == 2


def test_entity_cluster_bootstrap_keeps_related_tasks_together():
    rows = [
        {
            "task_id": task,
            "trial": trial,
            "condition": condition,
            "attempt": 0,
            "status": "valid",
            "metrics": {"official_final_reward": 1 if (task == "a") == (condition == "U2") else 0},
        }
        for task in ["a", "b"]
        for trial in range(3)
        for condition in ["U0", "U2"]
    ]
    result = paired_bootstrap(rows, clusters={"a": "one_user", "b": "one_user"})
    assert result["resampling_clusters"] == 1
    assert result["confidence_interval_95"] == [0, 0]


def test_bootstrap_keeps_task_trials_together_and_primary_only():
    rows = [
        {
            "task_id": task,
            "trial": trial,
            "condition": condition,
            "attempt": 0,
            "status": "valid",
            "metrics": {"official_final_reward": 1 if condition == "U2" else 0},
        }
        for task in ["a", "b"]
        for trial in range(3)
        for condition in ["U0", "U2"]
    ]
    rows.append({**rows[0], "attempt": 1, "metrics": {"official_final_reward": 1}})
    result = paired_bootstrap(rows)
    assert result["complete_tasks"] == 2
    assert result["confidence_interval_95"] == [1, 1]
    rows[0]["status"] = "infrastructure_error"
    result = paired_bootstrap(rows)
    assert result["complete_tasks"] == 1
    assert result["missing_pairs"] == [["a", 0]]
    with pytest.raises(ValueError):
        paired_bootstrap(rows + [rows[1]])


def test_immutable_write_and_crash_reconciliation(tmp_path):
    directory = tmp_path / "attempts" / "formal-t26-U0-r0-a00"
    job_path = directory / "job.json"
    write_json(job_path, {"slot": {"slot_id": "formal-t26-U0-r0", "phase": "formal"}, "attempt": 0})
    rows = reconcile(tmp_path, {"study_id": "fixture"})
    assert rows[0]["status"] == "interrupted"
    assert reconcile(tmp_path, {"study_id": "fixture"}) == rows
    with pytest.raises(FileExistsError):
        write_json(job_path, {}, exclusive=True)
    write_json(directory / "outcome.json", {})
    with pytest.raises(ValueError, match="changed"):
        reconcile(tmp_path, {"study_id": "fixture"})


def test_deadline_preserves_partial_and_stops_child(tmp_path):
    child_file = tmp_path / "fixture.py"
    partial = tmp_path / "partial.json"
    child_file.write_text(
        "import json,signal,time\n"
        f"partial={str(partial)!r}\n"
        "def stop(sig,frame):\n"
        " open(partial,'w').write(json.dumps({'messages':[{'role':'user','content':'partial'}]}))\n"
        " raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "time.sleep(20)\n"
    )
    code = run_child(
        [sys.executable, str(child_file)],
        cwd=tmp_path,
        env=os.environ.copy(),
        log=tmp_path / "worker.log",
        timeout=0.5,
    )
    assert code == 124
    assert read_json(partial)["messages"][0]["content"] == "partial"


def test_frozen_manifest_validation():
    m = {
        "schema_version": 1,
        "analyzer_version": "retail-events-v1",
        "conditions": ["U0", "U2"],
        "trials": 3,
        "task_ids": ["26"],
        "smoke_tasks": ["0", "5"],
        "base_seed": 300,
        "observed_local_task_ids": ["0"],
        "model_args": {"num_retries": 3},
        "deadline_seconds": 600,
    }
    m["schedule_sha256"] = digest([r.as_dict() for r in schedule(m, "formal")])
    validate_manifest(m)
    m["schedule_sha256"] = "changed"
    with pytest.raises(ValueError):
        validate_manifest(m)


def test_smoke_gate_keeps_failed_request_reservations_but_rejects_missing_success_usage(tmp_path):
    from frozen_study import append_json

    m = {"base_seed": 300, "trials": 3, "task_ids": ["26"], "smoke_tasks": ["0", "5"], "conditions": ["U0", "U2"]}
    ledger = []
    for slot in schedule(m, "smoke"):
        directory = tmp_path / slot.key
        directory.mkdir()
        returned = {
            "call_index": 1,
            "state": "http_returned",
            "http_status": 200,
            "known_list_price_rmb": 0.1,
            "budget_debit_rmb": 0.1,
            "precall_reservation_rmb": 0.5,
        }
        failed = {
            "call_index": 2,
            "state": "http_error",
            "known_list_price_rmb": None,
            "budget_debit_rmb": 0.5,
            "precall_reservation_rmb": 0.5,
        }
        for event in [returned, failed]:
            append_json(directory / "requests.jsonl", event)
        ledger.append(
            {
                **slot.as_dict(),
                "attempt": 0,
                "status": "valid",
                "outcome_path": slot.key + "/outcome.json",
                "billing": budget_totals([returned, failed]),
            }
        )
    assert smoke_ready(tmp_path, ledger, m)
    missing = {**returned, "known_list_price_rmb": None, "budget_debit_rmb": 0.5}
    append_json(directory / "requests.jsonl", missing)
    ledger[-1]["billing"] = budget_totals([missing, failed])
    assert not smoke_ready(tmp_path, ledger, m)
