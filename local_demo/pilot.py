"""Run real-LLM pilot tasks with the unmodified vanilla ToolCallingAgent."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from smolagents import ToolCallingAgent

from .pilot_tasks import PILOT_TASKS, PilotTask, get_pilot_task
from .run import ARTIFACTS, InventoryTool, OrderDetailTool, _trajectory, build_api_model


ROOT = Path(__file__).resolve().parents[1]
PILOT_MAX_STEPS = 8
PILOT_MAX_TOOL_THREADS = 1
PILOT_CONDITIONS = ("raw-error", "structured-error")


def _mentions_not_found(output: Any) -> bool:
    text = str(output).lower()
    return any(
        phrase in text
        for phrase in (
            "ordernotfound",
            "order not found",
            "does not exist",
            "doesn't exist",
            "not found",
            "cannot find",
            "could not find",
            "unable to find",
            "unable to locate",
            "no such order",
            "订单不存在",
            "不存在",
            "找不到",
            "未找到",
            "查不到",
            "无法找到",
        )
    )


def _output_text(output: Any) -> str:
    return str(output).lower()


def _mentions_order_in_output(output: Any, order_id: str) -> bool:
    return order_id.lower() in _output_text(output)


def _mentions_missing_target(output: Any, order_id: str) -> bool:
    return _mentions_order_in_output(output, order_id) and _mentions_not_found(output)


def _mentions_inventory_result(output: Any, order_id: str) -> bool:
    """Require the final answer to report this order's expected stock value."""

    expected_sku = OrderDetailTool.database[order_id]["sku"]
    expected_stock = InventoryTool.database[expected_sku]
    text = _output_text(output)
    return _mentions_order_in_output(text, order_id) and str(expected_stock) in text


def _successful_inventory_results(trajectory: list[dict[str, Any]]) -> set[tuple[str, Any]]:
    return {
        (record["result"]["sku"], record["result"]["stock"])
        for record in trajectory
        if record["tool_name"] == "get_inventory"
        and record["error"] is None
        and isinstance(record["result"], dict)
        and "sku" in record["result"]
        and "stock" in record["result"]
    }


def _order_not_found_records(task: PilotTask, trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in trajectory
        if record.get("error_type") in {"TARGET_NOT_FOUND", "OrderNotFound"}
        and _mentions_any_order(record, task.missing_order_ids)
    ]


def _mentions_any_order(record: dict[str, Any], order_ids: tuple[str, ...]) -> bool:
    arguments = json.dumps(record.get("arguments"), ensure_ascii=False, sort_keys=True, default=str)
    return any(order_id in arguments for order_id in order_ids)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _record_identity(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("step_index"),
        record.get("call_index"),
        record.get("tool_name"),
        record.get("normalized_arguments"),
    )


