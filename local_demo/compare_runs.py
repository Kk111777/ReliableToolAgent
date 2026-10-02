"""Compare frozen Raw Error and Structured Error V1 pilot artifacts.

This module only reads artifacts and produces paired summaries. It does not run
an agent and does not alter recovery behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .pilot import ARTIFACTS, PILOT_CONDITIONS, summarize_reports


COMPARISON_DIR = ARTIFACTS / "comparison"


def artifact_path(condition: str, task_id: str, repeat_index: int) -> Path:
    return ARTIFACTS / condition / f"r{repeat_index:02d}" / f"{task_id}.json"


def load_condition_reports(condition: str) -> list[dict[str, Any]]:
    """Load only per-task reports, never the condition summary."""

    paths = sorted((ARTIFACTS / condition).glob("r*/P*.json"))
    return [json.loads(path.read_text()) for path in paths]


def _metric_view(report: dict[str, Any]) -> dict[str, Any]:
    metrics = report["metrics"]
    return {
        "task_success": metrics.get("task_success"),
        "terminal_violation": metrics.get("terminal_violation"),
        "terminal_violation_count": metrics.get("terminal_violation_count", 0),
        "duplicate_failed_calls": metrics.get("duplicate_failed_calls", 0),
        "unnecessary_tool_call_count": metrics.get("unnecessary_tool_call_count", 0),
        "targets_correctly_resolved": metrics.get("targets_correctly_resolved", 0),
        "targets_total": metrics.get("targets_total", 0),
        "target_completion_rate": metrics.get("target_completion_rate"),
        "tool_calls": metrics.get("tool_calls", 0),
        "model_calls": metrics.get("model_calls", 0),
        "input_tokens": metrics.get("input_tokens"),
        "output_tokens": metrics.get("output_tokens"),
        "total_tokens": metrics.get("total_tokens"),
        "latency": metrics.get("latency"),
        "stop_reason": metrics.get("stop_reason"),
    }


def pair_reports(
    raw_reports: list[dict[str, Any]], structured_reports: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_by_key = {(report["task_id"], report["repeat_index"]): report for report in raw_reports}
    structured_by_key = {(report["task_id"], report["repeat_index"]): report for report in structured_reports}
    common_keys = sorted(raw_by_key.keys())
    paired = []
    missing = []
    for key in common_keys:
        if key not in structured_by_key:
            missing.append({"condition": "structured-error", "task_id": key[0], "repeat_index": key[1]})
            continue
        raw = raw_by_key[key]
        structured = structured_by_key[key]
        paired.append(
            {
                "task_id": key[0],
                "repeat_index": key[1],
                "category": raw["category"],
                "raw_error": _metric_view(raw),
                "structured_error_v1": _metric_view(structured),
            }
        )
    for key in sorted(structured_by_key.keys() - raw_by_key.keys()):
        missing.append({"condition": "raw-error", "task_id": key[0], "repeat_index": key[1]})
    return paired, missing


def _numeric_delta(paired: list[dict[str, Any]], field: str) -> dict[str, Any]:
    raw_values = [item["raw_error"].get(field) for item in paired if item["raw_error"].get(field) is not None]
    structured_values = [
        item["structured_error_v1"].get(field) for item in paired if item["structured_error_v1"].get(field) is not None
    ]
    if not raw_values or not structured_values:
        return {"raw_average": None, "structured_average": None, "structured_minus_raw": None}
    raw_average = sum(raw_values) / len(raw_values)
    structured_average = sum(structured_values) / len(structured_values)
    return {
        "raw_average": round(raw_average, 4),
        "structured_average": round(structured_average, 4),
        "structured_minus_raw": round(structured_average - raw_average, 4),
    }


def build_comparison() -> dict[str, Any]:
    raw_reports = load_condition_reports("raw-error")
    structured_reports = load_condition_reports("structured-error")
    paired, missing = pair_reports(raw_reports, structured_reports)
    summary = {
        "conditions": {
            "raw-error": summarize_reports(raw_reports),
            "structured-error": summarize_reports(structured_reports),
        },
        "paired_run_count": len(paired),
        "missing_pairs": missing,
        "paired_metric_deltas": {
            field: _numeric_delta(paired, field)
            for field in (
                "tool_calls",
                "model_calls",
                "duplicate_failed_calls",
                "unnecessary_tool_call_count",
                "targets_correctly_resolved",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "latency",
            )
        },
    }
    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)
    (COMPARISON_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    with (COMPARISON_DIR / "paired_runs.jsonl").open("w") as handle:
        for item in paired:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    fieldnames = [
        "task_id",
        "repeat_index",
        "category",
        "raw_task_success",
        "structured_task_success",
        "raw_terminal_violation_count",
        "structured_terminal_violation_count",
        "raw_duplicate_failed_calls",
        "structured_duplicate_failed_calls",
        "raw_unnecessary_tool_call_count",
        "structured_unnecessary_tool_call_count",
        "raw_targets_correctly_resolved",
        "structured_targets_correctly_resolved",
        "raw_tool_calls",
        "structured_tool_calls",
        "raw_model_calls",
        "structured_model_calls",
        "raw_total_tokens",
        "structured_total_tokens",
        "raw_latency",
        "structured_latency",
    ]
    with (COMPARISON_DIR / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in paired:
            raw = item["raw_error"]
            structured = item["structured_error_v1"]
            writer.writerow(
                {
                    "task_id": item["task_id"],
                    "repeat_index": item["repeat_index"],
                    "category": item["category"],
                    "raw_task_success": raw["task_success"],
                    "structured_task_success": structured["task_success"],
                    "raw_terminal_violation_count": raw["terminal_violation_count"],
                    "structured_terminal_violation_count": structured["terminal_violation_count"],
                    "raw_duplicate_failed_calls": raw["duplicate_failed_calls"],
                    "structured_duplicate_failed_calls": structured["duplicate_failed_calls"],
                    "raw_unnecessary_tool_call_count": raw["unnecessary_tool_call_count"],
                    "structured_unnecessary_tool_call_count": structured["unnecessary_tool_call_count"],
                    "raw_targets_correctly_resolved": raw["targets_correctly_resolved"],
                    "structured_targets_correctly_resolved": structured["targets_correctly_resolved"],
                    "raw_tool_calls": raw["tool_calls"],
                    "structured_tool_calls": structured["tool_calls"],
                    "raw_model_calls": raw["model_calls"],
                    "structured_model_calls": structured["model_calls"],
                    "raw_total_tokens": raw["total_tokens"],
                    "structured_total_tokens": structured["total_tokens"],
                    "raw_latency": raw["latency"],
                    "structured_latency": structured["latency"],
                }
            )
    (COMPARISON_DIR / "report.md").write_text(_markdown_report(summary, paired), encoding="utf-8")
    return summary


def _markdown_report(summary: dict[str, Any], paired: list[dict[str, Any]]) -> str:
    lines = [
        "# Raw Error vs Structured Error V1",
        "",
        "This report is a mechanical comparison of frozen artifacts. It does not apply a recovery policy or interpret effectiveness.",
        "Post-terminal unnecessary call rate is unnecessary calls divided by observed terminal targets and may exceed 1.0; task rate is reported separately.",
        "",
        f"Paired runs: {summary['paired_run_count']}",
        "",
        "## Condition summaries",
        "",
        "| Condition | Category | Runs | Task success | Timely stop | Post-terminal unnecessary call rate | Target completion | Premature termination |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, condition_summary in summary["conditions"].items():
        for category, metrics in condition_summary["categories"].items():
            lines.append(
                f"| {condition} | {category} | {metrics['task_runs']} | {metrics['task_success_rate']} | "
                f"{metrics['timely_stop_rate']} | {metrics['post_terminal_unnecessary_tool_call_rate']} | "
                f"{metrics['target_completion_rate']} | {metrics['premature_termination_rate']} |"
            )
    lines.extend(
        [
            "",
            "## Paired runs",
            "",
            "| Task | Repeat | Category | Raw success | Structured success | Raw terminal violations | Structured terminal violations | Raw unnecessary | Structured unnecessary |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in paired:
        raw = item["raw_error"]
        structured = item["structured_error_v1"]
        lines.append(
            f"| {item['task_id']} | {item['repeat_index']} | {item['category']} | {raw['task_success']} | "
            f"{structured['task_success']} | {raw['terminal_violation_count']} | "
            f"{structured['terminal_violation_count']} | {raw['unnecessary_tool_call_count']} | "
            f"{structured['unnecessary_tool_call_count']} |"
        )
    return "\n".join(lines) + "\n"


def _print_pair(task_id: str, repeat_index: int) -> None:
    reports = []
    for condition in PILOT_CONDITIONS:
        path = artifact_path(condition, task_id, repeat_index)
        if not path.exists():
            raise SystemExit(f"Missing artifact: {path}")
        reports.append(json.loads(path.read_text()))
    for report in reports:
        print(f"=== {report['condition']} {report['task_id']} repeat {report['repeat_index']} ===")
        print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
        print("trajectory:")
        for record in report["trajectory"]:
            print(
                json.dumps(
                    {
                        "step": record.get("step_index"),
                        "call_index": record.get("call_index"),
                        "tool": record.get("tool_name"),
                        "arguments": record.get("arguments"),
                        "status": record.get("status"),
                        "error_type": record.get("error_type"),
                        "message": record.get("message"),
                        "error": record.get("error"),
                    },
                    ensure_ascii=False,
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", choices=[f"P{i:02d}" for i in range(1, 17)])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--build-summary", action="store_true")
    args = parser.parse_args()
    if args.build_summary:
        summary = build_comparison()
        print(json.dumps({"written_to": str(COMPARISON_DIR), "paired_run_count": summary["paired_run_count"]}))
        return
    if not args.task_id:
        parser.error("choose --task-id TASK_ID or --build-summary")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    _print_pair(args.task_id, args.repeat)


if __name__ == "__main__":
    main()
