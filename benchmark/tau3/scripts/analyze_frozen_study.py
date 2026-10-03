"""Recompute study metrics without credentials, network calls, or tau2 imports."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from frozen_study import (
    analyze_simulation,
    digest,
    file_sha,
    paired_bootstrap,
    read_json,
    read_jsonl,
    schedule,
    validate_manifest,
    write_json,
)


def aggregate(manifest: dict, rows: list[dict]) -> dict:
    primary = [row for row in rows if row["phase"] == "formal" and row["attempt"] == 0]
    expected = len(schedule(manifest, "formal"))
    expected_per_condition = expected // 2
    conditions = {}
    for condition in manifest["conditions"]:
        attempts = [row for row in primary if row["condition"] == condition]
        valid = [row for row in attempts if row["status"] == "valid"]
        success = sum(row["metrics"]["official_final_reward"] == 1 for row in valid)
        restored = []
        for slot in schedule(manifest, "formal"):
            if slot.condition != condition:
                continue
            candidates = sorted(
                [r for r in rows if r["slot_id"] == slot.key and r["status"] == "valid"], key=lambda r: r["attempt"]
            )
            if candidates:
                restored.append(candidates[0])
        conditions[condition] = {
            "planned_slots": expected_per_condition,
            "first_attempts_finished": len(attempts),
            "first_attempt_status_counts": dict(Counter(r["status"] for r in attempts)),
            "first_attempt_valid": len(valid),
            "first_attempt_success": success,
            "success_over_valid_first_attempts": success / len(valid) if valid else None,
            "success_over_all_planned_slots": success / expected_per_condition,
            "restored_valid_secondary": len(restored),
            "restored_success_secondary": sum(r["metrics"]["official_final_reward"] == 1 for r in restored),
            "confirmation_terminal_before_write_candidates": sum(
                r["metrics"]["confirmation_terminal_before_write_candidate"] for r in valid
            ),
            "terminal_before_reference_write_candidates": sum(
                r["metrics"]["terminal_before_reference_write_candidate"] for r in valid
            ),
            "explicit_tool_errors": sum(r["metrics"]["explicit_tool_errors"] for r in valid),
            "tasks_with_cross_turn_exact_repeats": sorted(
                {r["task_id"] for r in valid if r["metrics"]["cross_turn_exact_repeats"]}
            ),
        }
    pair_valid = 0
    by_key = {r["slot_id"]: r for r in primary}
    for task in manifest["task_ids"]:
        for trial in range(manifest["trials"]):
            pair = [by_key.get(f"formal-t{task}-{condition}-r{trial}") for condition in manifest["conditions"]]
            pair_valid += all(r and r["status"] == "valid" for r in pair)
    planned_pairs = expected // 2
    invalid = sum(r["status"] != "valid" for r in primary)
    completeness = pair_valid / planned_pairs
    infra_fraction = invalid / len(primary) if primary else None
    source_audit = read_json(Path(__file__).resolve().parents[1] / "studies/retail-holdout-v1/task_audit.json")
    families = {}
    for family in sorted({item["write_family"] for item in source_audit["tasks"]}):
        ids = {item["task_id"] for item in source_audit["tasks"] if item["write_family"] == family}
        family_rows = [r for r in primary if r["task_id"] in ids]
        family_success = {}
        for condition in manifest["conditions"]:
            valid = [r for r in family_rows if r["condition"] == condition and r["status"] == "valid"]
            family_success[condition] = {
                "valid": len(valid),
                "success": sum(r["metrics"]["official_final_reward"] == 1 for r in valid),
            }
        families[family] = family_success
    return {
        "study_id": manifest["study_id"],
        "manifest_sha256": digest(manifest),
        "complete": len(primary) == expected,
        "planned_primary_slots": expected,
        "finished_primary_slots": len(primary),
        "valid_primary_pairs": pair_valid,
        "planned_pairs": planned_pairs,
        "pair_completeness": completeness,
        "infrastructure_or_timeout_fraction": infra_fraction,
        "engineering_gate_pass": bool(
            len(primary) == expected and completeness >= 0.9 and infra_fraction is not None and infra_fraction <= 0.1
        ),
        "conditions": conditions,
        "paired_reward_bootstrap": paired_bootstrap(primary),
        "user_entity_cluster_bootstrap_sensitivity": paired_bootstrap(
            primary, clusters={item["task_id"]: item["user_entity_cluster"] for item in source_audit["tasks"]}
        ),
        "exclude_near_duplicate_task38_sensitivity": paired_bootstrap(
            [row for row in primary if row["task_id"] != "38"]
        ),
        "write_family_sensitivity": families,
        "billing_all_phases": {
            "attempts": len(rows),
            "known_response_list_price_rmb": sum(r["billing"]["known_list_price_rmb"] for r in rows),
            "conservative_budget_debit_rmb": sum(r["billing"]["budget_debit_rmb"] for r in rows),
            "unknown_usage_calls": sum(r["billing"]["usage_unknown_calls"] for r in rows),
            "provider_invoice_verified": False,
        },
        "interpretation": "Simulator-condition diagnostic; not an Agent improvement or general tool benchmark",
    }


def analyze(output: Path, destination: Path) -> dict:
    manifest = read_json(output / "manifest.json")
    validate_manifest(manifest)
    rows = read_jsonl(output / "attempts.jsonl")
    for row in rows:
        outcome = output / row["outcome_path"]
        if file_sha(outcome) != row["outcome_sha256"]:
            raise ValueError("outcome digest mismatch")
        for name, expected in row["artifact_sha256"].items():
            if file_sha(outcome.parent / name) != expected:
                raise ValueError("attempt artifact digest mismatch")
        simulation = outcome.parent / "simulation.json"
        if simulation.exists() and analyze_simulation(read_json(simulation)) != row["metrics"]:
            raise ValueError("saved metrics disagree with raw trajectory")
    report = aggregate(manifest, rows)
    write_json(destination / "per_attempt_metrics.json", rows)
    write_json(destination / "summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(analyze(args.input, args.output))


if __name__ == "__main__":
    main()
