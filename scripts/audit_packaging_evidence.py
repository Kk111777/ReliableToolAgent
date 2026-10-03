"""Read existing evidence without model calls or changes to experimental files.

Default mode checks public snapshots. --local also verifies them against the
retained raw trajectories and the already existing evaluator-v2 rescore.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
SOURCES: dict[str, str] = {}


def read(relative: str):
    path = ROOT / relative
    payload = path.read_bytes()
    SOURCES[relative] = hashlib.sha256(payload).hexdigest()
    return json.loads(payload)


def toy_summary(directory: str) -> dict:
    reports = [read(str(p.relative_to(ROOT))) for p in sorted((ROOT / directory).glob("r*/P*.json"))]
    metrics = [r["metrics"] for r in reports]
    if not metrics:
        raise ValueError(f"No retained reports: {directory}")
    return {
        "runs": len(metrics),
        "task_success_rate": round(mean(m["task_success"] for m in metrics), 4),
        "timely_stop_rate": round(mean(not m["terminal_violation"] for m in metrics), 4),
        "terminal_violation_count": sum(m["terminal_violation_count"] for m in metrics),
        "duplicate_failure_count": sum(m["duplicate_failed_calls"] for m in metrics),
        "avg_tool_calls": round(mean(m["tool_calls"] for m in metrics), 4),
        "avg_model_calls": round(mean(m["model_calls"] for m in metrics), 4),
    }


def check_equal(actual, expected, label: str):
    if actual != expected:
        raise ValueError(f"Evidence mismatch in {label}: {actual!r} != {expected!r}")


def verify_local(snapshot: dict):
    for name, expected in snapshot["toy_original"].items():
        actual = toy_summary(f"artifacts/qwen35-flash-ablation/{name}")
        check_equal(actual, expected, f"original toy/{name}")
        corrected = toy_summary(f"artifacts/rescored/ablation/{name}")
        public = read("reports/evaluator-v2-ablation-summary.json")["conditions"][name]
        for local_key, public_key in (
            ("task_success_rate", "task_success_rate"),
            ("timely_stop_rate", "timely_stop_rate"),
            ("terminal_violation_count", "terminal_violation_call_total"),
            ("avg_tool_calls", "average_tool_calls"),
        ):
            check_equal(corrected[local_key], public[public_key], f"v2/{name}/{public_key}")
    originals = ROOT / "artifacts/qwen35-flash-ablation"
    changed_metrics = {}
    for path in sorted(originals.glob("E*/r*/P*.json")):
        relative = str(path.relative_to(originals))
        original = read(str(path.relative_to(ROOT)))
        corrected = read(f"artifacts/rescored/ablation/{relative}")
        check_equal(original["run"], corrected["run"], f"unchanged trajectory/{relative}")
        check_equal(original["output"], corrected["output"], f"unchanged answer/{relative}")
        check_equal(
            corrected["metrics"].keys() - original["metrics"].keys(),
            {"correct_continue_behavior"},
            f"existing v2 added field/{relative}",
        )
        check_equal(
            original["metrics"].keys() - corrected["metrics"].keys(), set(), f"no removed metric field/{relative}"
        )
        check_equal(corrected["metrics"]["correct_continue_behavior"], False, f"v2 single-terminal field/{relative}")
        delta = {
            k: [original["metrics"].get(k), corrected["metrics"].get(k)]
            for k in original["metrics"]
            if original["metrics"].get(k) != corrected["metrics"].get(k)
        }
        if delta:
            changed_metrics[relative] = delta
    check_equal(
        changed_metrics,
        {
            "E2_raw_no_retry/r01/P04.json": {
                "task_success": [False, True],
                "business_success": [False, True],
                "premature_termination": [True, False],
            }
        },
        "only existing v2 metric correction",
    )
    first = read("artifacts/qwen35-flash-ablation/E2_raw_no_retry/r01/P04.json")
    second = read("artifacts/rescored/ablation/E2_raw_no_retry/r01/P04.json")
    check_equal(first["run"], second["run"], "E2/P04 unchanged trajectory")
    check_equal(first["output"], second["output"], "E2/P04 unchanged answer")
    check_equal(first["metrics"]["task_success"], False, "E2/P04 original scoring")
    check_equal(second["metrics"]["task_success"], True, "E2/P04 existing v2 scoring")
    for name, expected in snapshot["toy_guard"].items():
        reports = [
            read(str(p.relative_to(ROOT)))
            for p in sorted((ROOT / "artifacts/qwen35-flash-guard-v1" / name).glob("r*/P*.json"))
        ]
        metrics = [r["metrics"] for r in reports]
        actual = {
            "runs": len(metrics),
            "task_success_rate": mean(m["task_success"] for m in metrics),
            "terminal_violation_count": sum(m["terminal_violation_count"] for m in metrics),
            "unnecessary_tool_call_count": sum(m["unnecessary_tool_call_count"] for m in metrics),
            "duplicate_executed_failure_count": sum(m["duplicate_executed_failure_count"] for m in metrics),
            "blocked_call_count": sum(m["blocked_tool_calls"] for m in metrics),
            "executed_tool_calls": sum(m["executed_tool_calls"] for m in metrics),
        }
        check_equal(actual, expected, f"toy guard/{name}")

    # Only pure analysis helpers are called. Main functions and launchers are never run.
    sys.path.insert(0, str(ROOT / "benchmark/tau3/scripts"))
    from analyze_clean_u2_failure_audit import completion_metrics
    from analyze_user_simulator_ablation import counts

    saved = read("tau2-bench-baseline/data/analysis/retail-observability/clean-u2-20x1/summary.json")
    tool_classes = saved["tool_classification"]
    for condition in ("U0", "U2"):
        data = read(
            f"tau2-bench-baseline/data/simulations/tau3-retail-user-simulator-ablation-{condition.lower()}-0-4/results.json"
        )
        rows = [
            counts(s, tool_classes)
            for s in data["simulations"]
            if str(s["task_id"]) in snapshot["simulator"]["task_ids"]
            and s["termination_reason"] != "infrastructure_error"
        ]
        actual = {
            "valid_simulations": len(rows),
            "premature_user_termination_before_write": sum(r["premature_user_termination_before_write"] for r in rows),
            "expected_write_executed": sum(r["expected_write_observed"] for r in rows),
            "db_reward_one": sum(r["db_reward"] == 1 for r in rows),
            "final_reward_one": sum(r["final_reward"] == 1 for r in rows),
        }
        expected = {k: snapshot["simulator"]["conditions"][condition][k] for k in actual}
        check_equal(actual, expected, f"raw simulator/{condition}")

    raw = read("tau2-bench-baseline/data/simulations/tau3-retail-clean-u2-20x1/results.json")
    valid = [s for s in raw["simulations"] if s["termination_reason"] != "infrastructure_error"]
    metrics = [completion_metrics(s, tool_classes) for s in valid]
    actual = {
        "attempted_simulations": len(raw["simulations"]),
        "valid_simulations": len(valid),
        "infrastructure_invalid": len(raw["simulations"]) - len(valid),
        "simulation_timeouts": sum(s["termination_reason"] == "timeout" for s in raw["simulations"]),
        "final_reward_one": sum(r["final_reward"] == 1 for r in metrics),
        "db_reward_one": sum(r["db_reward"] == 1 for r in metrics),
        "nl_reward_one": sum(r["nl_reward"] == 1 for r in metrics),
        "tasks_with_expected_write": sum(r["expected_write_exists"] for r in metrics),
        "successful_expected_write": sum(r["expected_write_observed"] for r in metrics),
        "cross_turn_exact_repeat_calls": sum(r["cross_turn_exact_repeat_calls"] for r in metrics),
        "same_message_duplicate_tasks": sum(r["same_message_duplicate_calls"] > 0 for r in metrics),
        "same_message_duplicate_calls": sum(r["same_message_duplicate_calls"] for r in metrics),
        "explicit_tool_failure_tasks": sum(r["tool_failure_count"] > 0 for r in metrics),
        "valid_reward_zero_tasks": sum(r["final_reward"] == 0 for r in metrics),
    }
    check_equal(actual, snapshot["clean_audit"]["results"], "raw clean audit")
    check_equal(sum(r["tool_failure_count"] for r in metrics), 3, "explicit failure calls")
    residual = [r for r in metrics if r["final_reward"] == 0]
    check_equal([r["task_id"] for r in residual], ["5"], "T05 residual identity")
    check_equal(residual[0]["terminal_type"], "TRANSFER", "T05 terminal signal")
    check_equal(residual[0]["tool_failure_count"], 0, "T05 no failed tool calls")


def build_snapshot():
    toy = read("artifacts/qwen35-flash-ablation/summary.json")
    guard = read("artifacts/qwen35-flash-guard-v1/summary.json")
    snapshot = {
        "scope": "read_only_packaging_audit_of_existing_experiments",
        "checked_on": "2026-10-03",
        "toy_original": {
            name: {
                k: row[k]
                for k in (
                    "runs",
                    "task_success_rate",
                    "timely_stop_rate",
                    "terminal_violation_count",
                    "duplicate_failure_count",
                    "avg_tool_calls",
                    "avg_model_calls",
                )
            }
            for name, row in toy["conditions"].items()
        },
        "toy_guard": {
            name: {
                k: row[k]
                for k in (
                    "runs",
                    "task_success_rate",
                    "terminal_violation_count",
                    "unnecessary_tool_call_count",
                    "duplicate_executed_failure_count",
                    "blocked_call_count",
                    "executed_tool_calls",
                )
            }
            for name, row in guard["conditions"].items()
        },
        "simulator": read("benchmark/tau3/results/user_simulator_stability_summary.json"),
        "clean_audit": read("benchmark/tau3/results/clean_audit_summary.json"),
        "scoring_note": {
            "condition": "E2_raw_no_retry",
            "original_success": "23/24",
            "existing_evaluator_v2_success": "24/24",
            "affected_trial": "P04/r01",
            "reason": "Correct missing-order answer used the Chinese wording 无法找到; the existing v2 scorer accepts this wording.",
            "trajectory_and_answer_unchanged": True,
            "existing_v2_schema_addition": "All 96 single-terminal reports also add correct_continue_behavior=false; existing metric values otherwise differ only in P04/r01 success/business/premature labels.",
        },
    }
    verify_local(snapshot)
    snapshot["verification"] = {"raw_cross_check_passed": True, "source_sha256": dict(sorted(SOURCES.items()))}
    return snapshot


def verify_public(snapshot: dict):
    check_equal(
        snapshot["simulator"], read("benchmark/tau3/results/user_simulator_stability_summary.json"), "public simulator"
    )
    check_equal(snapshot["clean_audit"], read("benchmark/tau3/results/clean_audit_summary.json"), "public clean audit")
    check_equal(snapshot["clean_audit"], read("reports/tau3-clean-audit-summary.json"), "duplicate clean snapshot")
    rescored = read("reports/evaluator-v2-ablation-summary.json")["conditions"]
    for name, original in snapshot["toy_original"].items():
        expected_success = 1.0 if name == snapshot["scoring_note"]["condition"] else original["task_success_rate"]
        check_equal(rescored[name]["task_success_rate"], expected_success, f"public v2 success/{name}")
        check_equal(rescored[name]["timely_stop_rate"], original["timely_stop_rate"], f"public stopping/{name}")
    provenance = read("assets/simulator_ablation.provenance.json")
    for label in ("source", "canonical", "generator", "figure"):
        key = "canonical_snapshot" if label == "canonical" else label
        check_equal(
            hashlib.sha256((ROOT / provenance[key]).read_bytes()).hexdigest(),
            provenance[f"{label}_sha256"],
            f"figure provenance/{label}",
        )
    rows = snapshot["simulator"]["conditions"]
    check_equal(
        provenance["denominators"], {c: row["valid_simulations"] for c, row in rows.items()}, "figure denominators"
    )
    for field, plotted in provenance["plotted_counts"].items():
        check_equal(plotted, {c: row[field] for c, row in rows.items()}, f"figure counts/{field}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Cross-check retained raw files; never writes them.")
    parser.add_argument("--write-snapshot", action="store_true", help="Create only the presentation snapshot.")
    args = parser.parse_args()
    destination = ROOT / "reports/packaging_evidence_20261003.json"
    if args.write_snapshot:
        snapshot = build_snapshot()
        destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    else:
        snapshot = read(str(destination.relative_to(ROOT)))
        verify_public(snapshot)
        if args.local:
            verify_local(snapshot)
            for path, digest in snapshot["verification"]["source_sha256"].items():
                check_equal(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest, path)
    print(
        json.dumps(
            {
                "passed": True,
                "scope": "retained_raw_evidence" if args.local or args.write_snapshot else "public_snapshots",
                "experimental_files_written": 0,
                "snapshot": str(destination.relative_to(ROOT)),
            }
        )
    )


if __name__ == "__main__":
    main()
