"""Prepare a separate replay namespace without requiring private historical runs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from frozen_study import digest, file_sha, read_json, validate_manifest, write_json


def prepare(parent: dict, study_id: str, root: Path) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", study_id) or study_id == parent["study_id"]:
        raise ValueError("use a distinct study ID with letters, digits, hyphens or underscores")
    parent = read_json_value(parent)
    original_hash = digest(parent)
    provenance, runtime = {}, {}
    for relative, expected in parent["source_sha256"].items():
        if relative.startswith("tau2-bench-baseline/data/simulations/"):
            provenance[relative] = expected
        else:
            if file_sha(root / relative) != expected:
                raise ValueError(f"runtime/public source changed: {relative}")
            runtime[relative] = expected
    parent.update(
        {
            "study_id": study_id,
            "status": "new_paid_replay_not_the_recorded_original_study",
            "parent_manifest_sha256": original_hash,
            "provenance_only_sha256": provenance,
            "source_sha256": runtime,
            "budget_cap_rmb": 300,
            "additional_attempt_limit": 10,
            "total_attempt_limit": 224,
            "replay_boundary": "Same tasks/settings/event rules; new model outputs and fees. Historical raw runs remain provenance, not execution inputs. Verify dated prices before a later replay.",
        }
    )
    for key in ["prior_preflight", "accepted_smoke_study_id", "accepted_smoke_manifest_sha256"]:
        parent.pop(key, None)
    validate_manifest(parent)
    return parent


def read_json_value(value: dict) -> dict:
    import copy

    return copy.deepcopy(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    manifest = prepare(read_json(args.manifest), args.study_id, root)
    write_json(args.output, manifest, exclusive=True)
    print(
        {
            "prepared": str(args.output),
            "study_id": manifest["study_id"],
            "model_calls": 0,
            "manifest_sha256": digest(manifest),
        }
    )


if __name__ == "__main__":
    main()
