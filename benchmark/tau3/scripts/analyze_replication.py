"""Analyze the separate stratified retail train-split replication."""

from __future__ import annotations

import argparse
from pathlib import Path

from analyze_frozen_study import aggregate
from frozen_study import analyze_simulation, file_sha, paired_bootstrap, read_json, read_jsonl, write_json


def analyze(input_dir: Path, output_dir: Path) -> dict:
    manifest = read_json(input_dir / "manifest.json")
    rows = read_jsonl(input_dir / "attempts.jsonl")
    for row in rows:
        outcome = input_dir / row["outcome_path"]
        if file_sha(outcome) != row["outcome_sha256"]:
            raise ValueError("outcome hash mismatch")
        for name, expected in row["artifact_sha256"].items():
            if file_sha(outcome.parent / name) != expected:
                raise ValueError("raw attempt artifact hash mismatch")
        simulation = outcome.parent / "simulation.json"
        if simulation.exists() and analyze_simulation(read_json(simulation)) != row["metrics"]:
            raise ValueError("event metrics disagree with retained trajectory")
    result = aggregate(manifest, rows)
    root = Path(__file__).resolve().parents[3]
    audit = read_json(root / manifest["task_audit_relative_path"])
    primary = [row for row in rows if row["phase"] == "formal" and row["attempt"] == 0]
    strata = {}
    for stratum in sorted({row["stratum"] for row in audit["tasks"]}):
        ids = {row["task_id"] for row in audit["tasks"] if row["stratum"] == stratum}
        values = {}
        for condition in manifest["conditions"]:
            valid = [
                row
                for row in primary
                if row["task_id"] in ids and row["condition"] == condition and row["status"] == "valid"
            ]
            values[condition] = {
                "valid": len(valid),
                "success": sum(row["metrics"]["official_final_reward"] == 1 for row in valid),
            }
        strata[stratum] = values
    result["write_family_sensitivity"] = strata
    result["user_entity_cluster_bootstrap_sensitivity"] = paired_bootstrap(
        primary, clusters={row["task_id"]: row["user_entity_cluster"] for row in audit["tasks"]}
    )
    result.pop("exclude_near_duplicate_task38_sensitivity", None)
    result["official_split"] = "train; stratified supplementary sample, not an official test score"
    result["interpretation"] = "Separate replication; do not pool with the test-split primary study"
    write_json(output_dir / "summary.json", result)
    write_json(output_dir / "per_attempt_metrics.json", rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.input, args.output)
    print({key: result[key] for key in ["study_id", "complete", "finished_primary_slots", "planned_primary_slots"]})


if __name__ == "__main__":
    main()
