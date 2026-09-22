#!/usr/bin/env python3
"""Offline observability analysis for tau2 retail simulation artifacts.

This module deliberately reads the serialized results instead of instrumenting
the tau2 runtime.  It reports call-level facts and does not decide whether a
repeated call was useful or harmful.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


def canonical_arguments(arguments: Any) -> str:
    """Canonicalize JSON arguments without changing list order or values."""

    return json.dumps(
        arguments if arguments is not None else {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _compact_message(message: dict[str, Any], message_index: int) -> dict[str, Any]:
    """Keep context readable and avoid copying provider raw payloads."""

    compact = {
        "message_index": message_index,
        "role": message.get("role"),
        "turn_idx": message.get("turn_idx"),
        "content": message.get("content"),
    }
    if message.get("tool_calls") is not None:
        compact["tool_calls"] = _json_copy(message["tool_calls"])
    if message.get("id") is not None:
        compact["id"] = message["id"]
    if message.get("error") is not None:
        compact["error"] = message["error"]
    return compact


def _context(messages: list[dict[str, Any]], center: int, radius: int = 2) -> list[dict[str, Any]]:
    start = max(0, center - radius)
    stop = min(len(messages), center + radius + 1)
    return [_compact_message(messages[i], i) for i in range(start, stop)]


def _tool_result(message: dict[str, Any] | None) -> Any:
    if message is None:
        return None
    return {
        "content": _json_copy(message.get("content")),
        "error": message.get("error"),
    }


def _parsed_status(message: dict[str, Any] | None) -> str:
    """Parse only tau2's explicit ToolMessage.error flag.

    Text content is intentionally not interpreted: a string that happens to
    contain words such as "failed" is not enough evidence for a tool failure.
    """

    if message is None or not isinstance(message.get("error"), bool):
        return "unknown"
    return "error" if message["error"] else "success"


def _message_usage(message: dict[str, Any]) -> int | None:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)):
        return int(total)
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
        return int(prompt + completion)
    return None


def _tool_classification() -> dict[str, str]:
    """Read the official retail decorators; do not duplicate tool policy."""

    from tau2.domains.retail.environment import get_environment

    environment = get_environment()
    toolkit = environment.tools
    if toolkit is None:
        return {}
    return {name: toolkit.tool_type(name).value for name in sorted(toolkit.tools)}


def _load_results(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("simulations"), list):
        raise ValueError(f"Not a tau2 results artifact: {path}")
    return value


def _call_records(
    simulation: dict[str, Any],
    tool_classes: dict[str, str],
) -> list[dict[str, Any]]:
    messages = simulation.get("messages") or []
    result_messages = {
        message.get("id"): (index, message)
        for index, message in enumerate(messages)
        if message.get("role") == "tool" and message.get("id") is not None
    }
    records: list[dict[str, Any]] = []
    assistant_turn_sequence = 0
    for message_index, message in enumerate(messages):
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        assistant_turn_index = message.get("turn_idx", assistant_turn_sequence)
        for call_index, call in enumerate(message["tool_calls"]):
            call_id = call.get("id")
            result_entry = result_messages.get(call_id)
            result_index = result_entry[0] if result_entry else None
            result_message = result_entry[1] if result_entry else None
            records.append(
                {
                    "task_id": str(simulation.get("task_id")),
                    "trial_id": simulation.get("trial"),
                    "message_index": message_index,
                    "assistant_turn_index": assistant_turn_index,
                    "call_index": call_index,
                    "call_id": call_id,
                    "tool_name": call.get("name"),
                    "raw_arguments": _json_copy(call.get("arguments") or {}),
                    "normalized_arguments": canonical_arguments(call.get("arguments") or {}),
                    "tool_effect_class": tool_classes.get(call.get("name"), "unknown"),
                    "result_message_index": result_index,
                    "tool_result": _tool_result(result_message),
                    "parsed_status": _parsed_status(result_message),
                }
            )
        assistant_turn_sequence += 1
    return records


def _call_key(record: dict[str, Any]) -> tuple[str | None, str]:
    return record.get("tool_name"), record["normalized_arguments"]


def _record_context(record: dict[str, Any], messages: list[dict[str, Any]], radius: int = 2) -> dict[str, Any]:
    value = dict(record)
    value["context_messages"] = _context(messages, record["message_index"], radius)
    return value


def _reward_components(simulation: dict[str, Any]) -> dict[str, Any] | None:
    reward_info = simulation.get("reward_info") or {}
    return reward_info.get("reward_breakdown")


def _task_metrics(
    simulation: dict[str, Any],
    records: list[dict[str, Any]],
    tool_classes: dict[str, str],
) -> dict[str, Any]:
    messages = simulation.get("messages") or []
    same_groups = _same_message_groups(records)
    cross_repeats = _cross_turn_repeats(records)
    cross_cases = _cross_turn_case(records, messages, tool_classes)
    agent_tokens = sum(
        token_count
        for message in messages
        if message.get("role") == "assistant"
        for token_count in [_message_usage(message)]
        if token_count is not None
    )
    user_tokens = sum(
        token_count
        for message in messages
        if message.get("role") == "user"
        for token_count in [_message_usage(message)]
        if token_count is not None
    )
    agent_model_calls = sum(
        message.get("role") == "assistant"
        and (message.get("usage") is not None or message.get("raw_data") is not None)
        for message in messages
    )
    user_model_calls = sum(
        message.get("role") == "user" and (message.get("usage") is not None or message.get("raw_data") is not None)
        for message in messages
    )
    reward_info = simulation.get("reward_info") or {}
    reward = reward_info.get("reward")
    return {
        "task_id": str(simulation.get("task_id")),
        "trial_id": simulation.get("trial"),
        "official_final_reward": reward,
        "reward_components": _reward_components(simulation),
        "agent_model_calls": agent_model_calls,
        "user_model_calls": user_model_calls,
        "total_tool_calls": len(records),
        "read_tool_calls": sum(record["tool_effect_class"] == "read" for record in records),
        "write_tool_calls": sum(record["tool_effect_class"] == "write" for record in records),
        "same_message_exact_duplicate_calls": sum(len(group) for group in same_groups.values()),
        "same_message_exact_duplicate_groups": len(same_groups),
        "cross_turn_exact_repeat_calls": len(cross_repeats),
        "cross_turn_repeats_after_state_change": sum(case["repeat_after_state_change"] for case in cross_cases),
        "cross_turn_repeats_without_state_change": sum(not case["repeat_after_state_change"] for case in cross_cases),
        "tool_failure_count": sum(record["parsed_status"] == "error" for record in records),
        "unknown_tool_result_count": sum(record["parsed_status"] == "unknown" for record in records),
        "tokens": {
            "agent": agent_tokens if agent_tokens else None,
            "user": user_tokens if user_tokens else None,
            "total": (agent_tokens + user_tokens) if agent_tokens or user_tokens else None,
            "source": "messages[].usage.total_tokens or prompt_tokens+completion_tokens",
        },
        "latency_seconds": simulation.get("duration"),
        "termination_reason": simulation.get("termination_reason"),
    }


def _same_message_groups(records: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[tuple[int, tuple[str | None, str]], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record["message_index"], _call_key(record))].append(record)
    return {
        f"{message_index}:{tool_name}:{arguments}": values
        for (message_index, (tool_name, arguments)), values in groups.items()
        if len(values) >= 2
    }


def _cross_turn_repeats(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    first_message: dict[tuple[str | None, str], int] = {}
    repeats: list[dict[str, Any]] = []
    for record in records:
        key = _call_key(record)
        message_index = record["message_index"]
        if key not in first_message:
            first_message[key] = message_index
        elif message_index != first_message[key]:
            repeats.append(record)
    return repeats


def _cross_turn_case(
    records: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tool_classes: dict[str, str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_call_key(record)].append(record)
    cases: list[dict[str, Any]] = []
    for (tool_name, normalized_arguments), occurrences in grouped.items():
        if len(occurrences) < 2:
            continue
        for previous, current in zip(occurrences, occurrences[1:]):
            if previous["message_index"] == current["message_index"]:
                continue
            first = previous["message_index"]
            last = current["message_index"]
            intervening = messages[first + 1 : last]
            write_between = any(
                message.get("role") == "assistant"
                and any(tool_classes.get(call.get("name")) == "write" for call in (message.get("tool_calls") or []))
                for message in intervening
            )
            cases.append(
                {
                    "task_id": occurrences[0]["task_id"],
                    "trial_id": occurrences[0]["trial_id"],
                    "tool_name": tool_name,
                    "normalized_arguments": normalized_arguments,
                    "occurrences": [
                        _record_context(previous, messages),
                        _record_context(current, messages),
                    ],
                    "turn_indexes": [
                        previous["assistant_turn_index"],
                        current["assistant_turn_index"],
                    ],
                    "intervening_user_message_count": sum(message.get("role") == "user" for message in intervening),
                    "intervening_tool_messages": [
                        {
                            "message_index": first + 1 + offset,
                            "content": _json_copy(message.get("content")),
                            "error": message.get("error"),
                        }
                        for offset, message in enumerate(intervening)
                        if message.get("role") == "tool"
                    ],
                    "write_tool_executed_between": write_between,
                    "repeat_after_state_change": write_between,
                }
            )
    return cases


def _failure_recovered(
    record_index: int,
    records: list[dict[str, Any]],
    simulation: dict[str, Any],
) -> dict[str, bool]:
    failure = records[record_index]
    different_arguments_success = any(
        later["tool_name"] == failure["tool_name"]
        and later["normalized_arguments"] != failure["normalized_arguments"]
        and later["parsed_status"] == "success"
        for later in records[record_index + 1 :]
    )
    reward = (simulation.get("reward_info") or {}).get("reward")
    normal_termination = str(simulation.get("termination_reason", "")).lower() == "user_stop" and reward is not None
    return {
        "different_arguments_success": different_arguments_success,
        "normal_termination_with_reward": normal_termination,
        "recovered_after_tool_failure": (different_arguments_success or normal_termination),
    }


def _base_case_fields(simulation: dict[str, Any]) -> dict[str, Any]:
    reward_info = simulation.get("reward_info") or {}
    return {
        "task_id": str(simulation.get("task_id")),
        "trial_id": simulation.get("trial"),
        "official_final_reward": reward_info.get("reward"),
        "reward_components": reward_info.get("reward_breakdown"),
        "termination_reason": simulation.get("termination_reason"),
    }


def _short_text(value: Any, limit: int = 700) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _render_context(context_messages: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for message in context_messages:
        role = message.get("role")
        index = message.get("message_index")
        if role == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                lines.append(
                    f"- Assistant tool call [message {index}]: "
                    f"`{call.get('name')}({_short_text(call.get('arguments') or {})})`"
                )
        elif role == "tool":
            lines.append(
                f"- Tool result [message {index}, id={message.get('id')}]: "
                f"error={message.get('error')}; {_short_text(message.get('content'))}"
            )
        elif role in {"user", "assistant"}:
            lines.append(f"- {role.title()} [message {index}]: {_short_text(message.get('content'))}")
    return lines


def _write_human_audit(
    output_dir: Path,
    same_cases: list[dict[str, Any]],
    cross_cases: list[dict[str, Any]],
    failure_cases: list[dict[str, Any]],
    reward_zero_cases: list[dict[str, Any]],
) -> None:
    lines = [
        "# Retail observability audit",
        "",
        "This is a factual trajectory index. It does not label a repeated call as unnecessary or incorrect.",
        "",
    ]

    def add_case(title: str, case: dict[str, Any], context: list[dict[str, Any]]) -> None:
        lines.extend(
            [
                f"## {title}: task={case.get('task_id')} trial={case.get('trial_id')}",
                f"- official_final_reward: `{case.get('official_final_reward')}`",
                f"- reward_components: `{json.dumps(case.get('reward_components'), ensure_ascii=False)}`",
                f"- turn_indexes: `{case.get('turn_indexes')}`",
            ]
        )
        if "repeat_after_state_change" in case:
            lines.append(f"- repeat_after_state_change: `{case['repeat_after_state_change']}`")
        if "recovered_after_tool_failure" in case:
            lines.append(f"- recovered_after_tool_failure: `{case['recovered_after_tool_failure']}`")
        lines.extend(_render_context(context))
        lines.append("")

    for index, case in enumerate(same_cases, start=1):
        add_case(
            f"same-message exact duplicate #{index} ({case.get('tool_name')})",
            case,
            case.get("context_messages", []),
        )
    for index, case in enumerate(cross_cases, start=1):
        occurrence_context = []
        for occurrence in case.get("occurrences", []):
            occurrence_context.extend(occurrence.get("context_messages", []))
        deduped: dict[int, dict[str, Any]] = {message["message_index"]: message for message in occurrence_context}
        add_case(
            f"cross-turn exact repeat #{index} ({case.get('tool_name')})",
            case,
            [deduped[key] for key in sorted(deduped)],
        )
    for index, case in enumerate(failure_cases, start=1):
        add_case(
            f"explicit tool failure #{index}",
            case,
            case.get("context_messages", []),
        )
    for index, case in enumerate(reward_zero_cases, start=1):
        add_case(
            f"reward-zero case #{index}",
            case,
            case.get("context_messages", []),
        )
    if len(lines) == 5:
        lines.append("No matching cases were found in this artifact.")
    (output_dir / "human_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_results(
    input_paths: Iterable[Path],
    output_dir: Path,
    max_cases: int = 15,
) -> dict[str, Any]:
    """Analyze one or more results artifacts and write JSON reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    tool_classes = _tool_classification()
    simulations: list[dict[str, Any]] = []
    loaded_paths: list[str] = []
    seen_simulation_ids: set[str] = set()
    for path in input_paths:
        data = _load_results(path)
        loaded_paths.append(str(path))
        for simulation in data["simulations"]:
            simulation_id = str(simulation.get("id"))
            if simulation_id in seen_simulation_ids:
                continue
            seen_simulation_ids.add(simulation_id)
            simulations.append(simulation)

    metrics: list[dict[str, Any]] = []
    same_cases: list[dict[str, Any]] = []
    cross_cases: list[dict[str, Any]] = []
    failure_cases: list[dict[str, Any]] = []
    reward_zero_cases: list[dict[str, Any]] = []

    for simulation in simulations:
        messages = simulation.get("messages") or []
        records = _call_records(simulation, tool_classes)
        metrics.append(_task_metrics(simulation, records, tool_classes))
        same_groups = _same_message_groups(records)
        for group in same_groups.values():
            same_cases.append(
                {
                    **_base_case_fields(simulation),
                    "turn_indexes": sorted({record["assistant_turn_index"] for record in group}),
                    "tool_name": group[0]["tool_name"],
                    "normalized_arguments": group[0]["normalized_arguments"],
                    "tool_calls": [_record_context(record, messages) for record in group],
                    "context_messages": _context(messages, group[0]["message_index"]),
                    "observation": "same_message_exact_duplicate",
                }
            )
        cross_cases.extend(_cross_turn_case(records, messages, tool_classes))
        for record_index, record in enumerate(records):
            if record["parsed_status"] == "error":
                recovery = _failure_recovered(record_index, records, simulation)
                failure_cases.append(
                    {
                        **_base_case_fields(simulation),
                        "turn_indexes": [record["assistant_turn_index"]],
                        "tool_call": _record_context(record, messages),
                        "tool_result": record["tool_result"],
                        "context_messages": _context(messages, record["message_index"]),
                        "observation": "explicit_tool_error",
                        **recovery,
                    }
                )
        if (simulation.get("reward_info") or {}).get("reward") == 0:
            reward_zero_cases.append(
                {
                    **_base_case_fields(simulation),
                    "turn_indexes": sorted({record["assistant_turn_index"] for record in records}),
                    "tool_calls": [_record_context(record, messages) for record in records],
                    "context_messages": (
                        [_compact_message(message, index) for index, message in enumerate(messages[:2])]
                        + [
                            _compact_message(message, index)
                            for index, message in enumerate(messages[-2:], start=max(0, len(messages) - 2))
                        ]
                    ),
                    "observation": "reward_zero",
                }
            )

    def write_json(name: str, value: Any) -> None:
        (output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    aggregate = {
        "simulation_count": len(metrics),
        "task_count": len({metric["task_id"] for metric in metrics}),
        "final_reward_one_tasks": sum(metric["official_final_reward"] == 1 for metric in metrics),
        "final_reward_zero_tasks": sum(metric["official_final_reward"] == 0 for metric in metrics),
        "same_message_exact_duplicate_calls": sum(metric["same_message_exact_duplicate_calls"] for metric in metrics),
        "same_message_exact_duplicate_tasks": sum(
            metric["same_message_exact_duplicate_groups"] > 0 for metric in metrics
        ),
        "tasks_with_same_message_duplicates": sum(
            metric["same_message_exact_duplicate_groups"] > 0 for metric in metrics
        ),
        "tasks_with_cross_turn_repeats": sum(metric["cross_turn_exact_repeat_calls"] > 0 for metric in metrics),
        "cross_turn_exact_repeat_calls": sum(metric["cross_turn_exact_repeat_calls"] for metric in metrics),
        "cross_turn_repeat_after_state_change_calls": sum(
            metric["cross_turn_repeats_after_state_change"] for metric in metrics
        ),
        "cross_turn_repeat_after_state_change_tasks": sum(
            metric["cross_turn_repeats_after_state_change"] > 0 for metric in metrics
        ),
        "cross_turn_repeat_without_state_change_calls": sum(
            metric["cross_turn_repeats_without_state_change"] for metric in metrics
        ),
        "cross_turn_repeat_without_state_change_tasks": sum(
            metric["cross_turn_repeats_without_state_change"] > 0 for metric in metrics
        ),
        "tasks_with_tool_failures": sum(metric["tool_failure_count"] > 0 for metric in metrics),
        "explicit_tool_failure_count": sum(metric["tool_failure_count"] for metric in metrics),
        "reward_zero_tasks": sum(metric["official_final_reward"] == 0 for metric in metrics),
        "reward_zero_not_tool_failure_tasks": sum(
            metric["official_final_reward"] == 0 and metric["tool_failure_count"] == 0 for metric in metrics
        ),
        "reward_zero_but_db_reward_one_tasks": sum(
            metric["official_final_reward"] == 0 and (metric["reward_components"] or {}).get("DB") == 1.0
            for metric in metrics
        ),
        "normal_termination_count": sum(
            str(metric["termination_reason"]).lower() == "user_stop" for metric in metrics
        ),
        "infrastructure_error_count": sum(
            str(metric["termination_reason"]).lower() == "infrastructure_error" for metric in metrics
        ),
        "simulation_timeout_count": sum(str(metric["termination_reason"]).lower() == "timeout" for metric in metrics),
        "tool_failure_recovered_after_different_args_success": sum(
            case["different_arguments_success"] for case in failure_cases
        ),
        "tool_failure_recovered_after_tool_failure": sum(
            case["recovered_after_tool_failure"] for case in failure_cases
        ),
    }
    summary = {
        "analysis": "retail_observability_audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "input_artifacts": loaded_paths,
        "tool_classification": tool_classes,
        "normalization": {
            "dicts": "json.dumps(sort_keys=True, separators=(',', ':'))",
            "lists": "preserved in original order",
            "identifier_rewriting": False,
            "semantic_matching": False,
        },
        "metrics": metrics,
        "aggregate": aggregate,
        "case_limits": {
            "same_message_duplicates": max_cases,
            "cross_turn_repeats": max_cases,
            "tool_failures": max_cases,
            "reward_zero": max_cases,
        },
    }
    write_json("task_metrics.json", metrics)
    write_json("summary.json", summary)
    write_json("cases_same_message_duplicates.json", same_cases[:max_cases])
    write_json("cases_cross_turn_repeats.json", cross_cases[:max_cases])
    write_json("cases_tool_failures.json", failure_cases[:max_cases])
    write_json("cases_reward_zero.json", reward_zero_cases[:max_cases])
    _write_human_audit(
        output_dir,
        same_cases[:max_cases],
        cross_cases[:max_cases],
        failure_cases[:max_cases],
        reward_zero_cases[:max_cases],
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-cases", type=int, default=15)
    args = parser.parse_args()
    summary = analyze_results(args.input, args.output_dir, args.max_cases)
    print(json.dumps(summary["aggregate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