def _run_token_usage(run: dict[str, Any]) -> dict[str, int] | None:
    usage = run.get("token_usage")
    if isinstance(usage, dict):
        return {
            "input_tokens": usage.get("input_tokens", 0) or 0,
            "output_tokens": usage.get("output_tokens", 0) or 0,
            "total_tokens": usage.get("total_tokens", 0)
            or (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0),
        }
    step_usage = [step.get("token_usage") for step in run.get("steps", []) if step.get("token_usage")]
    if not step_usage:
        return None
    input_tokens = sum(item.get("input_tokens", 0) or 0 for item in step_usage)
    output_tokens = sum(item.get("output_tokens", 0) or 0 for item in step_usage)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def evaluate_pilot(task: PilotTask, result: Any) -> dict[str, Any]:
    """Evaluate business completion and terminal/continuation observations."""

    run = result.dict()
    output = result.output
    trajectory = _trajectory(run)
    business_calls = [record for record in trajectory if record["tool_name"] != "final_answer"]
    errors = [record for record in business_calls if record["error"]]
    executed_calls = [record for record in business_calls if record["status"] in {"success", "error"}]
    blocked_calls = [record for record in business_calls if record["status"] == "blocked"]
    not_found_records = _order_not_found_records(task, trajectory)
    first_not_found_step_by_target = {
        order_id: min(
            (record["step_index"] for record in not_found_records if _mentions_any_order(record, (order_id,))),
            default=None,
        )
        for order_id in task.missing_order_ids
    }
    first_not_found_step = min(
        (step for step in first_not_found_step_by_target.values() if step is not None),
        default=None,
    )
    later_business_calls = [
        record
        for record in business_calls
        if first_not_found_step is not None and record["step_index"] >= first_not_found_step
    ]
    first_not_found_identity_by_target = {
        order_id: next(
            (_record_identity(record) for record in not_found_records if _mentions_any_order(record, (order_id,))),
            None,
        )
        for order_id in task.missing_order_ids
    }
    terminal_violation_records: list[dict[str, Any]] = []
    for record in business_calls:
        record_identity = _record_identity(record)
        if task.category == "single_terminal" and not_found_records:
            first_step = min(item["step_index"] for item in not_found_records)
            first_identity = min(
                (_record_identity(item) for item in not_found_records),
                default=None,
            )
            if record["step_index"] >= first_step and record_identity != first_identity:
                terminal_violation_records.append(record)
                continue
        for order_id, first_step in first_not_found_step_by_target.items():
            if first_step is None or not _mentions_any_order(record, (order_id,)):
                continue
            first_identity = first_not_found_identity_by_target[order_id]
            if record["step_index"] > first_step or (
                record["step_index"] == first_step and record_identity != first_identity
            ):
                terminal_violation_records.append(record)
                break

    failed_keys = Counter(
        (record["tool_name"], record["normalized_arguments"], record["error_type"]) for record in errors
    )
    duplicate_failed_records: list[dict[str, Any]] = []
    seen_failed_keys: Counter[tuple[str, str, str | None]] = Counter()
    for record in errors:
        key = (record["tool_name"], record["normalized_arguments"], record["error_type"])
        seen_failed_keys[key] += 1
        if seen_failed_keys[key] > 1:
            duplicate_failed_records.append(record)
    non_retryable_failed_keys = Counter(
        (record["tool_name"], record["normalized_arguments"], record["error_type"])
        for record in errors
        if record.get("retryable_same_call") is False
    )

    unnecessary_ids = {_record_identity(record) for record in terminal_violation_records + duplicate_failed_records}
    unnecessary_calls = [record for record in business_calls if _record_identity(record) in unnecessary_ids]
    terminal_violation = bool(terminal_violation_records)

    expected_skus = {OrderDetailTool.database[order_id]["sku"] for order_id in task.existing_order_ids}
    successful_inventory = _successful_inventory_results(trajectory)
    successful_order_details = {
        result.get("order_id"): result.get("sku")
        for record in trajectory
        if record["tool_name"] == "get_order_detail" and record["error"] is None and isinstance(record["result"], dict)
        for result in [record["result"]]
    }
    completed_existing_order_ids = [
        order_id
        for order_id in task.existing_order_ids
        if successful_order_details.get(order_id) == OrderDetailTool.database[order_id]["sku"]
        and (
            OrderDetailTool.database[order_id]["sku"],
            InventoryTool.database[OrderDetailTool.database[order_id]["sku"]],
        )
        in successful_inventory
    ]
    existing_orders_completed = set(completed_existing_order_ids) == set(task.existing_order_ids)
    completed_target_ids = set(completed_existing_order_ids)
    completed_target_ids.update(
        order_id for order_id in task.missing_order_ids if first_not_found_step_by_target[order_id] is not None
    )
    target_completion_count = len(completed_target_ids)
    continued_after_error = (
        any(
            record["error"] is None
            and (
                record["result"].get("order_id") in task.existing_order_ids
                or record["result"].get("sku") in expected_skus
            )
            for record in later_business_calls
            if isinstance(record["result"], dict)
        )
        if task.category == "multi_continue"
        else None
    )

    if task.category == "single_terminal":
        business_success = bool(
            run["state"] == "success"
            and not_found_records
            and all(_mentions_missing_target(output, order_id) for order_id in task.missing_order_ids)
        )
        expected_behavior = bool(not_found_records and not terminal_violation)
    else:
        missing_handled = all(
            any(_mentions_any_order(record, (order_id,)) for record in not_found_records)
            for order_id in task.missing_order_ids
        )
        existing_results_reported = all(
            _mentions_inventory_result(output, order_id) for order_id in task.existing_order_ids
        )
        missing_results_reported = all(
            _mentions_missing_target(output, order_id) for order_id in task.missing_order_ids
        )
        business_success = bool(
            run["state"] == "success"
            and existing_orders_completed
            and missing_handled
            and existing_results_reported
            and missing_results_reported
        )
        expected_behavior = bool(existing_orders_completed and continued_after_error is True)
    # A final answer that does not complete the requested business task, or a
    # max-steps stop, is premature regardless of whether valid siblings ran.
    premature_termination = not business_success

    metrics = {
        "task_id": task.task_id,
        "category": task.category,
        "task_success": business_success,
        "business_success": business_success,
        "expected_behavior_observed": expected_behavior,
        "model_calls": sum(1 for step in run["steps"] if step.get("model_output_message")),
        "tool_calls": len(executed_calls),
        "model_tool_call_attempts": len(business_calls),
        "executed_tool_calls": len(executed_calls),
        "blocked_tool_calls": len(blocked_calls),
        "errors_encountered": len(errors),
        "unrecoverable_observation": bool(not_found_records),
        "unrecoverable_observation_count": len(not_found_records),
        "unnecessary_tool_call": bool(unnecessary_calls),
        "unnecessary_tool_call_count": len(unnecessary_calls),
        "failed_tool_calls": len(errors),
        "duplicate_failed_calls": sum(max(count - 1, 0) for count in failed_keys.values()),
        "duplicate_executed_failure_count": sum(max(count - 1, 0) for count in non_retryable_failed_keys.values()),
        "duplicate_failure_rate": _rate(sum(max(count - 1, 0) for count in failed_keys.values()), len(errors)),
        "premature_termination": premature_termination,
        "terminal_violation": terminal_violation,
        "terminal_violation_count": len(terminal_violation_records),
        "terminal_violation_targets": sorted(
            {
                order_id
                for order_id, first_step in first_not_found_step_by_target.items()
                if first_step is not None
                and any(
                    record["step_index"] > first_step and _mentions_any_order(record, (order_id,))
                    for record in business_calls
                )
            }
        ),
        "terminal_target_count": len(
            [order_id for order_id, first_step in first_not_found_step_by_target.items() if first_step is not None]
        ),
        "continued_after_error": continued_after_error,
        "correct_continue_behavior": bool(
            task.category == "multi_continue"
            and continued_after_error is True
            and target_completion_count == len(task.target_order_ids)
        ),
        "existing_orders_completed": completed_existing_order_ids,
        "targets_total": len(task.target_order_ids),
        "targets_correctly_resolved": target_completion_count,
        "target_completion_rate": _rate(target_completion_count, len(task.target_order_ids)),
        "input_tokens": (_run_token_usage(run) or {}).get("input_tokens"),
        "output_tokens": (_run_token_usage(run) or {}).get("output_tokens"),
        "total_tokens": (_run_token_usage(run) or {}).get("total_tokens"),
        "latency": (run.get("timing") or {}).get("duration"),
        "stop_reason": (
            "final_answer" if any(record["tool_name"] == "final_answer" for record in trajectory) else run["state"]
        ),
    }
    return {"output": output, "metrics": metrics, "trajectory": trajectory, "run": run}


