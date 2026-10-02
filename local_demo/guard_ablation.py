"""Run the G0/G1 Duplicate Failure Guard V1 experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smolagents import ToolCallingAgent

from .ablation import (
    ABLATION_CLIENT_TIMEOUT,
    ABLATION_MAX_RETRIES,
    ABLATION_MAX_TOKENS,
    ABLATION_MODEL_ID,
    ABLATION_REASONING_EFFORT,
    DEFAULT_SCHEDULE,
    DEFAULT_SCHEDULE_SEED,
    _tool_schema_digest,
    build_schedule,
)
from .pilot import PILOT_MAX_STEPS, PILOT_MAX_TOOL_THREADS, evaluate_pilot, summarize_reports
from .pilot_tasks import PILOT_TASKS, get_pilot_task
from .run import ARTIFACTS, InventoryTool, OrderDetailTool, build_api_model


GUARD_ROOT = ARTIFACTS / "qwen35-flash-guard-v1"
GUARD_TASKS = tuple(task.task_id for task in PILOT_TASKS[:8])
GUARD_CONDITIONS: dict[str, dict[str, Any]] = {
    "G0_E3_no_guard": {"duplicate_guard": False},
    "G1_E3_duplicate_guard": {"duplicate_guard": True},
}
GUARD_MODEL_CONFIG = {
    "model_id": ABLATION_MODEL_ID,
    "temperature": 0.0,
    "max_tokens": ABLATION_MAX_TOKENS,
    "reasoning_effort": ABLATION_REASONING_EFFORT,
    "client_timeout": ABLATION_CLIENT_TIMEOUT,
    "client_max_retries": ABLATION_MAX_RETRIES,
}


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_metadata() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None}
    return {"revision": revision, "dirty": dirty}


def run_guard_case(
    task_id: str,
    condition: str,
    repeat_index: int,
    *,
    schedule: str = DEFAULT_SCHEDULE,
    schedule_seed: int = DEFAULT_SCHEDULE_SEED,
    schedule_index: int | None = None,
) -> dict[str, Any]:
    if condition not in GUARD_CONDITIONS:
        raise ValueError(f"Unknown guard condition {condition!r}; choose one of {tuple(GUARD_CONDITIONS)}")
    task = get_pilot_task(task_id)
    model = build_api_model(
        model_id=ABLATION_MODEL_ID,
        temperature=0.0,
        reasoning_effort=ABLATION_REASONING_EFFORT,
    )
    prompt = f"{task.query} Use only the provided tools and summarize the results."
    agent = ToolCallingAgent(
        tools=[OrderDetailTool(), InventoryTool(task_id=task.task_id)],
        model=model,
        max_steps=PILOT_MAX_STEPS,
        max_tool_threads=PILOT_MAX_TOOL_THREADS,
        verbosity_level=0,
        structured_error_feedback=True,
        retry_framing=False,
        duplicate_guard=GUARD_CONDITIONS[condition]["duplicate_guard"],
    )
    result = agent.run(prompt, return_full_result=True)
    evaluated = evaluate_pilot(task, result)
    return {
        "experiment": "duplicate_failure_guard_v1",
        "condition": condition,
        "guard_enabled": GUARD_CONDITIONS[condition]["duplicate_guard"],
        "error_mode": "structured",
        "retry_framing": False,
        "model_id": model.model_id,
        "task_id": task.task_id,
        "repeat_index": repeat_index,
        "schedule": schedule,
        "schedule_seed": schedule_seed,
        "schedule_index": schedule_index,
        "category": task.category,
        "query": task.query,
        "prompt": prompt,
        "target_order_ids": task.target_order_ids,
        "existing_order_ids": task.existing_order_ids,
        "missing_order_ids": task.missing_order_ids,
        "agent_config": {
            "max_steps": PILOT_MAX_STEPS,
            "max_tool_threads": PILOT_MAX_TOOL_THREADS,
            "structured_error_feedback": True,
            "retry_framing": False,
            "duplicate_guard": GUARD_CONDITIONS[condition]["duplicate_guard"],
        },
        "model_config": GUARD_MODEL_CONFIG,
        "system_prompt_digest": _sha256_json(agent.system_prompt),
        "tool_schema_digest": _tool_schema_digest(agent),
        "scope": "qwen35_flash_duplicate_failure_guard_v1",
        **evaluated,
    }


def write_guard_report(report: dict[str, Any]) -> Path:
    path = GUARD_ROOT / report["condition"] / f"r{report['repeat_index']:02d}" / f"{report['task_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    return path


def _condition_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    categories = summarize_reports(reports)["categories"]
    all_metrics = [report["metrics"] for report in reports]
    return {
        "condition": reports[0]["condition"] if reports else None,
        "runs": len(reports),
        "task_success_rate": round(sum(metric["task_success"] for metric in all_metrics) / len(all_metrics), 4)
        if all_metrics
        else None,
        "terminal_violation_count": sum(metric["terminal_violation_count"] for metric in all_metrics),
        "unnecessary_tool_call_count": sum(metric["unnecessary_tool_call_count"] for metric in all_metrics),
        "duplicate_executed_failure_count": sum(
            metric.get("duplicate_executed_failure_count", 0) for metric in all_metrics
        ),
        "blocked_call_count": sum(metric.get("blocked_tool_calls", 0) for metric in all_metrics),
        "model_tool_call_attempts": sum(
            metric.get("model_tool_call_attempts", metric["tool_calls"]) for metric in all_metrics
        ),
        "executed_tool_calls": sum(metric.get("executed_tool_calls", metric["tool_calls"]) for metric in all_metrics),
        "avg_executed_tool_calls": round(
            sum(metric.get("executed_tool_calls", metric["tool_calls"]) for metric in all_metrics) / len(all_metrics),
            4,
        )
        if all_metrics
        else None,
        "avg_model_calls": round(sum(metric["model_calls"] for metric in all_metrics) / len(all_metrics), 4)
        if all_metrics
        else None,
        "avg_total_tokens": round(sum(metric["total_tokens"] or 0 for metric in all_metrics) / len(all_metrics), 4)
        if all_metrics
        else None,
        "avg_latency": round(sum(metric["latency"] or 0 for metric in all_metrics) / len(all_metrics), 4)
        if all_metrics
        else None,
        "categories": categories,
    }


def run_guard_experiment(
    task_ids: list[str], repeats: int, *, schedule: str = DEFAULT_SCHEDULE, seed: int = DEFAULT_SCHEDULE_SEED
) -> dict[str, Any]:
    reports_by_condition: dict[str, list[dict[str, Any]]] = {condition: [] for condition in GUARD_CONDITIONS}
    schedule_items = build_schedule(
        task_ids,
        list(GUARD_CONDITIONS),
        repeats,
        schedule=schedule,
        seed=seed,
    )
    for schedule_index, (repeat_index, task_id, condition) in enumerate(schedule_items):
        report = run_guard_case(
            task_id,
            condition,
            repeat_index,
            schedule=schedule,
            schedule_seed=seed,
            schedule_index=schedule_index,
        )
        reports_by_condition[condition].append(report)
        write_guard_report(report)

    condition_summaries = {
        condition: _condition_summary(reports) for condition, reports in reports_by_condition.items()
    }
    manifest = {
        "experiment": "duplicate_failure_guard_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_config": GUARD_MODEL_CONFIG,
        "fixed_baseline": {
            "structured_error_feedback": True,
            "retry_framing": False,
            "system_prompt_changed": False,
            "tool_schema_changed": False,
        },
        "conditions": GUARD_CONDITIONS,
        "task_ids": task_ids,
        "repeats": repeats,
        "schedule": schedule,
        "schedule_seed": seed,
        "task_set_digest": _sha256_json(task_ids),
        "git": _git_metadata(),
    }
    GUARD_ROOT.mkdir(parents=True, exist_ok=True)
    (GUARD_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    summary = {
        "experiment": "duplicate_failure_guard_v1",
        "model_config": GUARD_MODEL_CONFIG,
        "conditions": condition_summaries,
        "run_count": sum(len(reports) for reports in reports_by_condition.values()),
    }
    (GUARD_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", action="append", choices=list(GUARD_TASKS))
    parser.add_argument("--all", action="store_true", help="Run P01-P08.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--schedule", choices=("interleaved", "blocked"), default=DEFAULT_SCHEDULE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SCHEDULE_SEED)
    args = parser.parse_args()
    if bool(args.task_id) == args.all:
        parser.error("choose exactly one of --task-id TASK_ID (repeatable) or --all")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    task_ids = args.task_id or list(GUARD_TASKS)
    summary = run_guard_experiment(task_ids, args.repeats, schedule=args.schedule, seed=args.seed)
    print(json.dumps({"completed": True, "summary": summary, "summary_report": str(GUARD_ROOT / "summary.json")}))


if __name__ == "__main__":
    main()
