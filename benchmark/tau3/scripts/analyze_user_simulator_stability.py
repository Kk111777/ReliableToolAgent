"""Offline stability report for the U0/U2 user-simulator pilot."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from analyze_retail_observability import _tool_classification
from analyze_user_simulator_ablation import counts


ROOT = Path("data/simulations")
OUT = Path("data/analysis/retail-observability/user-simulator-stability-0-4")
TASK_IDS = ["0", "4", "5", "6", "7"]
ARTIFACTS = {
    "U0": "tau3-retail-user-simulator-ablation-u0-0-4",
    "U2": "tau3-retail-user-simulator-ablation-u2-0-4",
}


def load_rows(condition: str, tool_classes: dict[str, str]) -> list[dict[str, Any]]:
    path = ROOT / ARTIFACTS[condition] / "results.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for simulation in result.get("simulations", []):
        if str(simulation.get("task_id")) not in TASK_IDS:
            continue
        row = counts(simulation, tool_classes)
        row["trial"] = simulation.get("trial")
        row["infrastructure_error"] = simulation.get("termination_reason") == "infrastructure_error"
        rows.append(row)
    return sorted(rows, key=lambda row: (int(row["task_id"]), int(row.get("trial", 0))))


def ratio(rows: list[dict[str, Any]], predicate: str) -> str:
    return f"{sum(bool(row.get(predicate)) for row in rows)}/{len(rows)}"


def write_report(data: dict[str, list[dict[str, Any]]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "per_trial_metrics.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# User Simulator Stability Confirmation",
        "",
        "Offline analysis only. The only experimental variable was the User Simulator model.",
        "No Agent, prompt, task, tool, policy, environment, orchestrator, evaluator, or STOP protocol was changed.",
        "",
        "## Frozen configuration",
        "",
        "- Commit: `b7ea9074c1cba482b30687fecdb5c8425fd6f619`",
        "- Agent: `openai/qwen3.5-flash-2026-02-23`",
        "- U0 User: `openai/qwen3.5-flash-2026-02-23`",
        "- U2 User: `openai/qwen3.8-max-2026-09-02`",
        "- `temperature=0`, `max_tokens=512`, LiteLLM `timeout=60`, `num_retries=3`",
        "- `simulation_timeout=unset`, `max_steps=200`, runner `max_retries=0`, `concurrency=1`, `seed=300`",
        "",
        "One initial U0 supplement attempt had one transient infrastructure parse failure for T04 trial 1.",
        "That exact missing trial key was rerun with the same configuration; the final denominator contains 15 valid U0 simulations.",
        "",
        "## Aggregate results",
        "",
        "| Metric | U0 | U2 |",
        "|---|---:|---:|",
    ]
    for label, key in [
        ("valid simulations", None),
        ("premature termination before WRITE", "premature_user_termination_before_write"),
        ("STOP before WRITE", "stop_before_write"),
        ("TRANSFER before WRITE", "transfer_before_write"),
        ("expected WRITE executed", "expected_write_observed"),
        ("DB reward=1", "db_reward_one"),
        ("final reward=1", "final_reward_one"),
        ("infrastructure errors", "infrastructure_error"),
    ]:
        values = []
        for condition, rows in data.items():
            valid = [row for row in rows if not row["infrastructure_error"]]
            if label == "valid simulations":
                values.append(str(len(valid)))
            elif label == "infrastructure errors":
                values.append(str(sum(row["infrastructure_error"] for row in rows)))
            elif key == "stop_before_write":
                values.append(
                    str(sum(row["terminal_type"] == "STOP" and not row["expected_write_observed"] for row in valid))
                )
            elif key == "transfer_before_write":
                values.append(
                    str(
                        sum(row["terminal_type"] == "TRANSFER" and not row["expected_write_observed"] for row in valid)
                    )
                )
            elif key == "db_reward_one":
                values.append(str(sum(row.get("db_reward") == 1 for row in valid)))
            elif key == "final_reward_one":
                values.append(str(sum(row.get("final_reward") == 1 for row in valid)))
            else:
                values.append(str(sum(bool(row.get(key)) for row in valid)))
        lines.append(f"| {label} | {values[0]} | {values[1]} |")

    lines += [
        "",
        "## Per-task, three-trial counts",
        "",
        "| Task | Condition | Premature / 3 | STOP-before-WRITE / 3 | TRANSFER-before-WRITE / 3 | WRITE / 3 | DB=1 / 3 | Final=1 / 3 | post-confirm agent turns |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for condition, rows in data.items():
        for row in rows:
            grouped[(condition, row["task_id"])].append(row)
    for task_id in TASK_IDS:
        for condition in ("U0", "U2"):
            rows = sorted(grouped[(condition, task_id)], key=lambda row: row.get("trial", 0))
            stop_before = [
                row for row in rows if row["terminal_type"] == "STOP" and not row["expected_write_observed"]
            ]
            transfer_before = [
                row for row in rows if row["terminal_type"] == "TRANSFER" and not row["expected_write_observed"]
            ]
            turns = ", ".join(str(row.get("post_confirmation_agent_turn_count")) for row in rows)
            lines.append(
                f"| T{task_id} | {condition} | {ratio(rows, 'premature_user_termination_before_write')} | "
                f"{len(stop_before)}/3 | {len(transfer_before)}/3 | {ratio(rows, 'expected_write_observed')} | "
                f"{sum(row.get('db_reward') == 1 for row in rows)}/3 | {sum(row.get('final_reward') == 1 for row in rows)}/3 | {turns} |"
            )

    lines += [
        "",
        "## Per-trial terminal evidence",
        "",
        "| Task | Condition | Trial | Terminal | Premature | Expected WRITE | WRITE calls before terminal | DB | Final |",
        "|---|---|---:|---|---|---|---:|---:|---:|",
    ]
    for condition, rows in data.items():
        for row in rows:
            lines.append(
                f"| T{row['task_id']} | {condition} | {row.get('trial')} | {row.get('terminal_type')} | "
                f"{row.get('premature_user_termination_before_write')} | {row.get('expected_write_observed')} | "
                f"{row.get('write_tool_calls_before_terminal')} | {row.get('db_reward')} | {row.get('final_reward')} |"
            )
    lines += [
        "",
        "## Scope",
        "",
        "This is a mechanical stability report. It does not make a quality ranking or a causal claim about either User Simulator.",
        "No 20x1 run was started after this pilot.",
    ]
    (OUT / "stability_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    tool_classes = _tool_classification()
    data = {condition: load_rows(condition, tool_classes) for condition in ARTIFACTS}
    write_report(data)
    print(f"wrote {OUT / 'stability_report.md'}")
    print(f"wrote {OUT / 'per_trial_metrics.json'}")
    for condition, rows in data.items():
        print(condition, len(rows), "valid", sum(not row["infrastructure_error"] for row in rows))


if __name__ == "__main__":
    main()
