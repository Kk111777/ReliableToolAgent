"""Pilot execution and real HTTP-monitor contracts; no credentials or network."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import dotenv
import httpx
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_engineering_pilot as pilot  # noqa: E402
from engineering_worker import ResponseAdapters, install_adapters  # noqa: E402
from frozen_study import (  # noqa: E402
    append_json,
    budget_totals,
    digest,
    file_sha,
    read_json,
    read_jsonl,
    schedule,
    write_json,
)
from run_budgeted_study import CostInventory  # noqa: E402
from study_worker import BillingMonitor, StudyBudget, StudyDeadline  # noqa: E402


def pilot_files(tmp_path, monkeypatch):
    root, base = tmp_path / "root", tmp_path / "studies"
    root.mkdir()
    output, history = base / "pilot", base / "history"
    manifest = {
        "schema_version": 1,
        "analyzer_version": "retail-events-v1",
        "study_id": "engineering-v2-test",
        "engineering_version": "engineering-v2",
        "task_ids": ["0", "5"],
        "smoke_tasks": [],
        "trials": 1,
        "base_seed": 300,
        "conditions": ["U0", "U2"],
        "deadline_seconds": 600,
        "evaluator_parse_retries": 2,
        "user_empty_retries": 1,
        "budget_cap_rmb": 1,
        "source_sha256": {},
        "benchmark_commit": "fixture",
    }
    manifest["schedule_sha256"] = digest([s.as_dict() for s in schedule(manifest, "formal")])
    write_json(output / "manifest.json", manifest)
    write_json(history / "manifest.json", {"study_id": "historical"})
    directory = history / "attempts/formal-t26-U0-r0-a00"
    write_json(
        directory / "job.json",
        {"manifest": {"study_id": "historical"}, "slot": {"slot_id": "formal-t26-U0-r0"}, "attempt": 0},
    )
    append_json(directory / "requests.jsonl", {"call_index": 1, "known_list_price_rmb": 0.1, "budget_debit_rmb": 0.15})
    write_json(directory / "simulation.json", {"messages": []})
    write_json(
        directory / "outcome.json",
        {"billing": budget_totals(read_jsonl(directory / "requests.jsonl")), "status": "valid"},
    )
    append_json(
        history / "attempts.jsonl",
        {
            "slot_id": "formal-t26-U0-r0",
            "attempt": 0,
            "status": "valid",
            "outcome_path": "attempts/formal-t26-U0-r0-a00/outcome.json",
            "outcome_sha256": file_sha(directory / "outcome.json"),
            "artifact_sha256": {
                name: file_sha(directory / name) for name in ("job.json", "requests.jsonl", "simulation.json")
            },
        },
    )
    inventory = CostInventory((history, output))
    records = inventory.records()
    write_json(base / "balance.json", {"records": records, "snapshot": {"inventory_sha256": digest(records)}})
    policy = {
        "combined_cap_rmb": 1.05,
        "discount_factor": 0.5,
        "discount_source": "explicit_user_confirmation",
        "cost_basis": "list_price_with_unknown_usage_reserve",
        "accounting_outputs": ["history", "pilot"],
        "required_existing_outputs": ["history", "pilot"],
        "paid_execution_state": "approved_with_verified_global_guard",
        "frozen_manifest_sha256": digest(manifest),
        "balance_baseline": {
            "available_rmb": 1,
            "evidence_path": "balance.json",
            "evidence_sha256": file_sha(base / "balance.json"),
        },
    }
    write_json(base / "policy.json", policy)
    monkeypatch.setattr(pilot, "verify_sources", lambda manifest, root: None)
    monkeypatch.setattr(pilot, "run_child", lambda *a, **k: pytest.fail("worker must not start in this contract"))
    return root, output, base / "policy.json", directory


def test_dry_run_does_not_read_credentials_reconcile_or_launch_worker(tmp_path, monkeypatch):
    root, output, policy, _ = pilot_files(tmp_path, monkeypatch)
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *a, **k: pytest.fail("dry-run must not read credentials"))
    monkeypatch.setattr(pilot, "reconcile", lambda *a, **k: pytest.fail("dry-run must not mutate historical evidence"))
    result = pilot.execute(root, output, policy, run=False)
    assert result["state"] == "dry_run"
    assert result["remaining_slots"] == 4
    assert result["new_model_calls"] == 0
    assert not (output / "attempts").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"study_id": "retail-holdout-v1c-20261003"},
        {"engineering_version": "frozen-v1"},
        {"task_ids": ["0", "5", "39"]},
        {"trials": 2},
        {"conditions": ["U0", "U2", "U3"]},
        {"base_seed": 301},
        {"schedule_sha256": "changed"},
    ],
)
def test_old_study_expansion_or_changed_schedule_is_rejected_before_execution(tmp_path, monkeypatch, change):
    _, output, _, _ = pilot_files(tmp_path, monkeypatch)
    manifest = {**read_json(output / "manifest.json"), **change}
    with pytest.raises(ValueError):
        pilot.validate_pilot(manifest)


def test_policy_cannot_authorize_more_than_reported_global_balance(tmp_path, monkeypatch):
    root, output, policy, _ = pilot_files(tmp_path, monkeypatch)
    write_json(policy, {**read_json(policy), "combined_cap_rmb": 2})
    with pytest.raises(ValueError, match="reported balance"):
        pilot.execute(root, output, policy, run=False)


def test_historical_unknown_reserve_exhausts_allowance_before_any_worker(tmp_path, monkeypatch):
    root, output, policy, _ = pilot_files(tmp_path, monkeypatch)
    write_json(policy, {**read_json(policy), "combined_cap_rmb": 0.075})
    monkeypatch.setattr(
        dotenv,
        "dotenv_values",
        lambda *a, **k: {
            "OPENAI_API_KEY": "fixture-not-a-real-key",
            "OPENAI_API_BASE": "https://dashscope.aliyuncs.com/fixture",
        },
    )
    result = pilot.execute(root, output, policy, run=True)
    assert result["state"] == "budget_stop_before_attempt"
    assert not (output / "attempts").exists()


@pytest.mark.parametrize("evidence", ["balance", "historical_cost", "historical_trajectory"])
def test_changed_balance_or_old_evidence_is_rejected_without_provider(tmp_path, monkeypatch, evidence):
    root, output, policy, directory = pilot_files(tmp_path, monkeypatch)
    if evidence == "balance":
        write_json(policy.parent / "balance.json", {"records": [], "snapshot": {"inventory_sha256": "changed"}})
    elif evidence == "historical_cost":
        write_json(directory / "outcome.json", {"billing": {}})
    else:
        write_json(directory / "simulation.json", {"messages": [{"role": "user", "content": "changed fixture"}]})
    monkeypatch.setattr(
        dotenv, "dotenv_values", lambda *a, **k: pytest.fail("changed evidence must stop before credentials")
    )
    with pytest.raises(ValueError):
        pilot.execute(root, output, policy, run=False)


class HTTPResponse(SimpleNamespace):
    def model_copy(self, *, update):
        return HTTPResponse(**{**vars(self), **update})


def scripted_http_monitor(tmp_path, *, budget, cancel=False):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if cancel:
            raise StudyDeadline()
        content = None if len(calls) == 1 else "complete"
        return httpx.Response(
            200,
            json={
                "model": "fixture-snapshot",
                "usage": {"prompt_tokens": 30, "completion_tokens": 100},
                "choices": [
                    {"finish_reason": "length" if content is None else "stop", "message": {"content": content}}
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def completion(**kwargs):
        response = client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=kwargs)
        raw = response.json()
        return HTTPResponse(
            content=raw["choices"][0]["message"]["content"],
            tool_calls=None,
            raw_data=raw,
            usage=SimpleNamespace(model_dump=lambda: raw["usage"]),
            choices=[SimpleNamespace(finish_reason=raw["choices"][0]["finish_reason"])],
            model=raw["model"],
        )

    module = SimpleNamespace(completion=completion)
    monitor = BillingMonitor(tmp_path / "calls.jsonl", budget, {"attempt": 0}, lambda: "user")
    monitor.install(module)
    wrapped = ResponseAdapters(tmp_path, []).user(lambda **kwargs: module.completion(**kwargs))
    kwargs = {
        "model": "qwen3.5-flash-2026-02-23",
        "messages": [],
        "max_tokens": 512,
        "max_completion_tokens": 100,
        "num_retries": 0,
    }
    return client, monitor, module, wrapped, kwargs, calls


def test_empty_response_retry_passes_through_http_billing_and_preserves_two_charges(tmp_path):
    client, monitor, module, wrapped, kwargs, calls = scripted_http_monitor(tmp_path, budget=0.01)
    try:
        assert wrapped(**kwargs).content == "complete"
    finally:
        monitor.uninstall(module)
        client.close()
    assert len(calls) == 2
    assert calls[0] == calls[1]
    totals = budget_totals(read_jsonl(tmp_path / "requests.jsonl"))
    assert totals["calls"] == 2
    assert totals["usage_unknown_calls"] == 0
    assert totals["known_list_price_rmb"] == pytest.approx(0.000412)
    assert [r["accepted"] for r in read_jsonl(tmp_path / "response_adapters.jsonl")] == [False, True]


def test_second_response_reservation_fails_before_provider_when_balance_is_insufficient(tmp_path):
    client, monitor, module, wrapped, kwargs, calls = scripted_http_monitor(tmp_path, budget=0.0005)
    try:
        with pytest.raises(StudyBudget):
            wrapped(**kwargs)
    finally:
        monitor.uninstall(module)
        client.close()
    assert len(calls) == 1
    totals = budget_totals(read_jsonl(tmp_path / "requests.jsonl"))
    assert totals["calls"] == 1
    assert totals["known_list_price_rmb"] == pytest.approx(0.000206)
    assert len(read_jsonl(tmp_path / "response_adapters.jsonl")) == 1


def test_http_cancellation_is_not_retried_and_unknown_request_reserve_is_retained(tmp_path):
    client, monitor, module, wrapped, kwargs, calls = scripted_http_monitor(tmp_path, budget=0.01, cancel=True)
    try:
        with pytest.raises(StudyDeadline):
            wrapped(**kwargs)
    finally:
        monitor.uninstall(module)
        client.close()
    assert len(calls) == 1
    totals = budget_totals(read_jsonl(tmp_path / "requests.jsonl"))
    assert totals["calls"] == 1 and totals["usage_unknown_calls"] == 1
    assert totals["budget_debit_rmb"] > 0
    assert not (tmp_path / "response_adapters.jsonl").exists()


def test_external_exception_subclass_name_cannot_reach_legacy_outcome_writer(tmp_path):
    provider_type = type("PrivateProviderToken", (ValueError,), {})

    def fail(*args, **kwargs):
        raise provider_type("private provider message")

    user, evaluator = SimpleNamespace(generate=fail), SimpleNamespace(generate=fail)
    simulation = SimpleNamespace(run_simulation=fail)
    with (
        pytest.raises(RuntimeError) as caught,
        install_adapters(
            ResponseAdapters(tmp_path, []),
            user_module=user,
            evaluator_module=evaluator,
            simulation_module=simulation,
            trusted_root=tmp_path,
        ),
    ):
        simulation.run_simulation()
    assert type(caught.value) is RuntimeError
    diagnostic = read_jsonl(tmp_path / "diagnostics.jsonl")[0]
    assert diagnostic["exception_type"] == "ValueError"
    assert "PrivateProviderToken" not in json.dumps(diagnostic)
    assert "private provider message" not in json.dumps(diagnostic)
