"""Synthetic case contracts do not add benchmark tasks or performance evidence."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_study_cases import CaseAudit  # noqa: E402
from frozen_study import digest, write_json  # noqa: E402
from study_evidence import EvidenceBundle  # noqa: E402
from test_study_evidence import design, fixture_rows  # noqa: E402


def fixture(tmp_path):
    manifest = design()
    rows = fixture_rows(manifest)
    row = rows[0]
    row["artifact_sha256"]["simulation.json"] = "1" * 64
    row["metrics"].update(
        tool_calls=5,
        explicit_tool_errors=1,
        unknown_tool_results=1,
        same_message_duplicate_calls=2,
        same_message_excess_calls=1,
        cross_turn_exact_repeats=2,
    )
    case = {
        "case_id": "C01",
        "study_id": row["study_id"],
        "slot_id": row["slot_id"],
        "attempt": 0,
        "status": row["status"],
        "outcome_sha256": row["outcome_sha256"],
        "simulation_sha256": "1" * 64,
        "message_indices": [2, 6],
        "selected_message_roles": [
            {"message_index": 2, "role": "assistant"},
            {"message_index": 6, "role": "assistant"},
        ],
        "tool_events": [
            {
                "message_index": pos,
                "tool_name": "get_order_details",
                "tool_type": "other",
                "status": status,
                "arguments_sha256": arg * 64,
            }
            for pos, status, arg in [
                (2, "success", "a"),
                (2, "success", "a"),
                (4, "error", "a"),
                (4, "unknown", "b"),
                (6, "success", "a"),
            ]
        ],
        "metrics": copy.deepcopy(row["metrics"]),
    }
    index = {
        "schema_version": 1,
        "study_id": manifest["study_id"],
        "manifest_sha256": digest(manifest),
        "source_review_sha256": "2" * 64,
        "selection": "Synthetic contract fixture",
        "boundary": "No performance claim",
        "cases": [case],
    }
    evidence = tmp_path / "evidence.json"
    EvidenceBundle(manifest, rows).save(evidence)
    return evidence, index


def check(tmp_path, evidence, index):
    index["payload_sha256"] = digest({k: v for k, v in index.items() if k != "payload_sha256"})
    path = tmp_path / "cases.json"
    write_json(path, index)
    return CaseAudit.load(evidence, path).recompute()


def test_tool_counts_distinguish_duplicate_group_members_excess_and_cross_turns(tmp_path):
    evidence, index = fixture(tmp_path)
    result = check(tmp_path, evidence, index)
    assert result["case_count"] == 1
    assert result["cases"][0] == {
        "case_id": "C01",
        "slot_id": index["cases"][0]["slot_id"],
        "attempt": 0,
        "tool_calls": 5,
        "explicit_tool_errors": 1,
        "unknown_tool_results": 1,
        "same_message_duplicate_calls": 2,
        "same_message_excess_calls": 1,
        "cross_turn_exact_repeats": 2,
    }
    assert "semantic judgments" in result["boundary"]


@pytest.mark.parametrize(
    "field,value",
    [("status", "timeout"), ("outcome_sha256", "f" * 64), ("simulation_sha256", "f" * 64), ("attempt", 1)],
)
def test_case_must_match_exact_retained_attempt(tmp_path, field, value):
    evidence, index = fixture(tmp_path)
    index["cases"][0][field] = value
    with pytest.raises(ValueError, match="compact evidence"):
        check(tmp_path, evidence, index)


def test_rehashed_case_metric_tampering_is_rejected(tmp_path):
    evidence, index = fixture(tmp_path)
    index["cases"][0]["metrics"]["official_final_reward"] = 0.5
    with pytest.raises(ValueError, match="metrics disagrees"):
        check(tmp_path, evidence, index)


def test_omitted_tool_event_is_not_hidden_by_unchanged_reported_metrics(tmp_path):
    evidence, index = fixture(tmp_path)
    index["cases"][0]["tool_events"].pop()
    with pytest.raises(ValueError, match="tool counters"):
        check(tmp_path, evidence, index)


@pytest.mark.parametrize("field", ["arguments", "content"])
def test_raw_argument_or_message_fields_are_not_allowed(tmp_path, field):
    evidence, index = fixture(tmp_path)
    index["cases"][0]["tool_events"][0][field] = "must not be published"
    with pytest.raises(ValueError, match="must be omitted"):
        check(tmp_path, evidence, index)


def test_duplicate_case_identity_rejected_even_with_a_new_label(tmp_path):
    evidence, index = fixture(tmp_path)
    index["cases"].append({**copy.deepcopy(index["cases"][0]), "case_id": "C02"})
    with pytest.raises(ValueError, match="duplicate"):
        check(tmp_path, evidence, index)


@pytest.mark.parametrize("change", ["order", "roles", "hash", "cohort"])
def test_invalid_case_positions_and_sources_fail_closed(tmp_path, change):
    evidence, index = fixture(tmp_path)
    case = index["cases"][0]
    if change == "order":
        case["tool_events"].reverse()
    elif change == "roles":
        case["selected_message_roles"][0]["message_index"] = 3
    elif change == "hash":
        case["tool_events"][0]["arguments_sha256"] = "not a hash"
    else:
        index["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        check(tmp_path, evidence, index)


def test_empty_tool_sequence_for_retained_no_tool_attempt_is_valid(tmp_path):
    evidence, index = fixture(tmp_path)
    from frozen_study import read_json

    payload = read_json(evidence)
    row = payload["rows"][0]
    for field in CaseAudit.tool_counts([]):
        row["metrics"][field] = 0
    EvidenceBundle(payload["manifest"], payload["rows"]).save(tmp_path / "empty-tools.json")
    index["cases"][0].update(tool_events=[], message_indices=[], selected_message_roles=[], metrics=row["metrics"])
    assert check(tmp_path, tmp_path / "empty-tools.json", index)["cases"][0]["tool_calls"] == 0


def test_evidence_summary_must_pass_existing_audit_before_cases_are_checked(tmp_path):
    evidence, index = fixture(tmp_path)
    from frozen_study import read_json

    payload = read_json(evidence)
    payload["summary"]["conditions"]["U0"]["first_attempt_success"] += 1
    payload["payload_sha256"] = digest({k: v for k, v in payload.items() if k != "payload_sha256"})
    write_json(evidence, payload)
    with pytest.raises(ValueError, match="summary disagrees"):
        check(tmp_path, evidence, index)
