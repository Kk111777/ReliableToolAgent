"""Total-cost contracts across preflight, reused smoke, retries and HTTP reserves."""

from __future__ import annotations

import json
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from frozen_study import append_json, budget_totals, digest, file_sha, read_json, read_jsonl, write_json  # noqa: E402
from run_budgeted_study import (  # noqa: E402
    BudgetPolicy,
    CostInventory,
    lock_outputs,
    remaining_slots,
    systemic_failures,
)
from study_worker import BillingMonitor, StudyBudget  # noqa: E402


def attempt(output, study="study", slot="smoke-t0-U0-r0", number=0, debit=1, known=1):
    directory = output / "attempts" / f"{slot}-a{number:02d}"
    directory.mkdir(parents=True)
    write_json(directory / "job.json", {"manifest": {"study_id": study}, "slot": {"slot_id": slot}, "attempt": number})
    append_json(
        directory / "requests.jsonl", {"call_index": 1, "budget_debit_rmb": debit, "known_list_price_rmb": known}
    )
    write_json(directory / "outcome.json", {"billing": budget_totals(read_jsonl(directory / "requests.jsonl"))})
    return directory


def test_preflight_reused_smoke_and_retry_count_once(tmp_path):
    preflight, smoke, primary = (tmp_path / p for p in ("preflight", "smoke", "primary"))
    attempt(preflight, "initial", "preflight", debit=0.1, known=None)
    original = attempt(smoke, "smoke-study", debit=0.2)
    shutil.copytree(original, primary / "attempts" / original.name)
    attempt(primary, slot="formal-t26-U0-r0", debit=0.3)
    attempt(primary, slot="formal-t26-U0-r0", number=1, debit=0.4)
    snapshot = CostInventory((preflight, smoke, primary)).snapshot()
    assert snapshot["unique_paid_attempts"] == 4
    assert snapshot["conservative_budget_debit_rmb"] == pytest.approx(1)
    assert snapshot["usage_unknown_calls"] == 1


def test_conflicting_reused_evidence_is_rejected(tmp_path):
    original = attempt(tmp_path / "one")
    clone = tmp_path / "two" / "attempts" / original.name
    shutil.copytree(original, clone)
    write_json(clone / "job.json", {**read_json(clone / "job.json"), "changed": True})
    with pytest.raises(ValueError, match="conflicting"):
        CostInventory((tmp_path / "one", tmp_path / "two")).snapshot()


def test_missing_outcome_and_changed_billing_are_rejected(tmp_path):
    directory = attempt(tmp_path)
    write_json(directory / "outcome.json", {"billing": {}})
    with pytest.raises(ValueError, match="billing disagrees"):
        CostInventory((tmp_path,)).snapshot()
    (directory / "outcome.json").unlink()
    with pytest.raises(ValueError, match="unfinished"):
        CostInventory((tmp_path,)).snapshot()


def test_torn_request_ledger_is_not_silently_dropped(tmp_path):
    directory = attempt(tmp_path)
    with (directory / "requests.jsonl").open("a") as handle:
        handle.write('{"call_index":')
    with pytest.raises(json.JSONDecodeError):
        CostInventory((tmp_path,)).snapshot()


def test_discount_keeps_list_price_evidence_and_bounds_worker_allowance(tmp_path):
    attempt(tmp_path, debit=14, known=12)
    policy = BudgetPolicy(15, "fixture", CostInventory((tmp_path,)), 0.5)
    snapshot = policy.snapshot()
    assert snapshot["known_list_price_rmb"] == 12
    assert snapshot["estimated_discounted_cost_rmb"] == pytest.approx(6)
    assert policy.remaining_rmb(snapshot) <= 8
    assert policy.allowance(snapshot) <= 16
    assert (snapshot["conservative_budget_debit_rmb"] + policy.allowance(snapshot)) * 0.5 <= 15


def policy_file(tmp_path, **changes):
    data = {
        "combined_cap_rmb": 15,
        "discount_factor": 0.5,
        "discount_source": "explicit_user_confirmation",
        "cost_basis": "list_price_with_unknown_usage_reserve",
        "accounting_outputs": ["prior"],
        "required_existing_outputs": ["prior"],
        "frozen_manifest_sha256": "fixture",
        "paid_execution_state": "approved_with_verified_global_guard",
        **changes,
    }
    write_json(tmp_path / "prior/manifest.json", {})
    write_json(tmp_path / "policy.json", data)
    return tmp_path / "policy.json"