def run_pilot(task_id: str, condition: str = "structured-error", repeat_index: int = 1) -> dict[str, Any]:
    """Run one task against the configured real model, without recovery changes."""

    task = get_pilot_task(task_id)
    if condition not in PILOT_CONDITIONS:
        raise ValueError(f"Unknown condition {condition!r}; choose one of {PILOT_CONDITIONS}")
    model = build_api_model()
    prompt = f"{task.query} Use only the provided tools and summarize the results."
    agent = ToolCallingAgent(
        tools=[OrderDetailTool(), InventoryTool(task_id=task.task_id)],
        model=model,
        max_steps=PILOT_MAX_STEPS,
        max_tool_threads=PILOT_MAX_TOOL_THREADS,
        verbosity_level=0,
        structured_error_feedback=condition == "structured-error",
    )
    result = agent.run(prompt, return_full_result=True)
    evaluated = evaluate_pilot(task, result)
    return {
        "task_id": task.task_id,
        "category": task.category,
        "query": task.query,
        "prompt": prompt,
        "target_order_ids": task.target_order_ids,
        "existing_order_ids": task.existing_order_ids,
        "missing_order_ids": task.missing_order_ids,
        "mode": "api",
        "condition": condition,
        "model_id": model.model_id,
        "agent_config": {
            "max_steps": PILOT_MAX_STEPS,
            "max_tool_threads": PILOT_MAX_TOOL_THREADS,
        },
        "scope": "real_llm_terminal_behavior_pilot",
        "repeat_index": repeat_index,
        **evaluated,
    }


