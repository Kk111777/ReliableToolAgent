"""Public-record contracts; no additional review labels or model requests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.audit_model_review import ModelReviewAudit, payload_digest


SOURCE = Path(__file__).resolve().parents[1] / "reports/model-review-v1/summary.json"


def record():
    return copy.deepcopy(json.loads(SOURCE.read_text()))


def sealed(value):
    value["payload_sha256"] = payload_digest({k: v for k, v in value.items() if k != "payload_sha256"})
    return ModelReviewAudit(value)


def test_published_record_preserves_first_disagreements_and_missing_counts():
    summary = ModelReviewAudit.load(SOURCE).recompute()
    assert summary["labels_agreeing"] == 117
    assert summary["labels_compared"] == 120
    assert summary["known_reference_labels_agreeing"] == summary["known_reference_labels_compared"] == 102
    assert [r["clip_id"] for r in summary["differences"]] == ["B08", "S02", "S06"]
    assert all(r["first_label"] == 0 and r["protocol_label"] is None for r in summary["differences"])


def test_modified_payload_is_rejected_before_recount():
    value = record()
    value["rows"][0]["first_labels"]["reference_write_occurrences"] = 2
    with pytest.raises(ValueError, match="digest"):
        ModelReviewAudit(value).recompute()


@pytest.mark.parametrize("change", ["duplicate", "missing", "reorder"])
def test_clip_identity_changes_are_rejected(change):
    value = record()
    if change == "duplicate":
        value["rows"][1]["clip_id"] = "B01"
    elif change == "missing":
        value["rows"].pop()
    else:
        value["rows"].reverse()
    with pytest.raises(ValueError, match="identities"):
        sealed(value).recompute()


@pytest.mark.parametrize("bad", [False, "0", -1])
def test_counts_reject_booleans_strings_and_negative_values(bad):
    value = record()
    value["rows"][0]["first_labels"]["successful_exact_reference_matches"] = bad
    with pytest.raises(ValueError, match="count"):
        sealed(value).recompute()


def test_missing_reference_cannot_be_silently_changed_to_zero():
    value = record()
    value["rows"][7]["protocol_labels"]["successful_exact_reference_matches"] = 0
    with pytest.raises(ValueError, match="missing references"):
        sealed(value).recompute()


def test_nonterminal_user_does_not_create_after_terminal_activity():
    value = record()
    value["rows"][7]["protocol_labels"]["assistant_observed_after_terminal_user"] = False
    with pytest.raises(ValueError, match="nonterminal"):
        sealed(value).recompute()


def test_recorded_summary_cannot_hide_a_first_disagreement():
    value = record()
    value["summary"]["labels_agreeing"] = 120
    value["summary"]["differences"] = []
    with pytest.raises(ValueError, match="summary"):
        sealed(value).recompute()


@pytest.mark.parametrize("field", ["strict_independent_blind_review", "human_annotation"])
def test_unsupported_independence_claim_is_rejected(field):
    value = record()
    value["reviewer"][field] = True
    with pytest.raises(ValueError, match="provenance"):
        sealed(value).recompute()


def test_private_raw_text_field_is_not_part_of_public_schema():
    value = record()
    value["rows"][0]["raw_message"] = "example private content"
    with pytest.raises(ValueError, match="excerpt fields"):
        sealed(value).recompute()


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        ModelReviewAudit.load(path)