@pytest.mark.parametrize(
    "changes",
    [
        {"combined_cap_rmb": -1},
        {"combined_cap_rmb": float("nan")},
        {"discount_factor": 0},
        {"discount_factor": 1.1},
        {"discount_source": "approximate_balance"},
        {"paid_execution_state": "not_verified"},
        {"accounting_outputs": ["../escape"]},
        {"accounting_outputs": []},
        {"required_existing_outputs": ["missing"]},
    ],
)
def test_policy_fails_closed(tmp_path, changes):
    with pytest.raises(ValueError):
        BudgetPolicy.load(policy_file(tmp_path, **changes), tmp_path)


def test_old_supervisor_and_second_runner_cannot_share_locks(tmp_path):
    output = tmp_path / "primary"
    output.mkdir()
    inventory = CostInventory((output,))
    with ExitStack() as owner:
        lock_outputs(owner, tmp_path, output, inventory)
        with ExitStack() as contender, pytest.raises(BlockingIOError):
            lock_outputs(contender, tmp_path, output, inventory)


def test_resume_preserves_original_order_and_skips_all_existing_attempts():
    manifest = {"base_seed": 300, "trials": 3, "task_ids": ["26"], "conditions": ["U0", "U2"]}
    rows = [{"slot_id": "formal-t26-U0-r0", "status": "valid"}, {"slot_id": "formal-t26-U2-r0", "status": "timeout"}]
    assert [s.key for s in remaining_slots(manifest, rows)] == [
        "formal-t26-U2-r1",
        "formal-t26-U0-r1",
        "formal-t26-U0-r2",
        "formal-t26-U2-r2",
    ]


def test_every_http_retry_is_checked_against_discounted_total(tmp_path):
    # Historical charges consume almost all of the global budget. The unchanged
    # worker gets the remaining list-price allowance, then blocks a second POST.
    policy = BudgetPolicy(1, "fixture", CostInventory(()), 0.5)
    snapshot = {"conservative_budget_debit_rmb": 1.65}
    monitor = BillingMonitor(tmp_path / "calls.jsonl", policy.allowance(snapshot), {}, lambda: "user")
    payload = {"model": "qwen3.8-max-2026-09-02", "messages": [], "max_completion_tokens": 8192}
    request = httpx.Request("POST", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload)
    first = monitor.start_http(request)
    monitor.fail_http(first, TimeoutError())
    with pytest.raises(StudyBudget):
        monitor.start_http(request)
    debit = budget_totals(read_jsonl(monitor.request_path))["budget_debit_rmb"]
    assert (snapshot["conservative_budget_debit_rmb"] + debit) * 0.5 <= policy.cap_rmb
    assert budget_totals(read_jsonl(monitor.request_path))["usage_unknown_calls"] == 1


def test_low_global_balance_blocks_completion_without_transport(tmp_path):
    policy = BudgetPolicy(15, "fixture", CostInventory(()), 0.5)
    monitor = BillingMonitor(
        tmp_path / "calls.jsonl", policy.allowance({"conservative_budget_debit_rmb": 29.9}), {}, lambda: "user"
    )
    monitor.original = lambda **kwargs: pytest.fail("provider must not be reached")
    with pytest.raises(StudyBudget):
        monitor.completion(
            model="qwen3.8-max-2026-09-02", messages=[], max_tokens=512, max_completion_tokens=8192, num_retries=3
        )
    assert not monitor.path.exists()


def test_finished_response_releases_only_measured_reservation(tmp_path):
    monitor = BillingMonitor(tmp_path / "calls.jsonl", 0.35, {}, lambda: "user")
    payload = {"model": "qwen3.8-max-2026-09-02", "messages": [], "max_completion_tokens": 8192}
    request = httpx.Request("POST", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload)
    first = monitor.start_http(request)
    monitor.finish_http(first, httpx.Response(200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 10}}))
    assert monitor.start_http(request) is not None


def balance_policy_file(tmp_path, **changes):
    attempt(tmp_path / "prior", debit=14, known=12)
    inventory = CostInventory((tmp_path / "prior",))
    evidence = tmp_path / "baseline.json"
    write_json(evidence, {"records": inventory.records(), "snapshot": inventory.snapshot()})
    return policy_file(
        tmp_path,
        combined_cap_rmb=18,
        balance_baseline={
            "available_rmb": 12,
            "evidence_path": "baseline.json",
            "evidence_sha256": file_sha(evidence),
        },
        **changes,
    )


def test_reported_remaining_balance_reserves_unknown_historical_usage(tmp_path):
    policy = BudgetPolicy.load(balance_policy_file(tmp_path), tmp_path)
    policy.verify_baseline()
    assert policy.remaining_rmb(policy.snapshot()) <= 11
    assert policy.allowance(policy.snapshot()) <= 22


