"""Compact evidence contracts; generated rows are protocol fixtures only."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from frozen_study import analyze_simulation, digest, file_sha, read_json, schedule, write_json  # noqa: E402
from study_evidence import EvidenceBundle, audit, compact_row, export, usage_by_role  # noqa: E402


def design(name="retail-holdout-v1"):
    manifest = read_json(Path(__file__).resolve().parents[1] / "studies" / name / "manifest.json")
    manifest["task_ids"] = manifest["task_ids"][:2]
    manifest["study_id"] = "evidence-contract-fixture"
    manifest["schedule_sha256"] = digest([s.as_dict() for s in schedule(manifest, "formal")])
    return manifest


def fixture_rows(manifest):
    rows = []
    for slot in schedule(manifest, "formal"):
        reward = int((slot.task_id == manifest["task_ids"][0]) == (slot.condition == "U2"))
        rows.append(
            {
                **slot.as_dict(),
                "study_id": manifest["study_id"],
                "attempt": 0,
                "status": "valid",
                "metrics": analyze_simulation({"reward_info": {"reward": reward}}),
                "billing": {"calls": 0, "usage_unknown_calls": 0, "known_list_price_rmb": 0, "budget_debit_rmb": 0},
                "outcome_sha256": "0" * 64,
                "artifact_sha256": {},
                "usage_by_role": usage_by_role([]),
                "wall_seconds": 1,
            }
        )
    return rows


def test_offline_roundtrip_keeps_task_clusters_and_rejects_summary_tampering(tmp_path):
    manifest = design()
    destination = tmp_path / "bundle.json"
    summary = EvidenceBundle(manifest, fixture_rows(manifest)).save(destination)
    assert audit(destination) == summary
    paired = summary["paired_reward_bootstrap"]
    assert paired["complete_tasks"] == 2
    assert paired["mean_difference_U2_minus_U0"] == 0
    assert paired["confidence_interval_95"] == [-1, 1]
    payload = read_json(destination)
    payload["summary"]["conditions"]["U0"]["first_attempt_success"] += 1
    payload["payload_sha256"] = digest({k: v for k, v in payload.items() if k != "payload_sha256"})
    write_json(destination, payload)
    with pytest.raises(ValueError, match="summary disagrees"):
        audit(destination)


def test_incomplete_export_requires_explicit_diagnostic_flag(tmp_path):
    manifest = design()
    rows = fixture_rows(manifest)[:-1]
    destination = tmp_path / "incomplete.json"
    with pytest.raises(ValueError, match="incomplete"):
        EvidenceBundle(manifest, rows).save(destination)
    assert not destination.exists()
    summary = EvidenceBundle(manifest, rows).save(destination, allow_incomplete=True)
    assert not summary["complete"]
    assert len(summary["unstarted_primary_slots"]) == 1
    assert not summary["engineering_gate_pass"]


@pytest.mark.parametrize(
    "change,match",
    [
        ("seed", "paired seed"),
        ("duplicate", "duplicate"),
        ("successful_retry", "retained invalid"),
        ("secret_field", "unexpected public"),
        ("usage_secret", "unexpected public usage"),
    ],
)
def test_corrupt_identity_or_private_fields_are_rejected(change, match):
    manifest = design()
    rows = fixture_rows(manifest)
    if change == "seed":
        rows[0]["seed"] += 1
    elif change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "successful_retry":
        rows.append({**copy.deepcopy(rows[0]), "attempt": 1})
    elif change == "secret_field":
        rows[0]["raw_provider_response"] = "private text"
    else:
        rows[0]["usage_by_role"]["agent"]["prompt"] = 123
    with pytest.raises(ValueError, match=match):
        EvidenceBundle(manifest, rows).recompute()


def test_unknown_request_cost_is_retained_and_reasoning_is_not_double_counted():
    events = [
        {"call_index": 1, "role": "agent", "known_list_price_rmb": None, "budget_debit_rmb": 2},
        {
            "call_index": 1,
            "role": "agent",
            "known_list_price_rmb": 0.1,
            "budget_debit_rmb": 0.1,
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 30,
                "completion_tokens_details": {"reasoning_tokens": 20},
            },
        },
        {"call_index": 2, "role": "evaluator", "known_list_price_rmb": None, "budget_debit_rmb": 3},
        {
            "call_index": 3,
            "role": "user",
            "known_list_price_rmb": 0.2,
            "budget_debit_rmb": 0.2,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "completion_tokens_details": None,
                "prompt_tokens_details": {"cached_tokens": 4},
            },
        },
    ]
    result = usage_by_role(events)
    assert result["agent"]["observed_http_requests"] == 1
    assert result["agent"]["completion_tokens_known"] == 30
    assert result["agent"]["reasoning_tokens_known"] == 20
    assert result["evaluator"]["missing_usage_requests"] == 1
    assert result["evaluator"]["conservative_budget_debit_rmb"] == 3
    assert result["user"]["cached_input_tokens_known"] == 4
    assert result["user"]["reasoning_usage_present_requests"] == 0
    assert sum(x["known_list_price_rmb"] for x in result.values()) == pytest.approx(0.3)


def test_replication_uses_its_own_seven_strata_and_separate_label():
    manifest = design("retail-replication-v1")
    summary = EvidenceBundle(manifest, fixture_rows(manifest)).recompute()
    assert len(summary["write_family_sensitivity"]) == 7
    assert summary["official_split"].startswith("train;")
    assert "exclude_near_duplicate_task38_sensitivity" not in summary
    assert sum(v["U0"]["valid"] for v in summary["write_family_sensitivity"].values()) == 6


def test_raw_export_verifies_events_and_does_not_overwrite(tmp_path):
    manifest = design()
    rows = fixture_rows(manifest)
    source = tmp_path / "source"
    write_json(source / "manifest.json", manifest)
    ledger = []
    for row in rows:
        simulation = {"reward_info": {"reward": row["metrics"]["official_final_reward"]}}
        directory = source / "attempts" / row["slot_id"]
        write_json(directory / "simulation.json", simulation)
        private_row = {k: v for k, v in row.items() if k not in {"usage_by_role", "outcome_sha256", "artifact_sha256"}}
        private_row["private_annotation"] = "must be omitted"
        write_json(directory / "outcome.json", private_row)
        ledger.append(
            {
                **private_row,
                "outcome_path": str((directory / "outcome.json").relative_to(source)),
                "outcome_sha256": file_sha(directory / "outcome.json"),
                "artifact_sha256": {"simulation.json": file_sha(directory / "simulation.json")},
            }
        )
    (source / "attempts.jsonl").write_text("\n".join(json.dumps(row) for row in ledger) + "\n")
    destination = tmp_path / "public.json"
    export(source, destination)
    assert "must be omitted" not in destination.read_text()
    with pytest.raises(FileExistsError):
        export(source, destination)
    write_json(source / ledger[0]["outcome_path"], {})
    with pytest.raises(ValueError, match="outcome changed"):
        export(source, tmp_path / "corrupt.json")


def test_compact_projection_rejects_nested_provider_text():
    manifest = design()
    row = fixture_rows(manifest)[0]
    row["metrics"]["provider_payload"] = "private"
    with pytest.raises(ValueError, match="unexpected metric"):
        compact_row(row, [])


@pytest.mark.parametrize(
    "key,value",
    [
        ("tool_calls", -1),
        ("duration_seconds", float("nan")),
        ("terminal_marker", "provider text"),
        ("db_reward", "private text"),
    ],
)
def test_nonprimitive_or_invalid_metric_values_are_rejected(key, value):
    manifest = design()
    rows = fixture_rows(manifest)
    rows[0]["metrics"][key] = value
    with pytest.raises(ValueError, match="primitive event metric"):
        EvidenceBundle(manifest, rows).recompute()


def test_fractional_official_reward_is_retained_as_valid():
    manifest = design()
    rows = fixture_rows(manifest)
    rows[0]["metrics"]["official_final_reward"] = 0.5
    result = EvidenceBundle(manifest, rows).recompute()
    condition = rows[0]["condition"]
    assert result["conditions"][condition]["first_attempt_valid"] == 6


def test_unfinished_frozen_checkpoint_retains_its_unknown_reason():
    manifest = design()
    rows = fixture_rows(manifest)
    rows[0]["status"] = "infrastructure_error"
    rows[0]["metrics"]["official_final_reward"] = None
    rows[0]["metrics"]["termination_reason"] = "None"
    result = EvidenceBundle(manifest, rows).recompute()
    assert result["conditions"][rows[0]["condition"]]["first_attempt_valid"] == 5
    assert rows[0]["metrics"]["termination_reason"] == "None"
