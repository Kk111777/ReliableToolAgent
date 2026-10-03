"""Offline contracts for a bounded, paired native-retail study (stdlib only).

Reference actions are diagnostics, never an alternative reward or Agent input.
The analyzer deliberately keeps unknown tool results and missing usage unknown.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ANALYZER_VERSION = "retail-events-v1"
WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}
CONFIRMATION = re.compile(r"\b(?:yes|i confirm|confirmed|please proceed|go ahead)\b", re.IGNORECASE)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def append_json(path: Path, value: Any) -> None:
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # A torn last line must be repaired explicitly, never silently dropped.
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@dataclass(frozen=True)
class Slot:
    phase: str
    task_id: str
    condition: str
    trial: int
    seed: int

    @property
    def key(self) -> str:
        return f"{self.phase}-t{self.task_id}-{self.condition}-r{self.trial}"

    def as_dict(self) -> dict:
        return dict(
            phase=self.phase,
            task_id=self.task_id,
            condition=self.condition,
            trial=self.trial,
            seed=self.seed,
            slot_id=self.key,
        )


def schedule(manifest: dict, phase: str) -> list[Slot]:
    if phase not in {"smoke", "formal"}:
        raise ValueError("phase must be smoke or formal")
    rng = random.Random(manifest["base_seed"])
    seeds = [rng.randint(0, 1_000_000) for _ in range(manifest["trials"])]
    tasks = manifest["smoke_tasks"] if phase == "smoke" else manifest["task_ids"]
    trials = 1 if phase == "smoke" else manifest["trials"]
    result = []
    # Alternate pair order to reduce fixed order/time confounding; never reshuffle on resume.
    for task_index, task in enumerate(tasks):
        for trial in range(trials):
            conditions = list(manifest["conditions"])
            if (task_index + trial) % 2:
                conditions.reverse()
            for condition in conditions:
                result.append(Slot(phase, str(task), condition, trial, seeds[trial]))
    return result


def validate_manifest(manifest: dict) -> None:
    if manifest["schema_version"] != 1 or manifest["analyzer_version"] != ANALYZER_VERSION:
        raise ValueError("unsupported manifest/analyzer version")
    if manifest["conditions"] != ["U0", "U2"] or manifest["trials"] != 3:
        raise ValueError("this protocol requires U0/U2 and three paired trials")
    if len(set(manifest["task_ids"])) != len(manifest["task_ids"]):
        raise ValueError("duplicate task IDs")
    if set(manifest["task_ids"]) & set(manifest["observed_local_task_ids"]):
        raise ValueError("holdout overlaps retained local development results")
    if manifest["model_args"]["num_retries"] != 3 or manifest["deadline_seconds"] != 600:
        raise ValueError("unexpected retry/deadline contract")
    expected = manifest["schedule_sha256"]
    actual = digest([slot.as_dict() for slot in schedule(manifest, "formal")])
    if expected != actual:
        raise ValueError("schedule digest mismatch")


def estimate_rmb(model: str, prompt: int, completion: int) -> float:
    if min(prompt, completion) < 0 or prompt > 1_000_000:
        raise ValueError("usage outside frozen tariff")
    name = model.removeprefix("openai/")
    if name == "qwen3.5-flash-2026-02-23":
        input_rate, output_rate = (0.2, 2) if prompt <= 128_000 else (0.8, 8) if prompt <= 256_000 else (1.2, 12)
    elif name in {"qwen3.8-max-2026-09-02", "qwen3.8-max-0902"}:
        input_rate, output_rate = 12, 36
    else:
        raise ValueError("no verified tariff for model")
    return (prompt * input_rate + completion * output_rate) / 1_000_000


def usage_cost(model: str, usage: dict | None) -> float | None:
    if not usage:
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return estimate_rmb(model, prompt, completion)


def budget_totals(events: list[dict]) -> dict:
    # An interrupted started call retains its full pre-call reservation.
    calls: dict[int, dict] = {}
    for event in events:
        calls[event["call_index"]] = event
    known = [row.get("known_list_price_rmb") for row in calls.values()]
    return {
        "known_list_price_rmb": sum(x for x in known if x is not None),
        "budget_debit_rmb": sum(row["budget_debit_rmb"] for row in calls.values()),
        "calls": len(calls),
        "usage_unknown_calls": sum(x is None for x in known),
    }


def call_events(simulation: dict) -> list[dict]:
    """Join by ID within the following response window, flag ambiguous/missing IDs.

    A global ID dictionary can join to a later call when a provider reuses an ID.
    A response cannot be consumed twice. Repeated IDs in one call batch are unknown.
    """
    messages = simulation.get("messages") or []
    events = []
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls") or []
        id_counts = Counter(call.get("id") for call in calls)
        end = next(
            (j for j in range(index + 1, len(messages)) if messages[j].get("role") in {"assistant", "user"}),
            len(messages),
        )
        for call_index, call in enumerate(calls):
            call_id = call.get("id")
            matches = [
                (j, messages[j])
                for j in range(index + 1, end)
                if messages[j].get("role") == "tool" and messages[j].get("id") == call_id
            ]
            matched = bool(call_id) and id_counts[call_id] == 1 and len(matches) == 1
            result_index, result = matches[0] if matched else (None, {})
            error = result.get("error")
            status = "error" if error is True else "success" if error is False else "unknown"
            events.append(
                {
                    "message_index": index,
                    "call_index": call_index,
                    "call_id": call_id,
                    "tool_name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                    "arguments_key": canonical(call.get("arguments") or {}),
                    "tool_type": "write" if call.get("name") in WRITE_TOOLS else "other",
                    "result_message_index": result_index,
                    "status": status,
                    "join_ambiguous": not matched,
                }
            )
    return events


def terminal_marker(text: str) -> str:
    if "###TRANSFER###" in text:
        return "TRANSFER"
    if "###STOP###" in text:
        return "STOP"
    return "NONE"


def analyze_simulation(simulation: dict) -> dict:
    messages = simulation.get("messages") or []
    events = call_events(simulation)
    groups = Counter((e["message_index"], e["tool_name"], e["arguments_key"]) for e in events)
    previous: dict[tuple, dict] = {}
    cross = 0
    for event in events:
        key = (event["tool_name"], event["arguments_key"])
        if key in previous and previous[key]["message_index"] != event["message_index"]:
            cross += 1
        previous[key] = event
    reward = simulation.get("reward_info") or {}
    checks = reward.get("action_checks") or []
    expected = {
        (check["action"]["name"], canonical(check["action"].get("arguments") or {}))
        for check in checks
        if check.get("tool_type") == "write" and check.get("action")
    }
    observed = {
        (e["tool_name"], e["arguments_key"]) for e in events if e["tool_type"] == "write" and e["status"] == "success"
    }
    users = [(i, str(m.get("content") or "")) for i, m in enumerate(messages) if m.get("role") == "user"]
    final_user = users[-1] if users else (-1, "")
    confirmations = [(i, text) for i, text in users if CONFIRMATION.search(text)]
    terminal = terminal_marker(final_user[1])
    terminal_confirmation = bool(CONFIRMATION.search(final_user[1]))
    agent_after_terminal = any(m.get("role") == "assistant" for m in messages[final_user[0] + 1 :])
    latest = confirmations[-1][0] if confirmations else None
    received = latest is not None and any(m.get("role") == "assistant" for m in messages[latest + 1 :])
    breakdown = reward.get("reward_breakdown") or {}
    return {
        "analyzer_version": ANALYZER_VERSION,
        "official_final_reward": reward.get("reward"),
        "db_reward": breakdown.get("DB"),
        "nl_reward": breakdown.get("NL_ASSERTION"),
        "communicate_reward": breakdown.get("COMMUNICATE"),
        "tool_calls": len(events),
        "explicit_tool_errors": sum(e["status"] == "error" for e in events),
        "unknown_tool_results": sum(e["status"] == "unknown" for e in events),
        "same_message_duplicate_calls": sum(n for n in groups.values() if n >= 2),
        "same_message_excess_calls": sum(n - 1 for n in groups.values() if n >= 2),
        "cross_turn_exact_repeats": cross,
        "expected_write_key_count": len(expected),
        "expected_write_matched_count": len(expected & observed),
        "any_expected_write_observed": bool(expected & observed) if expected else None,
        "all_expected_writes_observed": expected <= observed if expected else None,
        "terminal_marker": terminal,
        "terminal_confirmation_candidate": terminal_confirmation,
        "agent_after_terminal_user": agent_after_terminal,
        "latest_confirmation_received_candidate": received,
        "terminal_before_reference_write_candidate": bool(expected and terminal != "NONE" and not expected & observed),
        "confirmation_terminal_before_write_candidate": bool(
            expected
            and terminal != "NONE"
            and terminal_confirmation
            and not agent_after_terminal
            and not expected & observed
        ),
        "write_after_latest_confirmation_candidate": any(
            e["tool_type"] == "write"
            and e["status"] == "success"
            and latest is not None
            and e["message_index"] > latest
            for e in events
        ),
        "duration_seconds": simulation.get("duration"),
        "termination_reason": simulation.get("termination_reason"),
    }


def paired_bootstrap(
    rows: list[dict], *, samples: int = 5000, seed: int = 20261003, clusters: dict[str, str] | None = None
) -> dict:
    """Cluster by task, keep all three matched trials within each resampled task."""
    by_slot = {(str(r["task_id"]), r["trial"], r["condition"]): r for r in rows if r["attempt"] == 0}
    if len(by_slot) != sum(r["attempt"] == 0 for r in rows):
        raise ValueError("duplicate primary slots")
    differences: dict[str, list[float]] = defaultdict(list)
    missing = []
    task_trials = sorted({(task, trial) for task, trial, _ in by_slot})
    for task, trial in task_trials:
        a, b = by_slot.get((task, trial, "U0")), by_slot.get((task, trial, "U2"))
        if not a or not b or a["status"] != "valid" or b["status"] != "valid":
            missing.append([task, trial])
            continue
        differences[task].append(b["metrics"]["official_final_reward"] - a["metrics"]["official_final_reward"])
    # Require complete 3-trial tasks for the task-level primary CI.
    complete = {task: sum(values) / 3 for task, values in differences.items() if len(values) == 3}
    if not complete:
        return {
            "complete_tasks": 0,
            "missing_pairs": missing,
            "mean_difference_U2_minus_U0": None,
            "confidence_interval_95": None,
            "bootstrap_samples": samples,
            "seed": seed,
        }
    values = list(complete.values())
    rng = random.Random(seed)
    groups = defaultdict(list)
    for task, value in complete.items():
        groups[clusters.get(task, task) if clusters else task].append(value)
    group_values = list(groups.values())
    draws = []
    for _ in range(samples):
        sampled = [value for group in rng.choices(group_values, k=len(group_values)) for value in group]
        draws.append(sum(sampled) / len(sampled))
    draws.sort()
    return {
        "complete_tasks": len(values),
        "resampling_clusters": len(groups),
        "valid_trial_pairs": sum(map(len, differences.values())),
        "missing_pairs": missing,
        "mean_difference_U2_minus_U0": sum(values) / len(values),
        "confidence_interval_95": [draws[int(0.025 * samples)], draws[min(samples - 1, int(0.975 * samples))]],
        "bootstrap_samples": samples,
        "seed": seed,
        "unit": "user-entity cluster; all task/trial pairs travel together"
        if clusters
        else "task; all three trial pairs travel together",
    }