def _write_report(report: dict[str, Any]) -> Path:
    destination = ARTIFACTS / report["condition"] / f"r{report['repeat_index']:02d}" / f"{report['task_id']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    return destination


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate pilot observations without mixing the two task categories."""

    summary: dict[str, Any] = {
        "condition": reports[0].get("condition") if reports else None,
        "task_runs": len(reports),
        "categories": {},
    }
    for category, label in (
        ("single_terminal", "single_target_terminal_tasks"),
        ("multi_continue", "multi_target_continue_tasks"),
    ):
        metrics = [report["metrics"] for report in reports if report["category"] == category]
        observed = [metric for metric in metrics if metric["unrecoverable_observation"]]
        unnecessary = [metric for metric in metrics if metric["unnecessary_tool_call"]]
        successful = [metric for metric in metrics if metric["task_success"]]
        premature = [metric for metric in metrics if metric["premature_termination"]]
        terminal_targets = sum(metric["terminal_target_count"] for metric in metrics)
        terminal_violations = sum(len(metric["terminal_violation_targets"]) for metric in metrics)
        terminal_violation_calls = sum(metric["terminal_violation_count"] for metric in metrics)
        failed_tool_calls = sum(metric["failed_tool_calls"] for metric in metrics)
        duplicate_failed_calls = sum(metric["duplicate_failed_calls"] for metric in metrics)
        target_total = sum(metric["targets_total"] for metric in metrics)
        target_completed = sum(metric["targets_correctly_resolved"] for metric in metrics)
        continued = [metric for metric in metrics if metric["continued_after_error"] is True]

        def numeric(key: str) -> list[float]:
            return [metric[key] for metric in metrics if metric.get(key) is not None]

        summary["categories"][label] = {
            "task_runs": len(metrics),
            "task_success_rate": _rate(len(successful), len(metrics)),
            "unrecoverable_observation_rate": _rate(len(observed), len(metrics)),
            "terminal_target_count": terminal_targets,
            "terminal_violation_target_count": terminal_violations,
            "terminal_violation_call_total": terminal_violation_calls,
            "terminal_violation_rate": _rate(terminal_violations, terminal_targets),
            "timely_stop_rate": _rate(terminal_targets - terminal_violations, terminal_targets),
            "post_terminal_unnecessary_tool_call_rate": _rate(
                sum(metric["terminal_violation_count"] for metric in metrics), terminal_targets
            ),
            "post_terminal_unnecessary_task_rate": _rate(len(unnecessary), len(observed)),
            "unnecessary_tool_call_total": sum(metric["unnecessary_tool_call_count"] for metric in metrics),
            "failed_tool_call_total": failed_tool_calls,
            "duplicate_failed_call_total": duplicate_failed_calls,
            "duplicate_executed_failure_total": sum(
                metric.get("duplicate_executed_failure_count", 0) for metric in metrics
            ),
            "model_tool_call_attempt_total": sum(
                metric.get("model_tool_call_attempts", metric["tool_calls"]) for metric in metrics
            ),
            "executed_tool_call_total": sum(
                metric.get("executed_tool_calls", metric["tool_calls"]) for metric in metrics
            ),
            "blocked_tool_call_total": sum(metric.get("blocked_tool_calls", 0) for metric in metrics),
            "duplicate_failure_rate": _rate(duplicate_failed_calls, failed_tool_calls),
            "target_completion_rate": _rate(target_completed, target_total),
            "targets_total": target_total,
            "targets_correctly_resolved": target_completed,
            "premature_termination_rate": _rate(len(premature), len(metrics)),
            "continued_after_error_rate": (
                _rate(len(continued), len(metrics)) if category == "multi_continue" else None
            ),
            "correct_continue_rate": (
                _rate(
                    sum(metric["correct_continue_behavior"] for metric in metrics),
                    len(metrics),
                )
                if category == "multi_continue"
                else None
            ),
            "average_model_calls": _rate(sum(metric["model_calls"] for metric in metrics), len(metrics)),
            "average_tool_calls": _rate(sum(metric["tool_calls"] for metric in metrics), len(metrics)),
            "average_model_tool_call_attempts": _rate(
                sum(metric.get("model_tool_call_attempts", metric["tool_calls"]) for metric in metrics),
                len(metrics),
            ),
            "average_executed_tool_calls": _rate(
                sum(metric.get("executed_tool_calls", metric["tool_calls"]) for metric in metrics),
                len(metrics),
            ),
            "average_blocked_tool_calls": _rate(
                sum(metric.get("blocked_tool_calls", 0) for metric in metrics), len(metrics)
            ),
            "average_input_tokens": _rate(sum(numeric("input_tokens")), len(numeric("input_tokens"))),
            "average_output_tokens": _rate(sum(numeric("output_tokens")), len(numeric("output_tokens"))),
            "average_total_tokens": _rate(sum(numeric("total_tokens")), len(numeric("total_tokens"))),
            "average_latency": _rate(sum(numeric("latency")), len(numeric("latency"))),
        }
        summary["categories"][label]["task_level_bootstrap_ci"] = _task_level_bootstrap_ci(metrics, category)
    return summary


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(fraction * (len(ordered) - 1))))
    return round(ordered[index], 4)


def _task_level_bootstrap_ci(
    metrics: list[dict[str, Any]], category: str, *, samples: int = 2000, seed: int = 20260921
) -> dict[str, Any]:
    """Bootstrap task clusters, averaging repeats before resampling task IDs."""

    by_task: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        by_task.setdefault(metric["task_id"], []).append(metric)
    task_groups = list(by_task.values())
    if not task_groups:
        return {"task_count": 0, "samples": samples, "confidence": 0.95, "metrics": {}}

    def task_mean(group: list[dict[str, Any]], key: str) -> float:
        values = []
        for item in group:
            item_value = item.get(key)
            if item_value is None and key == "model_tool_call_attempts":
                item_value = item.get("tool_calls")
            if item_value is not None:
                values.append(float(item_value))
        return sum(values) / len(values) if values else 0.0

    metric_keys = [
        "task_success",
        "tool_calls",
        "model_tool_call_attempts",
        "blocked_tool_calls",
        "unnecessary_tool_call_count",
        "target_completion_rate",
    ]
    metric_keys.append("timely_stop" if category == "single_terminal" else "correct_continue")

    def value(group: list[dict[str, Any]], key: str) -> float:
        if key == "timely_stop":
            return 1.0 - task_mean(group, "terminal_violation")
        if key == "correct_continue":
            return task_mean(group, "correct_continue_behavior")
        if key == "model_tool_call_attempts":
            return task_mean(group, "model_tool_call_attempts")
        if key == "blocked_tool_calls":
            return task_mean(group, "blocked_tool_calls")
        return task_mean(group, key)

    point = {key: sum(value(group, key) for group in task_groups) / len(task_groups) for key in metric_keys}
    rng = random.Random(seed)
    bootstrap: dict[str, list[float]] = {key: [] for key in metric_keys}
    for _ in range(samples):
        sampled_groups = [task_groups[rng.randrange(len(task_groups))] for _ in task_groups]
        for key in metric_keys:
            bootstrap[key].append(sum(value(group, key) for group in sampled_groups) / len(sampled_groups))

    return {
        "task_count": len(task_groups),
        "samples": samples,
        "confidence": 0.95,
        "metrics": {
            key: {
                "estimate": round(point[key], 4),
                "lower": _percentile(values, 0.025),
                "upper": _percentile(values, 0.975),
            }
            for key, values in bootstrap.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", choices=[task.task_id for task in PILOT_TASKS])
    parser.add_argument("--all", action="store_true", help="Run all pilot tasks; this uses real model calls.")
    parser.add_argument("--repeats", type=int, default=1, help="Repeat each selected task this many times.")
    parser.add_argument("--condition", choices=PILOT_CONDITIONS, default="structured-error")
    args = parser.parse_args()
    if bool(args.task_id) == args.all:
        parser.error("choose exactly one of --task-id TASK_ID (repeatable) or --all")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    task_ids = args.task_id if args.task_id else [task.task_id for task in PILOT_TASKS]
    reports = [
        run_pilot(task_id, condition=args.condition, repeat_index=repeat_index)
        for repeat_index in range(1, args.repeats + 1)
        for task_id in task_ids
    ]
    paths = [_write_report(report) for report in reports]
    summary = summarize_reports(reports)
    summary_path = ARTIFACTS / args.condition / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "completed": True,
                "summary": summary,
                "summary_report": str(summary_path),
                "tasks": [
                    {
                        "task_id": report["task_id"],
                        "repeat_index": report["repeat_index"],
                        **report["metrics"],
                        "report": str(path),
                    }
                    for report, path in zip(reports, paths)
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
