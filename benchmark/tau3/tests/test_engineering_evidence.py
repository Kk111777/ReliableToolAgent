"""Public integration reports must keep failures and planned denominators."""

import copy
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from engineering_evidence import audit, summary  # noqa: E402
from frozen_study import digest, schedule  # noqa: E402


def report():
    protocol = {
        "engineering_version": "engineering-v2",
        "study_id": "engineering-v2-fixture",
        "task_ids": ["0", "5"],
        "trials": 1,
        "base_seed": 300,
        "conditions": ["U0", "U2"],
        "deadline_seconds": 600,
        "evaluator_parse_retries": 2,
        "user_empty_retries": 1,
    }
    protocol["schedule_sha256"] = digest([s.as_dict() for s in schedule(protocol, "formal")])
    rows = [
        {
            **s.as_dict(),
            "study_id": protocol["study_id"],
            "attempt": 0,
            "status": "valid",
            "billing": {"known_list_price_rmb": 0.1, "budget_debit_rmb": 0.2, "calls": 2, "usage_unknown_calls": 1},
            "empty_user_responses": 0,
            "user_response_retries": 0,
            "evaluator_format_retries": 0,
            "normalized_evaluator_responses": 0,
        }
        for s in schedule(protocol, "formal")
    ]
    rows[0]["status"] = "infrastructure_error"
    return seal({"protocol": protocol, "rows": rows, "summary": summary(rows), "execution_state": "finished"})


def seal(data):
    data = copy.deepcopy(data)
    data.pop("payload_sha256", None)
    data["payload_sha256"] = digest(data)
    return data


def test_public_report_keeps_invalid_first_attempt_and_unknown_cost_reserve():
    result = audit(report())
    assert result["summary"]["status_counts"] == {"infrastructure_error": 1, "valid": 3}
    assert result["summary"]["conservative_list_debit_rmb"] == pytest.approx(0.8)
    assert result["summary"]["unknown_usage_requests"] == 4


def test_rehashed_false_summary_is_rejected():
    data = report()
    data["summary"]["status_counts"] = {"valid": 4}
    with pytest.raises(ValueError, match="aggregate"):
        audit(seal(data))


def test_removing_failure_cannot_leave_finished_claim():
    data = report()
    data["rows"].pop(0)
    data["summary"] = summary(data["rows"])
    with pytest.raises(ValueError, match="missing"):
        audit(seal(data))
    data["execution_state"] = "stopped_at_gate"
    assert len(audit(seal(data))["missing_slots"]) == 1


def test_duplicate_or_retried_attempt_rejected():
    data = report()
    data["rows"][1] = copy.deepcopy(data["rows"][0])
    with pytest.raises(ValueError, match="duplicate"):
        audit(seal(data))
    data = report()
    data["rows"][0]["attempt"] = 1
    with pytest.raises(ValueError, match="additional"):
        audit(seal(data))
