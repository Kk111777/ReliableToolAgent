"""Combined budget counts reused smoke attempts once and retains unknown fees."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from finish_retail_studies import effective_replication, systemic_failure, unique_paid_rows  # noqa: E402


def row(key, phase, debit):
    return {
        "study_id": "fixture",
        "slot_id": key,
        "attempt": 0,
        "outcome_sha256": key,
        "phase": phase,
        "status": "valid",
        "billing": {"budget_debit_rmb": debit},
    }


def test_shared_smoke_costs_are_not_counted_twice():
    smoke, first, second = row("smoke", "smoke", 2), row("first", "formal", 10), row("second", "formal", 20)
    assert len(unique_paid_rows([smoke, first], [smoke, second])) == 3
    effective = effective_replication(
        {"combined_budget_cap_rmb": 500, "prior_preflight": {"budget_debit_rmb": 1}}, [smoke, first]
    )
    assert effective["budget_cap_rmb"] == 489
    with pytest.raises(ValueError):
        unique_paid_rows([smoke], [{**smoke, "outcome_sha256": "changed"}])


def test_systemic_stop_gate_does_not_treat_scored_failures_as_infrastructure():
    rows = [row(str(i), "formal", 1) for i in range(3)]
    assert not systemic_failure(rows)
    assert systemic_failure([{**r, "status": "timeout"} for r in rows])
