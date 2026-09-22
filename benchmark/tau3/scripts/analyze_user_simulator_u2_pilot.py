"""Offline U0 versus U2 pilot report for the retail user-simulator diagnosis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analyze_retail_observability import _tool_classification
from analyze_user_simulator_ablation import (
    counts,
    message_lines,
    short,
)


ROOT = Path("data/simulations")
OUT = Path("data/analysis/retail-observability/user-simulator-u2-pilot-0-4")
TASK_IDS = ["0", "4", "5", "6", "7"]
ARTIFACTS = {
    "U0": "tau3-retail-user-simulator-ablation-u0-0-4",
    "U2": "tau3-retail-user-simulator-ablation-u2-0-4",
}
MODELS = {
    "U0": "openai/qwen3.5-flash-2026-02-23",
    "U2": "openai/qwen3.8-max-2026-09-02",
}


def load(condition: str) -> dict[str, Any]:
    return json.loads((ROOT / ARTIFACTS[condition] / "results.json").read_text(encoding="utf-8"))


def retry_counts(condition: str) -> dict[str, int]:
    path = ROOT / ARTIFACTS[condition] / "evaluator_retry.json"
    if not path.exists():
        return {}
    return {
        str(record.get("task_id")): int(record.get("evaluator_retry_count", 0))
        for record in json.loads(path.read_text(encoding="utf-8")).get("records", [])
    }


def main() -> None:
    tool_classes = _tool_classification()
    data = {condition: load(condition) for condition in ARTIFACTS}
    rows: dict[str, dict[str, dict[str, Any]]] = {"U0": {}, "U2": {}}
    for condition, result in data.items():
        simulations = {str(item.get("task_id")): item for item in result.get("simulations") or []}
        retries = retry_counts(condition)
        for task_id in TASK_IDS:
            simulation = simulations.get(task_id)
            if simulation is None or simulation.get("termination_reason") == "infrastructure_error":
                rows[condition][task_id] = {
                    "task_id": task_id,
                    "infrastructure_error": True,
                    "termination_reason": "missing" if simulation is None else "infrastructure_error",
                }
                continue
            row = counts(simulation, tool_classes)
            row["infrastructure_error"] = False
            row["evaluator_retry_count"] = retries.get(task_id, 0)
            rows[condition][task_id] = row

    metrics = {condition: [rows[condition][task_id] for task_id in TASK_IDS] for condition in rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def valid(condition: str) -> list[dict[str, Any]]:
        return [row for row in rows[condition].values() if not row.get("infrastructure_error")]

    def count(condition: str, predicate) -> int:
        return sum(bool(predicate(row)) for row in valid(condition))

    lines = [
        "# U0 vs U2 User Simulator Pilot",
        "",
        "Offline paired analysis. Only the User Simulator model differs; no official tau2 runtime, prompt, task, tool, policy, environment, evaluator, orchestrator, or Agent behavior was changed.",
        "",
        "## Fixed configuration",
        "",
        "- Commit: `b7ea9074c1cba482b30687fecdb5c8425fd6f619`",
        "- Agent: `openai/qwen3.5-flash-2026-02-23`",
        "- U0 User: `openai/qwen3.5-flash-2026-02-23`",
        "- U2 User: `openai/qwen3.8-max-2026-09-02` (provider response identified it as `qwen3.8-max-0902`)",
        "- `temperature=0`, `max_tokens=512`, LiteLLM `timeout=60`, `num_retries=3`",
        "- `simulation_timeout=unset`, `max_steps=200`, runner `max_retries=0`, `concurrency=1`, `seed=300`",
        "- Evaluator: Qwen Agent snapshot with parse wrapper max retries 2",
        "",
        "## Summary",
        "",
        "| Metric | U0 | U2 |",
        "|---|---:|---:|",
    ]
    summary = [
        ("valid simulations", lambda r: True),
        (
            "premature user termination before WRITE",
            lambda r: r.get("premature_user_termination_before_write") is True,
        ),
        ("STOP-before-WRITE", lambda r: r.get("terminal_type") == "STOP" and not r.get("expected_write_observed")),
        (
            "TRANSFER-before-WRITE",
            lambda r: r.get("terminal_type") == "TRANSFER" and not r.get("expected_write_observed"),
        ),
        ("tasks executing expected WRITE", lambda r: r.get("expected_write_observed") is True),
        ("DB reward=1", lambda r: r.get("db_reward") == 1.0),
        ("final reward=1", lambda r: r.get("final_reward") == 1.0),
        ("infrastructure error", lambda r: r.get("infrastructure_error") is True),
    ]
    for label, predicate in summary:
        if label == "valid simulations":
            u0_value, u2_value = len(valid("U0")), len(valid("U2"))
        elif label == "infrastructure error":
            u0_value = sum(row.get("infrastructure_error") is True for row in rows["U0"].values())
            u2_value = sum(row.get("infrastructure_error") is True for row in rows["U2"].values())
        else:
            u0_value, u2_value = count("U0", predicate), count("U2", predicate)
        lines.append(f"| {label} | {u0_value} | {u2_value} |")

    lines += [
        "",
        "## Paired pilot table",
        "",
        "| Task | U0 terminal | U2 terminal | U0 premature | U2 premature | U0 WRITE | U2 WRITE | U0 DB | U2 DB | U0 final | U2 final |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for task_id in TASK_IDS:
        u0, u2 = rows["U0"][task_id], rows["U2"][task_id]
        lines.append(
            f"| {task_id} | {u0.get('terminal_type', 'N/A')} | {u2.get('terminal_type', 'N/A')} | "
            f"{u0.get('premature_user_termination_before_write', 'N/A')} | {u2.get('premature_user_termination_before_write', 'N/A')} | "
            f"{u0.get('write_tool_calls_before_terminal', 'N/A')} | {u2.get('write_tool_calls_before_terminal', 'N/A')} | "
            f"{u0.get('db_reward', 'N/A')} | {u2.get('db_reward', 'N/A')} | "
            f"{u0.get('final_reward', 'N/A')} | {u2.get('final_reward', 'N/A')} |"
        )

    lines += ["", "## Per-task terminal evidence", ""]
    for task_id in TASK_IDS:
        lines.append(f"### T{task_id}")
        for condition in ("U0", "U2"):
            row = rows[condition][task_id]
            simulation = next(
                (item for item in data[condition].get("simulations", []) if str(item.get("task_id")) == task_id), None
            )
            if row.get("infrastructure_error"):
                lines.append(f"- {condition}: infrastructure error; no trajectory")
                continue
            lines += [
                f"- {condition}: terminal_type=`{row['terminal_type']}`, premature=`{row['premature_user_termination_before_write']}`, ",
                f"  final_user_message_contains_confirmation=`{row['final_user_message_contains_confirmation']}`, confirmation_status=`{row['confirmation_status']}`",
                f"  post_confirmation_agent_turn_count=`{row['post_confirmation_agent_turn_count']}`, WRITE_tool_calls_before_terminal=`{row['write_tool_calls_before_terminal']}`, expected_WRITE_observed=`{row['expected_write_observed']}",
                f"  final_user_message: `{short(row['final_user_message'], 900)}`",
            ]

    lines += [
        "",
        "## Paired tail trajectories",
        "",
        "The following shows the final ten stored messages for each task/condition. Tool payloads are shortened for readability; hidden reasoning and evaluator-private data are not included.",
        "",
    ]
    for task_id in TASK_IDS:
        lines.append(f"### T{task_id}")
        for condition in ("U0", "U2"):
            simulation = next(
                (item for item in data[condition].get("simulations", []) if str(item.get("task_id")) == task_id), None
            )
            lines.append(f"#### {condition}")
            if simulation and simulation.get("messages"):
                lines.extend(message_lines(simulation, limit=10))
            else:
                lines.append("- No trajectory.")
            lines.append("")

    lines += [
        "## Scope boundary",
        "",
        "This is a diagnostic pilot, not an official τ³ leaderboard comparison. No conclusion about which User Simulator is better is made here. No 3-repeat experiment was run.",
        "",
        "## Artifacts",
        "",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u0-0-4/results.json`",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u2-0-4/results.json`",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u0-0-4/evaluator_retry.json`",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u2-0-4/evaluator_retry.json`",
        "- `data/analysis/retail-observability/user-simulator-u2-pilot-0-4/metrics.json`",
    ]
    (OUT / "u0_u2_pilot_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
