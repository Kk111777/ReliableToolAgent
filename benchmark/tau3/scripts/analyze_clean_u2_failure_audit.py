"""Offline completion and failure-attribution analysis for the clean U2 audit."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from analyze_retail_observability import (
    _call_records,
    _compact_message,
    _cross_turn_case,
    _failure_recovered,
    _same_message_groups,
    _short_text,
    _tool_classification,
)
from analyze_user_simulator_ablation import is_confirmation


INPUT = Path("data/simulations/tau3-retail-clean-u2-20x1/results.json")
RETRY_INPUT = INPUT.parent / "evaluator_retry.json"
OUTPUT = Path("data/analysis/retail-observability/clean-u2-20x1")
CONFIRMATION_REQUEST_RE = re.compile(
    r"(?:please confirm|do you confirm|would you like to proceed|"
    r"please proceed|if you.*confirm|shall i .*\?)",
    re.IGNORECASE,
)


def load_simulations() -> list[dict[str, Any]]:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    return [simulation for simulation in data.get("simulations", []) if isinstance(simulation, dict)]


def retry_records() -> dict[str, dict[str, Any]]:
    if not RETRY_INPUT.exists():
        return {}
    data = json.loads(RETRY_INPUT.read_text(encoding="utf-8"))
    return {str(record.get("task_id")): record for record in data.get("records", [])}


def assistant_turn(message: dict[str, Any]) -> bool:
    return message.get("role") == "assistant" and (
        message.get("usage") is not None
        or message.get("raw_data") is not None
        or message.get("content") is not None
        or message.get("tool_calls") is not None
    )


def final_user_message(simulation: dict[str, Any]) -> tuple[int, str] | None:
    messages = simulation.get("messages") or []
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index, str(messages[index].get("content") or "")
    return None


def terminal_type(text: str) -> str:
    if "###STOP###" in text:
        return "STOP"
    if "###TRANSFER###" in text:
        return "TRANSFER"
    return "NONE"


def expected_write_keys(simulation: dict[str, Any]) -> set[tuple[str, str]]:
    from analyze_retail_observability import canonical_arguments

    return {
        (
            str(check.get("action", {}).get("name")),
            canonical_arguments(check.get("action", {}).get("arguments") or {}),
        )
        for check in (simulation.get("reward_info") or {}).get("action_checks") or []
        if check.get("tool_type") == "write"
    }


def completion_metrics(
    simulation: dict[str, Any],
    tool_classes: dict[str, str],
) -> dict[str, Any]:
    messages = simulation.get("messages") or []
    records = _call_records(simulation, tool_classes)
    expected_keys = expected_write_keys(simulation)
    for record in records:
        record["is_expected_write"] = (
            record["tool_effect_class"] == "write"
            and (record["tool_name"], record["normalized_arguments"]) in expected_keys
            and record["parsed_status"] == "success"
        )

    confirmations: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        text = str(message.get("content") or "")
        if not is_confirmation(text):
            continue
        next_agent_indexes = [
            later_index
            for later_index, later in enumerate(messages[index + 1 :], start=index + 1)
            if assistant_turn(later)
        ]
        confirmation = {
            "message_index": index,
            "message": text,
            "agent_received_confirmation": bool(next_agent_indexes),
            "next_agent_message_index": next_agent_indexes[0] if next_agent_indexes else None,
            "post_confirmation_agent_turn_count": len(next_agent_indexes),
            "confirmation_request_before": bool(
                index > 0
                and messages[index - 1].get("role") == "assistant"
                and CONFIRMATION_REQUEST_RE.search(str(messages[index - 1].get("content") or ""))
            ),
        }
        confirmations.append(confirmation)

    final = final_user_message(simulation)
    final_text = final[1] if final else ""
    final_terminal = terminal_type(final_text)
    latest_confirmation = confirmations[-1] if confirmations else None
    expected_after_confirmation = False
    if latest_confirmation and latest_confirmation["agent_received_confirmation"]:
        expected_after_confirmation = any(
            record["is_expected_write"] and record["message_index"] > latest_confirmation["message_index"]
            for record in records
        )
    writes = [record for record in records if record["tool_effect_class"] == "write"]
    expected_writes = [record for record in records if record["is_expected_write"]]
    reward_info = simulation.get("reward_info") or {}
    breakdown = reward_info.get("reward_breakdown") or {}
    user_terminal_before_write = bool(final_terminal in {"STOP", "TRANSFER"} and expected_keys and not expected_writes)
    post_confirmation_no_write = bool(
        expected_keys
        and latest_confirmation
        and latest_confirmation["agent_received_confirmation"]
        and not expected_after_confirmation
    )
    return {
        "task_id": str(simulation.get("task_id")),
        "trial_id": simulation.get("trial"),
        "termination_reason": simulation.get("termination_reason"),
        "infrastructure_error": simulation.get("termination_reason") == "infrastructure_error",
        "final_reward": reward_info.get("reward"),
        "db_reward": breakdown.get("DB"),
        "nl_reward": breakdown.get("NL_ASSERTION"),
        "reward_components": breakdown,
        "terminal_type": final_terminal,
        "final_user_message": final_text,
        "expected_write_exists": bool(expected_keys),
        "user_terminal_before_write": user_terminal_before_write,
        "agent_received_confirmation": bool(
            latest_confirmation and latest_confirmation["agent_received_confirmation"]
        ),
        "expected_WRITE_after_confirmation": expected_after_confirmation,
        "post_confirmation_no_write": post_confirmation_no_write,
        "post_confirmation_agent_turn_count": (
            latest_confirmation["post_confirmation_agent_turn_count"] if latest_confirmation else None
        ),
        "confirmation_status": "confirmed" if latest_confirmation else "needs_manual_review",
        "confirmations": confirmations,
        "expected_write_observed": bool(expected_writes),
        "write_tool_calls": len(writes),
        "expected_write_calls": [
            {
                "tool": record["tool_name"],
                "arguments": record["raw_arguments"],
                "result": record["tool_result"],
                "message_index": record["message_index"],
            }
            for record in expected_writes
        ],
        "all_write_calls": [
            {
                "tool": record["tool_name"],
                "arguments": record["raw_arguments"],
                "status": record["parsed_status"],
                "result": record["tool_result"],
                "message_index": record["message_index"],
                "is_expected_write": record["is_expected_write"],
            }
            for record in writes
        ],
        "tool_failure_count": sum(record["parsed_status"] == "error" for record in records),
        "same_message_duplicate_calls": sum(len(group) for group in _same_message_groups(records).values()),
        "cross_turn_exact_repeat_calls": len(_cross_turn_case(records, messages, tool_classes)),
        "agent_model_calls": sum(
            message.get("role") == "assistant"
            and (message.get("usage") is not None or message.get("raw_data") is not None)
            for message in messages
        ),
        "user_model_calls": sum(
            message.get("role") == "user" and (message.get("usage") is not None or message.get("raw_data") is not None)
            for message in messages
        ),
        "tool_calls": len(records),
        "latency_seconds": simulation.get("duration"),
    }


def compact_case(
    simulation: dict[str, Any],
    metric: dict[str, Any],
    tool_classes: dict[str, str],
) -> dict[str, Any]:
    messages = simulation.get("messages") or []
    records = _call_records(simulation, tool_classes)
    return {
        "task_id": metric["task_id"],
        "trial_id": metric["trial_id"],
        "termination_reason": metric["termination_reason"],
        "terminal_type": metric["terminal_type"],
        "final_reward": metric["final_reward"],
        "db_reward": metric["db_reward"],
        "nl_reward": metric["nl_reward"],
        "reward_components": metric["reward_components"],
        "agent_received_confirmation": metric["agent_received_confirmation"],
        "expected_WRITE_after_confirmation": metric["expected_WRITE_after_confirmation"],
        "post_confirmation_no_write": metric["post_confirmation_no_write"],
        "user_terminal_before_write": metric["user_terminal_before_write"],
        "final_user_message": metric["final_user_message"],
        "confirmation_messages": metric["confirmations"],
        "tool_failures": metric["tool_failure_count"],
        "tool_failure_recovery": [
            _failure_recovered(index, records, simulation)
            for index, record in enumerate(records)
            if record["parsed_status"] == "error"
        ],
        "write_calls": metric["all_write_calls"],
        "trajectory_context": [
            _compact_message(message, index)
            for index, message in enumerate(messages)
            if message.get("role") in {"user", "assistant", "tool"}
        ],
        "tool_records": records,
    }


def candidate_categories(metric: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    if metric["user_terminal_before_write"]:
        candidates.append("user_simulator_termination")
    if metric["post_confirmation_no_write"]:
        candidates.append("post_confirmation_no_write")
    if metric["tool_failure_count"]:
        candidates.append("tool_failure")
    if metric["write_tool_calls"] and metric["db_reward"] != 1:
        candidates.append("wrong_write_arguments")
    if not metric["expected_write_observed"]:
        candidates.append("incomplete_execution")
    return candidates[:3] or ["other"]


def write_audit(
    metrics: list[dict[str, Any]],
    simulations: dict[str, dict[str, Any]],
    tool_classes: dict[str, str],
    retry: dict[str, dict[str, Any]],
) -> None:
    reward_zero = [metric for metric in metrics if metric["final_reward"] == 0]
    lines = [
        "# Clean U2 20x1 failure attribution audit",
        "",
        "This is an offline evidence index. Candidate categories are not primary-cause labels.",
        "The Agent and official tau2 runtime were not modified.",
        "",
        "## Infrastructure boundary",
        "",
        "T04 ended as `infrastructure_error` with an evaluator JSON parse error and has no reward trajectory.",
        "It is excluded from behavioral denominators and is not treated as a reward-zero Agent case.",
        "",
        "## Reward-zero tasks",
        "",
    ]
    if not reward_zero:
        lines.append("No valid reward-zero tasks.")
    for metric in reward_zero:
        task_id = metric["task_id"]
        lines += [
            f"### T{task_id} trial {metric['trial_id']}",
            f"- final reward: `{metric['final_reward']}`; DB: `{metric['db_reward']}`; NL: `{metric['nl_reward']}`",
            f"- termination: `{metric['termination_reason']}`; terminal type: `{metric['terminal_type']}`",
            f"- user_terminal_before_write: `{metric['user_terminal_before_write']}`",
            f"- agent_received_confirmation: `{metric['agent_received_confirmation']}`",
            f"- expected_WRITE_after_confirmation: `{metric['expected_WRITE_after_confirmation']}`",
            f"- post_confirmation_no_write: `{metric['post_confirmation_no_write']}`",
            f"- tool_failures: `{metric['tool_failure_count']}`; same-message duplicate calls: `{metric['same_message_duplicate_calls']}`; cross-turn repeats: `{metric['cross_turn_exact_repeat_calls']}`",
            f"- candidate categories: `{', '.join(candidate_categories(metric))}`",
            "- final user message:",
            f"  `{_short_text(metric['final_user_message'], 1200)}`",
            "",
            "#### Relevant trajectory",
        ]
        simulation = simulations[task_id]
        messages = simulation.get("messages") or []
        # Keep the complete semantic sequence but compact long tool payloads.
        for index, message in enumerate(messages):
            role = message.get("role")
            if role == "tool":
                lines.append(f"- Tool result [message {index}]: {_short_text(message.get('content'), 800)}")
            elif role == "assistant" and message.get("tool_calls"):
                for call in message["tool_calls"]:
                    lines.append(
                        f"- Agent tool call [message {index}]: `{call.get('name')}({_short_text(call.get('arguments') or {}, 500)})`"
                    )
            elif role in {"user", "assistant"}:
                lines.append(f"- {role.title()} [message {index}]: {_short_text(message.get('content'), 800)}")
        lines.append("")

    lines += [
        "## Manual completion table",
        "",
        "| Task | Primary cause | Secondary cause | Evidence | Controller could solve? |",
        "|---|---|---|---|---|",
    ]
    for metric in reward_zero:
        lines.append(
            f"| T{metric['task_id']} |  |  | candidates: {', '.join(candidate_categories(metric))}; "
            f"terminal={metric['terminal_type']}; DB={metric['db_reward']} |  |"
        )
    lines += [
        "",
        "## Evaluator retry facts",
        "",
    ]
    for task_id, record in sorted(retry.items(), key=lambda item: int(item[0])):
        if record.get("evaluator_retry_count") or record.get("error"):
            lines.append(
                f"- T{task_id}: evaluator_retry_count={record.get('evaluator_retry_count')}; error={record.get('error')}"
            )
    (OUTPUT / "failure_attribution_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    tool_classes = _tool_classification()
    simulations = load_simulations()
    by_task = {str(simulation.get("task_id")): simulation for simulation in simulations}
    metrics = [
        completion_metrics(simulation, tool_classes)
        for simulation in simulations
        if simulation.get("termination_reason") != "infrastructure_error"
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "agent_completion_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    cases = {
        "cases_post_confirmation_no_write.json": [
            compact_case(by_task[metric["task_id"]], metric, tool_classes)
            for metric in metrics
            if metric["post_confirmation_no_write"]
        ],
        "cases_write_but_db_fail.json": [
            compact_case(by_task[metric["task_id"]], metric, tool_classes)
            for metric in metrics
            if metric["write_tool_calls"] > 0 and metric["db_reward"] != 1
        ],
        "cases_tool_failures.json": [
            compact_case(by_task[metric["task_id"]], metric, tool_classes)
            for metric in metrics
            if metric["tool_failure_count"] > 0
        ],
        "cases_same_message_duplicates.json": [
            compact_case(by_task[metric["task_id"]], metric, tool_classes)
            for metric in metrics
            if metric["same_message_duplicate_calls"] > 0
        ],
        "cases_reward_zero.json": [
            compact_case(by_task[metric["task_id"]], metric, tool_classes)
            for metric in metrics
            if metric["final_reward"] == 0
        ],
    }
    for name, value in cases.items():
        (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    aggregate = {
        "valid_simulations": len(metrics),
        "infrastructure_errors": sum(
            simulation.get("termination_reason") == "infrastructure_error" for simulation in simulations
        ),
        "simulation_timeouts": sum(
            str(simulation.get("termination_reason", "")).lower() == "timeout" for simulation in simulations
        ),
        "reward_one": sum(metric["final_reward"] == 1 for metric in metrics),
        "reward_zero": sum(metric["final_reward"] == 0 for metric in metrics),
        "expected_write_executed": sum(metric["expected_write_observed"] for metric in metrics),
        "user_terminal_before_write": sum(metric["user_terminal_before_write"] for metric in metrics),
        "agent_received_confirmation": sum(metric["agent_received_confirmation"] for metric in metrics),
        "post_confirmation_no_write": sum(metric["post_confirmation_no_write"] for metric in metrics),
        "write_but_db_fail": sum(metric["write_tool_calls"] > 0 and metric["db_reward"] != 1 for metric in metrics),
        "explicit_tool_failures": sum(metric["tool_failure_count"] for metric in metrics),
        "tool_failure_tasks": sum(metric["tool_failure_count"] > 0 for metric in metrics),
        "same_message_duplicate_calls": sum(metric["same_message_duplicate_calls"] for metric in metrics),
        "same_message_duplicate_tasks": sum(metric["same_message_duplicate_calls"] > 0 for metric in metrics),
        "cross_turn_exact_repeat_calls": sum(metric["cross_turn_exact_repeat_calls"] for metric in metrics),
    }
    (OUTPUT / "agent_completion_summary.json").write_text(
        json.dumps({"aggregate": aggregate, "metrics": metrics}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_audit(metrics, by_task, tool_classes, retry_records())

    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
