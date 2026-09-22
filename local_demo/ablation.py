"""Run the fixed-model 2x2 error-protocol ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smolagents import ToolCallingAgent

from .pilot import PILOT_MAX_STEPS, PILOT_MAX_TOOL_THREADS, evaluate_pilot
from .pilot_tasks import PILOT_TASKS, get_pilot_task
from .run import ARTIFACTS, InventoryTool, OrderDetailTool, build_api_model


ABLATION_MODEL_ID = "qwen3.5-flash-2026-02-23"
ABLATION_ROOT = ARTIFACTS / "qwen35-flash-ablation"
ABLATION_TEMPERATURE = 0.0
ABLATION_MAX_TOKENS = 512
ABLATION_REASONING_EFFORT = "none"
ABLATION_CLIENT_TIMEOUT = 60.0
ABLATION_MAX_RETRIES = 0

CONDITIONS: dict[str, dict[str, Any]] = {
    "E0_raw_retry": {"error_mode": "raw", "retry_framing": True},
    "E1_structured_retry": {"error_mode": "structured", "retry_framing": True},
    "E2_raw_no_retry": {"error_mode": "raw", "retry_framing": False},
    "E3_structured_no_retry": {"error_mode": "structured", "retry_framing": False},
}

MODEL_CONFIG = {
    "temperature": ABLATION_TEMPERATURE,
    "max_tokens": ABLATION_MAX_TOKENS,
    "reasoning_effort": ABLATION_REASONING_EFFORT,
    "client_timeout": ABLATION_CLIENT_TIMEOUT,
    "client_max_retries": ABLATION_MAX_RETRIES,
}

DEFAULT_SCHEDULE = "interleaved"
DEFAULT_SCHEDULE_SEED = 20260921


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tool_schema_digest(agent: ToolCallingAgent) -> str:
    schemas = [
        {
            "name": tool.name,
            "description": tool.description,
            "inputs": tool.inputs,
            "output_type": tool.output_type,
        }
        for tool in agent.tools.values()
    ]
    return _sha256_json(sorted(schemas, key=lambda schema: schema["name"]))


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


def _task_set_digest(task_ids: list[str]) -> str:
    tasks = [get_pilot_task(task_id).__dict__ for task_id in task_ids]
    return _sha256_json(tasks)


def run_ablation(
    task_id: str,
    condition: str,
    repeat_index: int = 1,
    *,
    schedule: str = DEFAULT_SCHEDULE,
    schedule_seed: int = DEFAULT_SCHEDULE_SEED,
    schedule_index: int | None = None,
) -> dict[str, Any]:
    """Run one condition/task pair with no recovery policy changes."""

    if condition not in CONDITIONS:
        raise ValueError(f"Unknown condition {condition!r}; choose one of {tuple(CONDITIONS)}")
    task = get_pilot_task(task_id)
    condition_config = CONDITIONS[condition]
    model = build_api_model(
        model_id=ABLATION_MODEL_ID,
        temperature=ABLATION_TEMPERATURE,
        reasoning_effort=ABLATION_REASONING_EFFORT,
    )
    prompt = f"{task.query} Use only the provided tools and summarize the results."
    agent = ToolCallingAgent(
        tools=[OrderDetailTool(), InventoryTool(task_id=task.task_id)],
        model=model,
        max_steps=PILOT_MAX_STEPS,
        max_tool_threads=PILOT_MAX_TOOL_THREADS,
        verbosity_level=0,
        structured_error_feedback=condition_config["error_mode"] == "structured",
        retry_framing=condition_config["retry_framing"],
    )
    result = agent.run(prompt, return_full_result=True)
    evaluated = evaluate_pilot(task, result)
    return {
        "condition": condition,
        "error_mode": condition_config["error_mode"],
        "retry_framing": condition_config["retry_framing"],
        "model_id": model.model_id,
        "task_id": task.task_id,
        "repeat": repeat_index,
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
            "structured_error_feedback": condition_config["error_mode"] == "structured",
            "retry_framing": condition_config["retry_framing"],
        },
        "model_config": MODEL_CONFIG,
        "system_prompt_digest": _sha256_json(agent.system_prompt),
        "tool_schema_digest": _tool_schema_digest(agent),
        "scope": "qwen35_flash_error_protocol_ablation",
        **evaluated,
    }


def write_report(report: dict[str, Any]) -> Path:
    destination = ABLATION_ROOT / report["condition"] / f"r{report['repeat_index']:02d}" / f"{report['task_id']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    return destination


def _single_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    from .pilot import summarize_reports

    return summarize_reports(reports)["categories"]["single_target_terminal_tasks"]


def _condition_row(condition: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": condition,
        "runs": summary["task_runs"],
        "task_success_rate": summary["task_success_rate"],
        "timely_stop_rate": summary["timely_stop_rate"],
        "terminal_violation_count": summary["terminal_violation_call_total"],
        "terminal_violation_rate": summary["terminal_violation_rate"],
        "post_terminal_unnecessary_call_count": summary["terminal_violation_call_total"],
        "post_terminal_unnecessary_call_rate": summary["post_terminal_unnecessary_tool_call_rate"],
        "duplicate_failure_count": summary["duplicate_failed_call_total"],
        "avg_tool_calls": summary["average_tool_calls"],
        "avg_model_calls": summary["average_model_calls"],
        "avg_total_tokens": summary["average_total_tokens"],
        "avg_latency": summary["average_latency"],
    }


def _delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float | None]:
    fields = (
        "task_success_rate",
        "timely_stop_rate",
        "terminal_violation_rate",
        "post_terminal_unnecessary_call_count",
        "post_terminal_unnecessary_call_rate",
        "duplicate_failure_count",
        "avg_tool_calls",
        "avg_model_calls",
        "avg_total_tokens",
        "avg_latency",
    )
    return {
        field: (round(right[field] - left[field], 4) if left[field] is not None and right[field] is not None else None)
        for field in fields
    }


def summarize_ablation(reports_by_condition: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = {
        condition: _condition_row(condition, _single_summary(reports))
        for condition, reports in reports_by_condition.items()
    }
    return {
        "model_id": ABLATION_MODEL_ID,
        "model_config": MODEL_CONFIG,
        "conditions": rows,
        "structured_error_effect": {
            "E0_vs_E1": {"E1_minus_E0": _delta(rows["E0_raw_retry"], rows["E1_structured_retry"])},
            "E2_vs_E3": {"E3_minus_E2": _delta(rows["E2_raw_no_retry"], rows["E3_structured_no_retry"])},
        },
        "generic_retry_framing_effect": {
            "E0_vs_E2": {"E2_minus_E0": _delta(rows["E0_raw_retry"], rows["E2_raw_no_retry"])},
            "E1_vs_E3": {"E3_minus_E1": _delta(rows["E1_structured_retry"], rows["E3_structured_no_retry"])},
        },
    }


def build_schedule(
    task_ids: list[str],
    conditions: list[str],
    repeats: int,
    *,
    schedule: str = DEFAULT_SCHEDULE,
    seed: int = DEFAULT_SCHEDULE_SEED,
) -> list[tuple[int, str, str]]:
    """Return deterministic run order, interleaving conditions by task block."""

    if schedule not in {"interleaved", "blocked"}:
        raise ValueError("schedule must be 'interleaved' or 'blocked'")
    items: list[tuple[int, str, str]] = []
    if schedule == "interleaved":
        rng = random.Random(seed)
        for repeat_index in range(1, repeats + 1):
            for task_id in task_ids:
                block_conditions = list(conditions)
                rng.shuffle(block_conditions)
                items.extend((repeat_index, task_id, condition) for condition in block_conditions)
    else:
        for condition in conditions:
            for repeat_index in range(1, repeats + 1):
                items.extend((repeat_index, task_id, condition) for task_id in task_ids)
    return items


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", choices=[task.task_id for task in PILOT_TASKS[:8]])
    parser.add_argument("--all", action="store_true", help="Run P01-P08.")
    parser.add_argument("--condition", action="append", choices=list(CONDITIONS))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--schedule",
        choices=("interleaved", "blocked"),
        default=DEFAULT_SCHEDULE,
        help="Run all conditions per task/repeat block (default) or condition-blocked.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SCHEDULE_SEED)
    args = parser.parse_args()
    if bool(args.task_id) == args.all:
        parser.error("choose exactly one of --task-id TASK_ID (repeatable) or --all")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    task_ids = args.task_id or [task.task_id for task in PILOT_TASKS[:8]]
    conditions = args.condition or list(CONDITIONS)
    reports_by_condition: dict[str, list[dict[str, Any]]] = {condition: [] for condition in conditions}
    schedule_items = build_schedule(
        task_ids,
        conditions,
        args.repeats,
        schedule=args.schedule,
        seed=args.seed,
    )

    for schedule_index, (repeat_index, task_id, condition) in enumerate(schedule_items):
        report = run_ablation(
            task_id,
            condition,
            repeat_index,
            schedule=args.schedule,
            schedule_seed=args.seed,
            schedule_index=schedule_index,
        )
        reports_by_condition[condition].append(report)
        write_report(report)

    for condition, reports in reports_by_condition.items():
        condition_dir = ABLATION_ROOT / condition
        condition_dir.mkdir(parents=True, exist_ok=True)
        (condition_dir / "summary.json").write_text(
            json.dumps(_single_summary(reports), ensure_ascii=False, indent=2) + "\n"
        )

    manifest = {
        "scope": "qwen35_flash_error_protocol_ablation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": ABLATION_MODEL_ID,
        "model_config": MODEL_CONFIG,
        "conditions": {condition: CONDITIONS[condition] for condition in conditions},
        "task_ids": task_ids,
        "task_set_digest": _task_set_digest(task_ids),
        "repeats": args.repeats,
        "schedule": args.schedule,
        "schedule_seed": args.seed,
        "git": _git_metadata(),
    }
    ABLATION_ROOT.mkdir(parents=True, exist_ok=True)
    (ABLATION_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    if set(reports_by_condition) == set(CONDITIONS):
        summary = summarize_ablation(reports_by_condition)
        ABLATION_ROOT.mkdir(parents=True, exist_ok=True)
        summary_path = ABLATION_ROOT / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"completed": True, "summary": summary, "summary_report": str(summary_path)}))
    else:
        print(json.dumps({"completed": True, "conditions": list(reports_by_condition)}))


if __name__ == "__main__":
    main()