def test_balance_anchor_survives_new_attempts_but_not_removed_history(tmp_path):
    policy = BudgetPolicy.load(balance_policy_file(tmp_path), tmp_path)
    attempt(tmp_path / "prior", slot="formal-t26-U0-r0", debit=0.2)
    policy.verify_baseline()
    shutil.rmtree(tmp_path / "prior/attempts/smoke-t0-U0-r0-a00")
    with pytest.raises(ValueError, match="disappeared"):
        policy.verify_baseline()


def test_balance_anchor_hash_cannot_be_changed(tmp_path):
    path = balance_policy_file(tmp_path)
    write_json(tmp_path / "baseline.json", {})
    with pytest.raises(ValueError, match="evidence changed"):
        BudgetPolicy.load(path, tmp_path)


def test_balance_cannot_be_used_to_expand_total_cap(tmp_path):
    path = balance_policy_file(tmp_path)
    data = read_json(path)
    data["combined_cap_rmb"] += 1
    write_json(path, data)
    with pytest.raises(ValueError, match="exceeds"):
        BudgetPolicy.load(path, tmp_path)


def test_retry_selector_preserves_scored_failures_budget_stops_and_previous_reruns():
    manifest = {"base_seed": 300, "trials": 3, "task_ids": ["26"], "conditions": ["U0", "U2"]}
    rows = [
        {"slot_id": "formal-t26-U0-r0", "status": "valid", "attempt": 0},
        {"slot_id": "formal-t26-U2-r0", "status": "timeout", "attempt": 0},
        {"slot_id": "formal-t26-U0-r1", "status": "budget_stop", "attempt": 0},
        {"slot_id": "formal-t26-U2-r1", "status": "infrastructure_error", "attempt": 0},
        {"slot_id": "formal-t26-U2-r1", "status": "infrastructure_error", "attempt": 1},
        {"slot_id": "formal-t26-U0-r2", "status": "interrupted", "attempt": 0},
    ]
    assert [s.key for s in remaining_slots(manifest, rows, retries=True)] == ["formal-t26-U2-r0", "formal-t26-U0-r2"]


def test_execute_dry_run_never_loads_credentials_or_writes_attempt_ledger(tmp_path, monkeypatch):
    import types

    import run_budgeted_study as runner

    manifest = read_json(Path(__file__).resolve().parents[1] / "studies/retail-holdout-v1/manifest.json")
    policy_path = policy_file(tmp_path, frozen_manifest_sha256=digest(manifest))
    output = tmp_path / "prior"
    write_json(output / "manifest.json", manifest)
    (output / "attempts.jsonl").write_text("")
    checks = []
    monkeypatch.setattr(runner, "verify_sources", lambda *args: checks.append("source_check"))
    monkeypatch.setattr(runner, "smoke_ready", lambda *args: True)
    monkeypatch.setitem(
        sys.modules,
        "dotenv",
        types.SimpleNamespace(dotenv_values=lambda *args: pytest.fail("dry-run must not read credentials")),
    )
    monkeypatch.setattr(runner, "run_child", lambda *args, **kwargs: pytest.fail("dry-run must not launch worker"))
    result = runner.execute(tmp_path, output, policy_path, run=False)
    assert checks == ["source_check"]
    assert result["state"] == "dry_run" and result["model_calls_started"] == 0
    assert (output / "attempts.jsonl").read_text() == ""
    assert not (output / "attempts").exists()


def test_operator_cancellations_do_not_form_three_provider_failures():
    rows = [
        {"status": "valid", "outcome_sha256": "previous"},
        {"status": "timeout", "error_class": "StudyDeadline", "outcome_sha256": "cancel1"},
        {"status": "timeout", "error_class": "StudyDeadline", "outcome_sha256": "cancel2"},
        {"status": "infrastructure_error", "outcome_sha256": "failed1"},
    ]
    cancellations = frozenset({"cancel1", "cancel2"})
    assert not systemic_failures(rows, cancellations)
    rows.extend({"status": "infrastructure_error", "outcome_sha256": f"failed{i}"} for i in (2, 3))
    assert systemic_failures(rows, cancellations)


@pytest.mark.parametrize(
    "row",
    [
        {"status": "valid", "error_class": None, "outcome_sha256": "wrong"},
        {"status": "timeout", "error_class": "SDKTimeout", "outcome_sha256": "wrong"},
    ],
)
def test_provider_failures_cannot_be_annotated_as_operator_cancellations(row):
    with pytest.raises(ValueError, match="annotation disagrees"):
        systemic_failures([row], frozenset({"wrong"}))


def test_operator_annotation_requires_a_baseline_outcome(tmp_path):
    path = balance_policy_file(tmp_path)
    data = read_json(path)
    data["operator_cancelled_outcomes"] = ["unretained"]
    write_json(path, data)
    with pytest.raises(ValueError, match="immutable baseline"):
        BudgetPolicy.load(path, tmp_path)
