"""Replay preparation preserves method while separating private provenance."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from frozen_study import file_sha, read_json  # noqa: E402
from prepare_frozen_replay import prepare  # noqa: E402


def test_new_replay_uses_public_runtime_and_keeps_historical_provenance(tmp_path):
    parent = read_json(Path(__file__).resolve().parents[1] / "studies/retail-holdout-v1/manifest.json")
    runtime = tmp_path / "runtime.py"
    runtime.write_text("fixture")
    parent["source_sha256"] = {
        "runtime.py": file_sha(runtime),
        "tau2-bench-baseline/data/simulations/private/results.json": "oldhash",
    }
    replay = prepare(parent, "new-replay", tmp_path)
    assert replay["source_sha256"] == {"runtime.py": file_sha(runtime)}
    assert len(replay["provenance_only_sha256"]) == 1
    assert replay["schedule_sha256"] == parent["schedule_sha256"]
    assert replay["model_args"] == parent["model_args"]
    assert replay["budget_cap_rmb"] == 300
    assert "prior_preflight" not in replay
    assert "prior_preflight" in parent


@pytest.mark.parametrize("study_id", ["../escape", "", "a" * 65])
def test_replay_rejects_invalid_ids(study_id, tmp_path):
    with pytest.raises(ValueError):
        prepare({"study_id": "parent"}, study_id, tmp_path)
