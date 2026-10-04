"""Hand-authored measurement contracts; not new business tasks or human labels."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from frozen_study import analyze_simulation, append_json, file_sha, write_json  # noqa: E402
from measurement_v2 import MeasurementAudit, ReferenceWriteMeasurement  # noqa: E402


WRITE = "cancel_pending_order"


def reference(order="A"):
    return {"tool_type": "write", "action": {"name": WRITE, "arguments": {"order_id": order}}}


def call(order="A", call_id="c1"):
    return {"role": "assistant", "tool_calls": [{"id": call_id, "name": WRITE, "arguments": {"order_id": order}}]}


def result(call_id="c1", error=False):
    return {"role": "tool", "id": call_id, "error": error}


def simulation(messages, references):
    return {"messages": messages, "reward_info": {"action_checks": references}}


def measure(messages, references):
    return ReferenceWriteMeasurement(simulation(messages, references)).measure()


@pytest.mark.parametrize(
    "orders,expected_matched,expected_missing,completion,candidate",
    [([], 0, 2, "none", True), (["A"], 1, 1, "partial", True), (["A", "B"], 2, 0, "all", False)],
)
def test_none_partial_all_write_occurrences(orders, expected_matched, expected_missing, completion, candidate):
    messages = []
    for index, order in enumerate(orders):
        messages.extend([call(order, str(index)), result(str(index))])
    messages.append({"role": "user", "content": "Confirmed ###STOP###"})
    metrics = measure(messages, [reference("A"), reference("B")])
    assert metrics["reference_write_actions_expected"] == 2
    assert metrics["reference_write_actions_matched"] == expected_matched
    assert metrics["reference_write_actions_missing_at_terminal"] == expected_missing
    assert metrics["reference_write_completion_at_terminal"] == completion
    assert metrics["terminal_with_missing_reference_writes_candidate"] is candidate
    assert metrics["agent_after_terminal_user_v2"] is False


def test_duplicate_reference_occurrences_need_distinct_successes():
    metrics = measure([call(), result(), {"role": "user", "content": "###STOP###"}], [reference(), reference()])
    assert metrics["reference_write_actions_expected"] == 2
    assert metrics["reference_write_actions_matched"] == 1
    assert metrics["reference_write_actions_missing"] == 1
    assert metrics["terminal_with_missing_reference_writes_candidate"] is True
    twice = measure([call(), result(), call(call_id="c2"), result("c2")], [reference(), reference()])
    assert twice["reference_write_actions_matched"] == 2
    assert twice["reference_write_actions_missing"] == 0


def test_repeated_success_cannot_cover_another_reference_target():
    metrics = measure([call(), result(), call(call_id="c2"), result("c2")], [reference(), reference("B")])
    assert metrics["reference_write_actions_matched"] == 1
    assert metrics["reference_write_actions_missing"] == 1


@pytest.mark.parametrize("response", [None, {"role": "tool", "id": "different", "error": False}, result(error=None)])
def test_unknown_and_mismatched_result_do_not_count_as_success(response):
    messages = [call()] + ([response] if response else []) + [{"role": "user", "content": "###STOP###"}]
    metrics = measure(messages, [reference()])
    assert metrics["reference_write_actions_matched"] == 0
    assert metrics["reference_write_actions_missing"] == 1
    assert metrics["reference_write_unknown_result_candidates"] == 1
    assert metrics["terminal_with_missing_reference_writes_candidate"] is True


def test_explicit_error_is_not_success_or_unknown():
    metrics = measure([call(), result(error=True)], [reference()])
    assert metrics["reference_write_actions_matched"] == 0
    assert metrics["reference_write_unknown_result_candidates"] == 0


def test_unknown_candidates_cannot_double_count_already_satisfied_reference():
    metrics = measure([call(), result(), call(call_id="c2")], [reference()])
    assert metrics["reference_write_actions_matched"] == 1
    assert metrics["reference_write_unknown_result_candidates"] == 0


def test_id_reuse_retains_frozen_local_response_window():
    metrics = measure([call(), result(error=True), call(), result()], [reference(), reference()])
    assert metrics["reference_write_actions_matched"] == 1
    assert metrics["reference_write_actions_missing"] == 1


def test_duplicate_call_id_is_ambiguous_not_two_successes():
    message = call()
    message["tool_calls"].append(copy.deepcopy(message["tool_calls"][0]))
    metrics = measure([message, result()], [reference(), reference()])
    assert metrics["reference_write_actions_matched"] == 0
    assert metrics["reference_write_unknown_result_candidates"] == 2


@pytest.mark.parametrize(
    "messages",
    [[], [{"role": "assistant", "content": "###STOP###"}], [{"role": "user", "content": "Please continue"}, call()]],
)
def test_no_user_or_ordinary_user_is_not_terminal(messages):
    metrics = measure(messages, [reference()])
    assert metrics["terminal_user_present"] is False
    assert metrics["agent_after_terminal_user_v2"] is None
    assert metrics["terminal_with_missing_reference_writes_candidate"] is False
    assert metrics["reference_write_actions_missing_at_terminal"] is None


@pytest.mark.parametrize("marker", ["STOP", "TRANSFER"])
@pytest.mark.parametrize("after", [False, True])
def test_terminal_user_markers_have_explicit_agent_continuation(marker, after):
    messages = [{"role": "user", "content": f"###{marker}###"}]
    if after:
        messages.append({"role": "assistant", "content": "Acknowledged"})
    metrics = measure(messages, [reference()])
    assert metrics["terminal_user_present"] is True
    assert metrics["final_user_terminal_marker"] == marker
    assert metrics["agent_after_terminal_user_v2"] is after


def test_only_final_observed_user_defines_end_of_trace_candidate():
    metrics = measure(
        [{"role": "user", "content": "###STOP###"}, {"role": "user", "content": "Continue"}], [reference()]
    )
    assert metrics["terminal_user_present"] is False
    assert metrics["terminal_with_missing_reference_writes_candidate"] is False


def test_write_after_terminal_does_not_retroactively_satisfy_terminal_reference_count():
    metrics = measure([{"role": "user", "content": "###STOP###"}, call(), result()], [reference()])
    assert metrics["reference_write_actions_matched"] == 1
    assert metrics["reference_write_actions_missing"] == 0
    assert metrics["reference_write_actions_matched_before_terminal"] == 0
    assert metrics["reference_write_actions_missing_at_terminal"] == 1
    assert metrics["terminal_with_missing_reference_writes_candidate"] is True
    assert metrics["agent_after_terminal_user_v2"] is True


@pytest.mark.parametrize("messages", [None, {}, "unknown"])
def test_missing_or_unknown_trace_produces_unavailable_not_positive_claim(messages):
    metrics = ReferenceWriteMeasurement(simulation(messages, [reference()])).measure()
    assert metrics["message_trace_available"] is False
    assert metrics["terminal_user_present"] is None
    assert metrics["agent_after_terminal_user_v2"] is None
    assert metrics["reference_write_actions_matched"] is None
    assert metrics["terminal_with_missing_reference_writes_candidate"] is None


@pytest.mark.parametrize("content", [None, ["###STOP###"], {"text": "###STOP###"}])
def test_unknown_user_content_is_not_stringified_into_terminal(content):
    metrics = measure([{"role": "user", "content": content}], [reference()])
    assert metrics["terminal_user_present"] is None
    assert metrics["terminal_with_missing_reference_writes_candidate"] is None


@pytest.mark.parametrize("reward", [None, {}, {"action_checks": None}, {"action_checks": [{}]}])
def test_missing_reference_information_is_not_empty_reference_set(reward):
    metrics = ReferenceWriteMeasurement(
        {"messages": [{"role": "user", "content": "###STOP###"}], "reward_info": reward}
    ).measure()
    assert metrics["reference_write_actions_available"] is False
    assert metrics["reference_write_actions_expected"] is None
    assert metrics["terminal_with_missing_reference_writes_candidate"] is None


def test_explicit_empty_reference_list_is_known_empty():
    metrics = measure([{"role": "user", "content": "###STOP###"}], [])
    assert metrics["reference_write_actions_expected"] == 0
    assert metrics["reference_write_completion"] == "no_reference_writes"
    assert metrics["terminal_with_missing_reference_writes_candidate"] is False


def test_missing_arguments_are_not_silently_matched_to_empty_reference_arguments():
    empty_reference = {"tool_type": "write", "action": {"name": WRITE, "arguments": {}}}
    message = call()
    del message["tool_calls"][0]["arguments"]
    metrics = measure([message, result()], [empty_reference])
    assert metrics["reference_write_actions_matched"] == 0
    malformed_reference = {"tool_type": "write", "action": {"name": WRITE}}
    assert measure([], [malformed_reference])["reference_write_actions_available"] is False


def test_input_and_frozen_metrics_are_not_modified():
    source = simulation([call(), result(), {"role": "user", "content": "###STOP###"}], [reference(), reference("B")])
    original = copy.deepcopy(source)
    frozen_before = analyze_simulation(source)
    assert frozen_before["terminal_before_reference_write_candidate"] is False
    assert ReferenceWriteMeasurement(source).measure()["terminal_with_missing_reference_writes_candidate"] is True
    assert source == original
    assert analyze_simulation(source) == frozen_before


def retained_study(tmp_path):
    source = simulation([call(), result(), {"role": "user", "content": "###STOP###"}], [reference(), reference("B")])
    attempt = tmp_path / "attempts" / "fixture"
    write_json(attempt / "simulation.json", source)
    write_json(
        attempt / "outcome.json",
        {
            "study_id": "fixture",
            "slot_id": "formal-t1-U0-r0",
            "phase": "formal",
            "attempt": 0,
            "status": "valid",
            "metrics": analyze_simulation(source),
        },
    )
    row = {
        "phase": "formal",
        "attempt": 0,
        "slot_id": "formal-t1-U0-r0",
        "study_id": "fixture",
        "status": "valid",
        "outcome_path": "attempts/fixture/outcome.json",
        "outcome_sha256": file_sha(attempt / "outcome.json"),
        "artifact_sha256": {"simulation.json": file_sha(attempt / "simulation.json")},
        "metrics": analyze_simulation(source),
    }
    append_json(tmp_path / "attempts.jsonl", row)
    write_json(tmp_path / "manifest.json", {"study_id": "fixture"})
    return row


def test_metadata_audit_verifies_source_and_does_not_export_arguments(tmp_path):
    retained_study(tmp_path)
    report = MeasurementAudit(tmp_path).build()
    assert report["first_attempts"] == 1
    assert report["summary_valid_first_attempts"]["partial_completion_terminal_candidates"] == 1
    assert "order_id" not in str(report)
    assert "Confirmed" not in str(report)
    assert len(report["rows"][0]["simulation_sha256"]) == 64
    write_json(tmp_path / "attempts/fixture/simulation.json", {"messages": []})
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        MeasurementAudit(tmp_path).build()


def test_duplicate_ledger_identity_is_rejected(tmp_path):
    row = retained_study(tmp_path)
    append_json(tmp_path / "attempts.jsonl", row)
    with pytest.raises(ValueError, match="duplicate first-attempt"):
        MeasurementAudit(tmp_path).build()


def test_case_source_mismatch_is_rejected(tmp_path):
    row = retained_study(tmp_path)
    case = {key: row[key] for key in ("study_id", "slot_id", "attempt", "outcome_sha256")}
    case.update(case_id="C01", simulation_sha256="0" * 64)
    cases = tmp_path / "cases.json"
    write_json(cases, {"cases": [case]})
    with pytest.raises(ValueError, match="case source digest mismatch"):
        MeasurementAudit(tmp_path, cases).build()


def test_ledger_status_cannot_override_retained_outcome(tmp_path):
    row = retained_study(tmp_path)
    row["status"] = "infrastructure_error"
    (tmp_path / "attempts.jsonl").unlink()
    append_json(tmp_path / "attempts.jsonl", row)
    with pytest.raises(ValueError, match="ledger disagrees with retained outcome"):
        MeasurementAudit(tmp_path).build()


def compact_fixture(tmp_path, with_cases=False):
    from frozen_study import digest, read_json
    from measurement_v2 import CompactMeasurementAudit
    from study_evidence import EvidenceBundle
    from test_study_evidence import design, fixture_rows

    manifest = design()
    public_rows = fixture_rows(manifest)
    write_json(tmp_path / "manifest.json", manifest)
    for row in public_rows:
        source = simulation(
            [call(), result(), {"role": "user", "content": "###STOP###"}], [reference(), reference("B")]
        )
        source["reward_info"]["reward"] = row["metrics"]["official_final_reward"]
        row["metrics"] = analyze_simulation(source)
        directory = tmp_path / "attempts" / row["slot_id"]
        write_json(directory / "simulation.json", source)
        write_json(directory / "outcome.json", row)
        row["outcome_sha256"] = file_sha(directory / "outcome.json")
        row["artifact_sha256"]["simulation.json"] = file_sha(directory / "simulation.json")
        append_json(
            tmp_path / "attempts.jsonl",
            {**row, "outcome_path": f"attempts/{row['slot_id']}/outcome.json"},
        )
    evidence = tmp_path / "evidence.json"
    EvidenceBundle(manifest, public_rows).save(evidence)
    cases_path = None
    if with_cases:
        row = public_rows[0]
        case = {key: row[key] for key in ("study_id", "slot_id", "attempt", "outcome_sha256")}
        case.update(case_id="C01", simulation_sha256=row["artifact_sha256"]["simulation.json"])
        cases_path = tmp_path / "case_index.json"
        write_json(cases_path, {"cases": [case]})
    path = tmp_path / "measurement.json"
    report = MeasurementAudit(tmp_path, cases_path, evidence).build()
    write_json(path, report)
    assert CompactMeasurementAudit(path, evidence, cases_path).recompute()["first_attempts"] == 12
    return path, evidence, cases_path, digest, read_json


def test_public_compact_roundtrip_recomputes_counts_and_provenance(tmp_path):
    from measurement_v2 import CompactMeasurementAudit

    path, evidence, cases, _, _ = compact_fixture(tmp_path, with_cases=True)
    result = CompactMeasurementAudit(path, evidence, cases).recompute()
    assert result["summary_valid_first_attempts"]["partial_completion_terminal_candidates"] == 12
    assert result["case_count"] == 1
    assert "not independently recomputed" in result["boundary"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("summary", "summary disagrees"),
        ("duplicate", "duplicate measurement row"),
        ("missing", "rows missing"),
        ("case", "selected case metadata mismatch"),
        ("raw_field", "unexpected measurement row fields"),
        ("source", "source identity/hash mismatch"),
        ("counts", "inconsistent reference occurrence counts"),
        ("source_bundle", "public source evidence hash mismatch"),
    ],
)
def test_public_compact_rejects_tampering_even_with_resealed_payload(tmp_path, mutation, match):
    from measurement_v2 import CompactMeasurementAudit

    path, evidence, cases, digest, read_json = compact_fixture(tmp_path, with_cases=True)
    report = read_json(path)
    if mutation == "summary":
        report["summary_valid_first_attempts"]["partial_completion_terminal_candidates"] += 1
    elif mutation == "duplicate":
        report["rows"].append(copy.deepcopy(report["rows"][0]))
    elif mutation == "missing":
        report["rows"].pop()
    elif mutation == "case":
        report["selected_cases"][0]["measurement_v2"]["terminal_user_present"] = False
    elif mutation == "raw_field":
        report["rows"][0]["raw_trace"] = "must not be public"
    elif mutation == "source":
        report["rows"][0]["simulation_sha256"] = "0" * 64
    elif mutation == "counts":
        report["rows"][0]["measurement_v2"]["reference_write_actions_matched"] += 1
    elif mutation == "source_bundle":
        report["source_public_evidence_sha256"] = "0" * 64
    report["payload_sha256"] = digest({key: value for key, value in report.items() if key != "payload_sha256"})
    write_json(path, report)
    with pytest.raises(ValueError, match=match):
        CompactMeasurementAudit(path, evidence, cases).recompute()
