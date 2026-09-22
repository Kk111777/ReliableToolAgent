"""Offline report for the U0/U1 user-simulator model ablation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from analyze_retail_observability import (
    _call_records,
    _message_usage,
    _tool_classification,
)


ROOT = Path("data/simulations")
OUT = Path("data/analysis/retail-observability/user-simulator-ablation-0-4")
TASK_IDS = ["0", "4", "5", "6", "7"]
CONDITIONS = {"U0": "tau3-retail-user-simulator-ablation-u0-0-4", "U1": "tau3-retail-user-simulator-ablation-u1-0-4"}

CONFIRMATION_RE = re.compile(
    r"\b(?:yes|i confirm|confirmed|please proceed|go ahead|that(?:'s| is) correct|process it|do it)\b",
    re.IGNORECASE,
)
CONFIRMATION_REQUEST_RE = re.compile(
    r"(?:please confirm|do you confirm|would you like to proceed|please proceed|if you.*confirm|shall i .*\?|proceed with)",
    re.IGNORECASE,
)


def load(condition: str) -> dict[str, Any]:
    path = ROOT / CONDITIONS[condition] / "results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def short(value: Any, limit: int = 520) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = text.replace("<think>", "").replace("</think>", "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " [...truncated...]"


def user_messages(simulation: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    return [(i, m) for i, m in enumerate(simulation.get("messages") or []) if m.get("role") == "user"]


def final_user(simulation: dict[str, Any]) -> tuple[int, str] | None:
    messages = user_messages(simulation)
    if not messages:
        return None
    index, message = messages[-1]
    return index, str(message.get("content") or "")


def is_confirmation(text: str) -> bool:
    return bool(CONFIRMATION_RE.search(text))


def expected_writes(simulation: dict[str, Any]) -> list[str]:
    reward_info = simulation.get("reward_info") or {}
    return [
        check["action"]["name"]
        for check in reward_info.get("action_checks") or []
        if check.get("tool_type") == "write"
    ]


def counts(simulation: dict[str, Any], tool_classes: dict[str, str]) -> dict[str, Any]:
    messages = simulation.get("messages") or []
    records = _call_records(simulation, tool_classes)
    agent_calls = sum(
        message.get("role") == "assistant"
        and (message.get("usage") is not None or message.get("raw_data") is not None)
        for message in messages
    )
    user_calls = sum(
        message.get("role") == "user" and (message.get("usage") is not None or message.get("raw_data") is not None)
        for message in messages
    )
    agent_tokens = sum(
        usage
        for message in messages
        if message.get("role") == "assistant"
        for usage in [_message_usage(message)]
        if usage is not None
    )
    user_tokens = sum(
        usage
        for message in messages
        if message.get("role") == "user"
        for usage in [_message_usage(message)]
        if usage is not None
    )
    final = final_user(simulation)
    final_text = final[1] if final else ""
    stop = "###STOP###" in final_text
    transfer = "###TRANSFER###" in final_text
    terminal_type = "STOP" if stop else ("TRANSFER" if transfer else "NONE")
    terminal = terminal_type in {"STOP", "TRANSFER"}
    confirmed_user_indices = [
        i for i, message in user_messages(simulation) if is_confirmation(str(message.get("content") or ""))
    ]
    last_confirmation_index = confirmed_user_indices[-1] if confirmed_user_indices else None
    post_confirmation_agent_turns = (
        sum(message.get("role") == "assistant" for message in messages[last_confirmation_index + 1 :])
        if last_confirmation_index is not None
        else None
    )
    prior_assistant = messages[final[0] - 1] if final and final[0] > 0 else None
    immediate = bool(
        stop
        and is_confirmation(final_text)
        and prior_assistant
        and prior_assistant.get("role") == "assistant"
        and CONFIRMATION_REQUEST_RE.search(str(prior_assistant.get("content") or ""))
    )
    reward_info = simulation.get("reward_info") or {}
    writes = [r for r in records if r.get("tool_effect_class") == "write"]
    expected = expected_writes(simulation)
    expected_write_observed = any(
        check.get("tool_type") == "write" and check.get("action_match") is True
        for check in (reward_info.get("action_checks") or [])
    )
    breakdown = reward_info.get("reward_breakdown") or {}
    writes_before_terminal = len(writes) if terminal else None
    premature = bool(expected and terminal and final and is_confirmation(final_text) and not expected_write_observed)
    return {
        "task_id": str(simulation.get("task_id")),
        "termination_reason": simulation.get("termination_reason"),
        "final_reward": reward_info.get("reward"),
        "db_reward": (reward_info.get("db_check") or {}).get("db_reward"),
        "nl_reward": breakdown.get("NL_ASSERTION"),
        "agent_model_calls": agent_calls,
        "user_model_calls": user_calls,
        "tool_calls": len(records),
        "write_tool_calls": len(writes),
        "agent_tokens": agent_tokens or None,
        "user_tokens": user_tokens or None,
        "latency_seconds": simulation.get("duration"),
        "final_user_message": final_text,
        "contains_stop": stop,
        "contains_transfer": transfer,
        "terminal_type": terminal_type,
        "final_user_message_contains_confirmation": is_confirmation(final_text) if final else None,
        "confirmation_status": "confirmed"
        if final and is_confirmation(final_text)
        else ("needs_manual_review" if final else "unavailable"),
        "premature_user_termination_before_write": premature,
        "required_write_observed_before_stop": expected_write_observed if stop else None,
        "write_tool_calls_before_terminal": writes_before_terminal,
        "expected_write_observed": expected_write_observed,
        "post_confirmation_agent_turn_count": post_confirmation_agent_turns,
        "stop_immediately_after_confirmation_phase": immediate,
        "expected_write_actions": expected,
        "evaluator_retry_count": None,
        "records": records,
    }


def message_lines(simulation: dict[str, Any], limit: int = 10) -> list[str]:
    messages = simulation.get("messages") or []
    selected = list(enumerate(messages))[-limit:]
    lines: list[str] = []
    for index, message in selected:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            content = message.get("content") or ""
            if content:
                lines.append(f"- Agent: {short(content)}")
            for call in message["tool_calls"]:
                lines.append(
                    f"- Agent Tool Call: `{call.get('name')}`({json.dumps(call.get('arguments') or {}, ensure_ascii=False, sort_keys=True)})"
                )
        elif role == "tool":
            status = "error" if message.get("error") else "success"
            lines.append(f"- Tool Result ({status}): {short(message.get('content') or message.get('error'))}")
        elif role == "assistant":
            lines.append(f"- Agent: {short(message.get('content') or '')}")
        elif role == "user":
            lines.append(f"- User: {short(message.get('content') or '')}")
    return lines


def main() -> None:
    tool_classes = _tool_classification()
    data = {condition: load(condition) for condition in CONDITIONS}
    metrics: dict[str, list[dict[str, Any]]] = {"U0": [], "U1": []}
    by_condition_task: dict[tuple[str, str], dict[str, Any]] = {}

    for condition, result in data.items():
        retry_path = ROOT / CONDITIONS[condition] / "evaluator_retry.json"
        retry_records = {}
        if retry_path.exists():
            retry_records = {
                str(item.get("task_id")): item.get("evaluator_retry_count")
                for item in json.loads(retry_path.read_text(encoding="utf-8")).get("records", [])
            }
        simulations = {str(s.get("task_id")): s for s in result.get("simulations") or []}
        for task_id in TASK_IDS:
            simulation = simulations.get(task_id)
            if simulation is None:
                row = {"task_id": task_id, "termination_reason": "missing", "infrastructure_error": True}
            elif simulation.get("termination_reason") == "infrastructure_error":
                row = {
                    "task_id": task_id,
                    "termination_reason": "infrastructure_error",
                    "infrastructure_error": True,
                    "infrastructure_detail": "official default user model unavailable: gpt-4.1-2025-04-14",
                }
            else:
                row = counts(simulation, tool_classes)
                row["infrastructure_error"] = False
                row["evaluator_retry_count"] = retry_records.get(task_id, 0)
            metrics[condition].append(row)
            by_condition_task[(condition, task_id)] = row

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# User Simulator Sanity Ablation",
        "",
        "Offline analysis of the two runner artifacts. The Agent, task, tools, prompts, STOP protocol, environment, evaluator, and orchestrator were not modified.",
        "",
        "## Fixed configuration",
        "",
        "- Commit: `b7ea9074c1cba482b30687fecdb5c8425fd6f619`",
        "- Agent: `openai/qwen3.5-flash-2026-02-23`",
        "- U0 user: `openai/qwen3.5-flash-2026-02-23`",
        "- U1 official default user: `gpt-4.1-2025-04-14` from `src/tau2/config.py`",
        "- `temperature=0`, `max_tokens=512`, LiteLLM `timeout=60`, `num_retries=3`",
        "- `simulation_timeout=unset`, `max_steps=200`, runner `max_retries=0`, `concurrency=1`, `seed=300`",
        "- Evaluator model: `openai/qwen3.5-flash-2026-02-23`; parse wrapper max retries: 2",
        "",
        "## U1 availability",
        "",
        "U1 was stopped after the first official runner attempt because all five tasks failed before simulation start with `litellm.NotFoundError: The model gpt-4.1-2025-04-14 does not exist or you do not have access to it.` No U1 trajectory or reward was produced.",
        "",
        "## Summary",
        "",
        "| Metric | U0 | U1 |",
        "|---|---:|---:|",
    ]

    def valid(condition: str) -> list[dict[str, Any]]:
        return [row for row in metrics[condition] if not row.get("infrastructure_error")]

    u0 = valid("U0")
    u1 = valid("U1")
    summary_rows = [
        ("valid simulations", len(u0), len(u1)),
        (
            "premature user stop before WRITE",
            sum(
                row.get("required_write_observed_before_stop") is False
                and row.get("contains_stop")
                and row.get("final_user_message_contains_confirmation") is True
                for row in u0
            ),
            "N/A",
        ),
        (
            "stop immediately after confirmation phase",
            sum(row.get("stop_immediately_after_confirmation_phase") is True for row in u0),
            "N/A",
        ),
        ("tasks with WRITE executed", sum(row.get("write_tool_calls", 0) > 0 for row in u0), "N/A"),
        ("DB reward=1", sum(row.get("db_reward") == 1.0 for row in u0), "N/A"),
        ("final reward=1", sum(row.get("final_reward") == 1.0 for row in u0), "N/A"),
        (
            "infrastructure errors",
            sum(row.get("infrastructure_error") for row in metrics["U0"]),
            sum(row.get("infrastructure_error") for row in metrics["U1"]),
        ),
    ]
    for name, u0_value, u1_value in summary_rows:
        lines.append(f"| {name} | {u0_value} | {u1_value} |")

    lines += [
        "",
        "## Paired task metrics",
        "",
        "| Task | Condition | Termination | Final | DB | NL | Agent calls | User calls | Tools | WRITE | Post-confirm agent turns | Final confirmation | STOP | Required WRITE before STOP | Evaluator retries |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|",
    ]
    for task_id in TASK_IDS:
        for condition in ("U0", "U1"):
            row = by_condition_task[(condition, task_id)]
            lines.append(
                "| {task} | {condition} | {term} | {final} | {db} | {nl} | {agent} | {user} | {tools} | {write} | {post} | {confirm} | {stop} | {required} | {retries} |".format(
                    task=task_id,
                    condition=condition,
                    term=row.get("termination_reason"),
                    final=row.get("final_reward", "N/A"),
                    db=row.get("db_reward", "N/A"),
                    nl=row.get("nl_reward", "N/A"),
                    agent=row.get("agent_model_calls", "N/A"),
                    user=row.get("user_model_calls", "N/A"),
                    tools=row.get("tool_calls", "N/A"),
                    write=row.get("write_tool_calls", "N/A"),
                    post=row.get("post_confirmation_agent_turn_count", "N/A"),
                    confirm=row.get("final_user_message_contains_confirmation", "N/A"),
                    stop=row.get("contains_stop", "N/A"),
                    required=row.get("required_write_observed_before_stop", "N/A"),
                    retries=row.get("evaluator_retry_count", "N/A"),
                )
            )

    lines += ["", "## Per-task final user messages", ""]
    for task_id in TASK_IDS:
        lines.append(f"### Task {task_id}")
        for condition in ("U0", "U1"):
            row = by_condition_task[(condition, task_id)]
            lines.append(
                f"- {condition}: `{short(row.get('final_user_message', row.get('infrastructure_detail', 'unavailable')), 900)}`"
            )
            lines.append(
                f"  - confirmation_status: `{row.get('confirmation_status', 'unavailable')}`; contains_STOP: `{row.get('contains_stop', False)}`; contains_TRANSFER: `{row.get('contains_transfer', False)}`"
            )

    lines += [
        "",
        "## Paired trajectory evidence",
        "",
        "The following are the final ten stored messages for each valid U0 task. U1 has no messages because the official default model was unavailable.",
        "",
    ]
    for task_id in TASK_IDS:
        lines.append(f"### T{task_id}")
        for condition in ("U0", "U1"):
            simulation = next(
                (s for s in data[condition].get("simulations") or [] if str(s.get("task_id")) == task_id), None
            )
            lines.append(f"#### {condition}")
            if simulation and simulation.get("messages"):
                lines.extend(message_lines(simulation))
            else:
                lines.append("- No trajectory: infrastructure error before simulation start.")
            lines.append("")

    lines += [
        "## Interpretation boundary",
        "",
        "This run does not support a U0-versus-U1 behavioral comparison because U1 had zero valid simulations. The U0 rows are mechanical observations only; no claim is made here about which user simulator is better.",
        "",
        "Raw artifacts:",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u0-0-4/results.json`",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u1-0-4/results.json`",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u0-0-4/evaluator_retry.json`",
        "- `data/simulations/tau3-retail-user-simulator-ablation-u1-0-4/evaluator_retry.json`",
        "",
    ]
    (OUT / "user_simulator_ablation_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
