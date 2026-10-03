"""Report contracts use synthetic rows, never benchmark performance fixtures."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from frozen_study import digest, read_json, write_json  # noqa: E402
from report_study_evidence import StudyReport  # noqa: E402
from study_evidence import EvidenceBundle  # noqa: E402
from test_study_evidence import design, fixture_rows  # noqa: E402


def report(tmp_path, manifest, rows):
    path = tmp_path / "evidence.json"
    EvidenceBundle(manifest, rows).save(path, allow_incomplete=True)
    return StudyReport.load(path)


def test_missing_pairs_include_fully_unstarted_trials_without_scoring_them(tmp_path):
    manifest = design()
    rows = [
        r
        for r in fixture_rows(manifest)
        if not (r["task_id"] == manifest["task_ids"][0] and r["trial"] == 2)
        and not (r["task_id"] == manifest["task_ids"][1] and r["trial"] == 0 and r["condition"] == "U0")
    ]
    failed = next(
        r for r in rows if r["task_id"] == manifest["task_ids"][0] and r["trial"] == 1 and r["condition"] == "U0"
    )
    failed["status"] = "infrastructure_error"
    failed["metrics"]["official_final_reward"] = None
    result = report(tmp_path, manifest, rows).recompute()
    assert result["execution_coverage"] == "incomplete_snapshot"
    assert result["pairs"]["planned"] == 6
    assert result["pairs"]["both_retained"] == 4
    assert result["pairs"]["both_valid"] == 3
    assert result["pairs"]["both_unstarted"] == 1
    assert result["pairs"]["one_unstarted"] == 1
    assert result["pairs"]["without_two_valid_first_attempts"] == 3
    u0 = result["conditions"]["U0"]
    assert (u0["valid_first_attempts"], u0["invalid_first_attempts"], u0["unstarted_slots"]) == (3, 1, 2)
    assert u0["scored_non_success_first_attempts"] == 1
    assert u0["success_over_valid_first_attempts"] == pytest.approx(2 / 3)
    assert u0["success_over_retained_first_attempts"] == pytest.approx(2 / 4)
    assert u0["success_over_planned_slots"] == pytest.approx(2 / 6)
    assert not result["engineering_gate_pass"]


def test_successful_additional_attempt_never_repairs_primary_counts_or_interval(tmp_path):
    manifest = design()
    rows = fixture_rows(manifest)
    failed = next(r for r in rows if r["condition"] == "U0")
    failed["status"] = "timeout"
    failed["metrics"]["official_final_reward"] = None
    restored = {**copy.deepcopy(failed), "attempt": 1, "status": "valid"}
    restored["metrics"]["official_final_reward"] = 1
    rows.append(restored)
    result = report(tmp_path, manifest, rows).recompute()
    u0 = result["conditions"]["U0"]
    assert u0["valid_first_attempts"] == 5
    assert u0["first_attempt_status_counts"] == {"timeout": 1, "valid": 5}
    assert u0["additional_attempts"] == 1
    assert u0["valid_slots_after_additional_attempts_secondary"] == 6
    assert u0["slots_without_valid_result_after_additional_attempts"] == 0
    assert result["frozen_bootstrap_results"]["paired_reward_bootstrap"]["complete_tasks"] == 1
    assert result["pairs"]["without_two_valid_first_attempts"] == 1
    assert not result["engineering_gate_pass"]


def test_empty_snapshot_has_zero_coverage_and_undefined_scored_rate(tmp_path):
    result = report(tmp_path, design(), []).recompute()
    assert result["pairs"]["both_unstarted"] == 6
    for row in result["conditions"].values():
        assert row["unstarted_slots"] == 6
        assert row["success_over_valid_first_attempts"] is None
        assert row["success_over_retained_first_attempts"] is None
        assert row["success_over_planned_slots"] == 0


def test_fractional_reward_is_scored_not_infrastructure_failure(tmp_path):
    manifest = design()
    rows = fixture_rows(manifest)
    zero = next(r for r in rows if r["metrics"]["official_final_reward"] == 0)
    zero["metrics"]["official_final_reward"] = 0.5
    result = report(tmp_path, manifest, rows).recompute()
    assert result["conditions"][zero["condition"]]["valid_first_attempts"] == 6
    assert result["conditions"][zero["condition"]]["scored_non_success_first_attempts"] == 3
    assert result["conditions"][zero["condition"]]["invalid_first_attempts"] == 0
    assert result["execution_coverage"] == "all_primary_slots_retained"


def test_real_terminal_filter_and_valid_population_do_not_rewrite_frozen_flags(tmp_path):
    manifest = design()
    rows = fixture_rows(manifest)
    rows[0]["metrics"]["agent_after_terminal_user"] = True
    rows[1]["metrics"].update(terminal_marker="STOP", agent_after_terminal_user=True)
    rows[2]["status"] = "infrastructure_error"
    rows[2]["metrics"].update(official_final_reward=None, explicit_tool_errors=2)
    result = report(tmp_path, manifest, rows).recompute()
    all_first = result["event_diagnostics"]["all_retained_first_attempts"]
    valid = result["event_diagnostics"]["valid_first_attempts"]
    assert all_first["real_terminal_attempts"] == 1
    assert all_first["assistant_after_real_terminal_attempts"] == 1
    assert all_first["tool_event_totals"]["explicit_tool_errors"] == 2
    assert valid["tool_event_totals"]["explicit_tool_errors"] == 0
    assert rows[0]["metrics"]["agent_after_terminal_user"] is True


@pytest.mark.parametrize("name", ["retail-holdout-v1", "retail-replication-v1"])
def test_family_coverage_matches_selected_cohort_and_primary_denominators(tmp_path, name):
    manifest = design(name)
    result = report(tmp_path, manifest, fixture_rows(manifest)).recompute()
    for condition in manifest["conditions"]:
        assert sum(f[condition]["planned_slots"] for f in result["business_family_coverage"].values()) == 6
        assert sum(f[condition]["valid_first_attempts"] for f in result["business_family_coverage"].values()) == 6
    assert result["official_split"] == ("train" if "replication" in name else "test")
    assert ("exclude_near_duplicate_task38_sensitivity" in result["frozen_bootstrap_results"]) == ("holdout" in name)


def test_bilingual_outputs_share_counts_and_never_overwrite(tmp_path):
    manifest = design()
    instance = report(tmp_path, manifest, fixture_rows(manifest)[:-1])
    destination = tmp_path / "report"
    result = instance.save(destination)
    assert read_json(destination / "summary.json") == result
    assert "Incomplete snapshot" in (destination / "report.md").read_text()
    assert "未完成快照" in (destination / "report.zh-CN.md").read_text()
    assert "2/5" in (destination / "report.md").read_text()
    assert "2/5" in (destination / "report.zh-CN.md").read_text()
    for language in ("report.md", "report.zh-CN.md"):
        assert result["evidence_file_sha256"] in (destination / language).read_text()
    with pytest.raises(FileExistsError):
        instance.save(destination)


def test_load_audits_bundle_before_generating_report(tmp_path):
    manifest = design()
    path = tmp_path / "corrupt.json"
    EvidenceBundle(manifest, fixture_rows(manifest)).save(path)
    payload = read_json(path)
    payload["summary"]["finished_primary_slots"] = 0
    payload["payload_sha256"] = digest({k: v for k, v in payload.items() if k != "payload_sha256"})
    write_json(path, payload)
    with pytest.raises(ValueError, match="summary disagrees"):
        StudyReport.load(path)
