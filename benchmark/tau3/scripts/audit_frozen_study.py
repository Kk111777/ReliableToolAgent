"""Offline public fixture/annotation audit and aggregate verification."""

from __future__ import annotations

import argparse
from pathlib import Path

from frozen_study import analyze_simulation, digest, read_json, validate_manifest


def audit_panel(path: Path) -> dict:
    panel = read_json(path)
    confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    field_checks = 0
    for row in panel["rows"]:
        actual = analyze_simulation(row["compact_simulation"])
        for key, expected in row["inspection_labels"].items():
            if actual[key] != expected:
                raise ValueError(f"annotation disagreement: {row['simulation_id']} {key}")
            field_checks += 1
        candidate = actual["confirmation_terminal_before_write_candidate"]
        label = row["semantic_terminal_confirmation_before_write"]
        confusion["tp" if candidate and label else "fp" if candidate else "fn" if label else "tn"] += 1
    tp, fp, fn = confusion["tp"], confusion["fp"], confusion["fn"]
    return {
        "trajectories": len(panel["rows"]),
        "field_checks": field_checks,
        "confusion": confusion,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "reviewer": panel["reviewer"],
        "panel_sha256": digest(panel),
        "boundary": "purposively selected development traces; same-author inspection, not independent human validation",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study", type=Path, default=Path(__file__).resolve().parents[1] / "studies/retail-holdout-v1"
    )
    args = parser.parse_args()
    manifest = read_json(args.study / "manifest.json")
    validate_manifest(manifest)
    panel = audit_panel(args.study / "measurement_panel.json")
    for fixture in read_json(Path(__file__).resolve().parents[1] / "tests/fixtures/event_fragments.json"):
        actual = analyze_simulation(fixture["simulation"])
        for key, expected in fixture["expected"].items():
            if actual[key] != expected:
                raise ValueError(f"fixture disagreement: {fixture['name']} {key}")
    print({"manifest_sha256": digest(manifest), "measurement_audit": panel, "protocol_fragments": 12})


if __name__ == "__main__":
    main()
