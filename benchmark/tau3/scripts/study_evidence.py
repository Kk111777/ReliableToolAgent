"""Export compact evidence and recompute it offline; never import a model SDK."""

from __future__ import annotations

import argparse
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from analyze_frozen_study import aggregate
from frozen_study import (
    analyze_simulation,
    budget_totals,
    digest,
    file_sha,
    paired_bootstrap,
    read_json,
    read_jsonl,
    schedule,
    validate_manifest,
    write_json,
)


ROOT = Path(__file__).resolve().parents[3]
ROLES = ("agent", "user", "evaluator")
STATUS = {"valid", "infrastructure_error", "timeout", "budget_stop", "interrupted"}
METRICS = set(analyze_simulation({}))
BILLING = {"calls", "known_list_price_rmb", "budget_debit_rmb", "usage_unknown_calls"}
ARTIFACTS = {"job.json", "simulation.json", "calls.jsonl", "requests.jsonl", "evaluator.jsonl"}
ROW_FIELDS = {
    "study_id",
    "slot_id",
    "phase",
    "task_id",
    "condition",
    "trial",
    "seed",
    "attempt",
    "status",
    "error_class",
    "stage",
    "wall_seconds",
    "simulation_id",
    "metrics",
    "billing",
    "outcome_sha256",
    "artifact_sha256",
    "usage_by_role",
}
BOUNDARY = (
    "Reported per-attempt metrics support aggregate recomputation. Full trajectories remain local; "
    "hashes identify retained evidence but do not independently verify official rewards. "
    "HTTP requests are observed; lower transport connection attempts are unknown. "
    "Reasoning is part of completion tokens, not an additional charge. Prices are list-price estimates, not invoices."
)


def finite_number(value, *, integer: bool = False) -> bool:
    return type(value) in ({int} if integer else {int, float}) and math.isfinite(value) and value >= 0


def usage_by_role(events: list[dict]) -> dict:
    """Count each observed HTTP request once, including failed or unfinished ones."""
    latest = {event["call_index"]: event for event in events}
    result = {}
    for role in ROLES:
        requests = [event for event in latest.values() if event["role"] == role]
        measured = [event for event in requests if event.get("known_list_price_rmb") is not None]
        usage = [event["usage"] for event in measured]
        reasoning = [(u.get("completion_tokens_details") or {}).get("reasoning_tokens") for u in usage]
        cached = [(u.get("prompt_tokens_details") or {}).get("cached_tokens") for u in usage]
        result[role] = {
            "observed_http_requests": len(requests),
            "with_usage": len(measured),
            "missing_usage_requests": len(requests) - len(measured),
            "prompt_tokens_known": sum(u["prompt_tokens"] for u in usage),
            "completion_tokens_known": sum(u["completion_tokens"] for u in usage),
            "reasoning_tokens_known": sum(v for v in reasoning if v is not None),
            "reasoning_usage_present_requests": sum(v is not None for v in reasoning),
            "cached_input_tokens_known": sum(v for v in cached if v is not None),
            "cache_usage_present_requests": sum(v is not None for v in cached),
            "known_list_price_rmb": sum(event["known_list_price_rmb"] for event in measured),
            "conservative_budget_debit_rmb": sum(event["budget_debit_rmb"] for event in requests),
        }
    if sum(row["observed_http_requests"] for row in result.values()) != len(latest):
        raise ValueError("unknown billing role")
    return result


def task_audit(manifest: dict) -> dict:
    name = "retail-replication-v1" if manifest.get("official_split") == "train" else "retail-holdout-v1"
    relative = f"benchmark/tau3/studies/{name}/task_audit.json"
    if manifest.get("task_audit_relative_path", relative) != relative:
        raise ValueError("unexpected task audit path")
    if file_sha(ROOT / relative) != manifest["source_sha256"][relative]:
        raise ValueError("task audit disagrees with frozen source hash")
    return read_json(ROOT / relative)


def analysis_sources(manifest: dict) -> dict:
    """Verify available frozen public inputs; private raw hashes stay provenance."""
    sources = {}
    for relative, expected in manifest["source_sha256"].items():
        if not relative.startswith(("benchmark/tau3/", "reports/")):
            continue
        if ".." in Path(relative).parts or file_sha(ROOT / relative) != expected:
            raise ValueError("public frozen source changed")
        sources[relative] = expected
    sources[str(Path(__file__).resolve().relative_to(ROOT))] = file_sha(Path(__file__))
    return sources


def compact_row(row: dict, requests: list[dict]) -> dict:
    if set(row["metrics"]) - METRICS or set(row["billing"]) != BILLING:
        raise ValueError("unexpected metric/billing fields")
    compact = {key: value for key, value in row.items() if key in ROW_FIELDS}
    if requests and budget_totals(requests) != row["billing"]:
        raise ValueError("request usage disagrees with attempt billing")
    if not requests and row["billing"]["calls"]:
        raise ValueError("HTTP request evidence missing")
    compact["usage_by_role"] = usage_by_role(requests)
    return compact


def validate_metrics(metrics: dict) -> None:
    """Accept only the primitive values returned by the frozen event analyzer."""
    counts = {
        "tool_calls",
        "explicit_tool_errors",
        "unknown_tool_results",
        "same_message_duplicate_calls",
        "same_message_excess_calls",
        "cross_turn_exact_repeats",
        "expected_write_key_count",
        "expected_write_matched_count",
    }
    rewards = {"official_final_reward", "db_reward", "nl_reward", "communicate_reward"}
    for key, value in metrics.items():
        if key in counts:
            valid = finite_number(value, integer=True)
        elif key in rewards:
            valid = value is None or (finite_number(value) and value <= 1)
        elif key == "duration_seconds":
            valid = value is None or finite_number(value)
        elif key == "analyzer_version":
            valid = value == "retail-events-v1"
        elif key == "terminal_marker":
            valid = value in {"NONE", "STOP", "TRANSFER"}
        elif key == "termination_reason":
            valid = value in {
                None,
                "None",  # The frozen worker stringifies an unfinished checkpoint reason.
                "user_stop",
                "agent_stop",
                "max_steps",
                "timeout",
                "too_many_errors",
                "agent_error",
                "user_error",
                "infrastructure_error",
                "context_window_exceeded",
                "unexpected_error",
            }
        else:
            valid = type(value) is bool or (
                value is None and key in {"any_expected_write_observed", "all_expected_writes_observed"}
            )
        if not valid:
            raise ValueError(f"invalid primitive event metric: {key}")


@dataclass
class EvidenceBundle:
    manifest: dict
    rows: list[dict]

    def validate(self) -> None:
        validate_manifest(self.manifest)
        analysis_sources(self.manifest)
        task_audit(self.manifest)
        slots = {slot.key: slot.as_dict() for phase in ("smoke", "formal") for slot in schedule(self.manifest, phase)}
        seen = {}
        for row in self.rows:
            if set(row) - ROW_FIELDS or row["slot_id"] not in slots:
                raise ValueError("unexpected public field or slot")
            if any(row[key] != value for key, value in slots[row["slot_id"]].items()):
                raise ValueError("slot identity or paired seed mismatch")
            expected_ids = {self.manifest["study_id"]}
            if row["phase"] == "smoke" and self.manifest.get("accepted_smoke_study_id"):
                expected_ids.add(self.manifest["accepted_smoke_study_id"])
            if row["study_id"] not in expected_ids:
                raise ValueError("attempt belongs to another study")
            if not finite_number(row["attempt"], integer=True) or row["status"] not in STATUS:
                raise ValueError("invalid attempt identity/status")
            key = (row["slot_id"], row["attempt"])
            if key in seen:
                raise ValueError("duplicate attempt identity")
            seen[key] = row
            if row.get("error_class") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", row["error_class"]):
                raise ValueError("exception message is not a public error class")
            if set(row["metrics"]) - METRICS or set(row["billing"]) != BILLING:
                raise ValueError("unexpected metric/billing field")
            validate_metrics(row["metrics"])
            if any(not finite_number(value) for value in row["billing"].values()):
                raise ValueError("negative or nonfinite billing")
            if any(not finite_number(row["billing"][key], integer=True) for key in ("calls", "usage_unknown_calls")):
                raise ValueError("request counts must be nonnegative integers")
            reward = row["metrics"].get("official_final_reward")
            if row["status"] == "valid" and (not finite_number(reward) or reward > 1):
                raise ValueError("valid attempt has no official reward")
            if row.get("stage") not in {None, "simulation", "evaluation"}:
                raise ValueError("unexpected execution stage")
            if row.get("wall_seconds") is not None and not finite_number(row["wall_seconds"]):
                raise ValueError("invalid elapsed time")
            for value in [row["outcome_sha256"], *row["artifact_sha256"].values()]:
                if not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise ValueError("invalid evidence hash")
            if set(row["artifact_sha256"]) - ARTIFACTS:
                raise ValueError("unexpected raw artifact name")
            if set(row["usage_by_role"]) != set(ROLES):
                raise ValueError("missing usage role")
            for role in ROLES:
                usage = row["usage_by_role"][role]
                if set(usage) != set(usage_by_role([])[role]):
                    raise ValueError("unexpected public usage field")
                if usage["with_usage"] + usage["missing_usage_requests"] != usage["observed_http_requests"]:
                    raise ValueError("usage coverage disagrees with request count")
            if any(not finite_number(v) for role in row["usage_by_role"].values() for v in role.values()):
                raise ValueError("invalid public usage value")
            totals = {
                "calls": "observed_http_requests",
                "usage_unknown_calls": "missing_usage_requests",
                "known_list_price_rmb": "known_list_price_rmb",
                "budget_debit_rmb": "conservative_budget_debit_rmb",
            }
            for key, field in totals.items():
                if not math.isclose(
                    sum(v[field] for v in row["usage_by_role"].values()), row["billing"][key], abs_tol=1e-10
                ):
                    raise ValueError("public role totals disagree with billing")
        for row in self.rows:
            for previous in range(row["attempt"]):
                earlier = seen.get((row["slot_id"], previous))
                if earlier is None or earlier["status"] in {"valid", "budget_stop"}:
                    raise ValueError("retry without retained invalid first attempt")

    def recompute(self) -> dict:
        self.validate()
        result = aggregate(self.manifest, self.rows)
        audit = task_audit(self.manifest)
        primary = [row for row in self.rows if row["phase"] == "formal" and row["attempt"] == 0]
        expected = {slot.key for slot in schedule(self.manifest, "formal")}
        result["unstarted_primary_slots"] = sorted(expected - {row["slot_id"] for row in primary})
        if self.manifest.get("official_split") == "train":
            families = {}
            for family in sorted({task["stratum"] for task in audit["tasks"]}):
                ids = {task["task_id"] for task in audit["tasks"] if task["stratum"] == family}
                families[family] = {}
                for condition in self.manifest["conditions"]:
                    valid = [
                        r
                        for r in primary
                        if r["task_id"] in ids and r["condition"] == condition and r["status"] == "valid"
                    ]
                    families[family][condition] = {
                        "valid": len(valid),
                        "success": sum(r["metrics"]["official_final_reward"] == 1 for r in valid),
                    }
            result["write_family_sensitivity"] = families
            result["user_entity_cluster_bootstrap_sensitivity"] = paired_bootstrap(
                primary, clusters={task["task_id"]: task["user_entity_cluster"] for task in audit["tasks"]}
            )
            result.pop("exclude_near_duplicate_task38_sensitivity", None)
            result["official_split"] = "train; stratified supplementary sample, not an official test score"
            result["interpretation"] = "Separate replication; do not pool with the test-split primary study"
        result["usage_all_phases_by_role"] = {
            role: {key: sum(row["usage_by_role"][role][key] for row in self.rows) for key in usage_by_role([])[role]}
            for role in ROLES
        }
        result["first_attempt_wall_seconds_by_condition"] = {}
        for condition in self.manifest["conditions"]:
            values = sorted(
                row["wall_seconds"]
                for row in primary
                if row["condition"] == condition and row.get("wall_seconds") is not None
            )
            result["first_attempt_wall_seconds_by_condition"][condition] = {
                "measured": len(values),
                "median": statistics.median(values) if values else None,
                "p95_nearest_rank": values[math.ceil(0.95 * len(values)) - 1] if values else None,
            }
        result["evidence_boundary"] = BOUNDARY
        return result

    def save(self, destination: Path, *, allow_incomplete: bool = False) -> dict:
        summary = self.recompute()
        if not summary["complete"] and not allow_incomplete:
            raise ValueError("study is incomplete; use --allow-incomplete only for a labeled local diagnostic")
        payload = {
            "schema_version": 1,
            "manifest": self.manifest,
            "rows": self.rows,
            "summary": summary,
            "analysis_sources_sha256": analysis_sources(self.manifest),
        }
        payload["payload_sha256"] = digest(payload)
        write_json(destination, payload, exclusive=True)
        return summary


def export(source: Path, destination: Path, *, allow_incomplete: bool = False) -> dict:
    manifest = read_json(source / "manifest.json")
    rows = read_jsonl(source / "attempts.jsonl")
    compact = []
    for row in rows:
        outcome = (source / row["outcome_path"]).resolve()
        if not outcome.is_relative_to(source.resolve()):
            raise ValueError("raw outcome path escapes study directory")
        if file_sha(outcome) != row["outcome_sha256"]:
            raise ValueError("raw outcome changed")
        if any(row.get(key) != value for key, value in read_json(outcome).items()):
            raise ValueError("ledger disagrees with retained outcome")
        for name, expected in row["artifact_sha256"].items():
            if name not in ARTIFACTS or file_sha(outcome.parent / name) != expected:
                raise ValueError("raw attempt artifact changed")
        simulation = outcome.parent / "simulation.json"
        if simulation.exists() and analyze_simulation(read_json(simulation)) != row["metrics"]:
            raise ValueError("event metrics disagree with retained trajectory")
        compact.append(compact_row(row, read_jsonl(outcome.parent / "requests.jsonl")))
    return EvidenceBundle(manifest, compact).save(destination, allow_incomplete=allow_incomplete)


def audit(path: Path) -> dict:
    payload = read_json(path)
    if (
        set(payload) != {"schema_version", "manifest", "rows", "summary", "payload_sha256", "analysis_sources_sha256"}
        or payload["schema_version"] != 1
    ):
        raise ValueError("unexpected public bundle schema")
    if digest({k: v for k, v in payload.items() if k != "payload_sha256"}) != payload["payload_sha256"]:
        raise ValueError("public bundle hash mismatch")
    if payload["analysis_sources_sha256"] != analysis_sources(payload["manifest"]):
        raise ValueError("public analysis source version mismatch")
    summary = EvidenceBundle(payload["manifest"], payload["rows"]).recompute()
    if summary != payload["summary"]:
        raise ValueError("reported summary disagrees with compact rows")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export", help="verify retained raw evidence before compact export")
    exporter.add_argument("--input", required=True, type=Path)
    exporter.add_argument("--output", required=True, type=Path)
    exporter.add_argument("--allow-incomplete", action="store_true")
    checker = commands.add_parser("audit", help="offline aggregate/interval recomputation from a compact bundle")
    checker.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    result = (
        export(args.input, args.output, allow_incomplete=args.allow_incomplete)
        if args.command == "export"
        else audit(args.input)
    )
    print({key: result[key] for key in ("study_id", "complete", "finished_primary_slots", "planned_primary_slots")})


if __name__ == "__main__":
    main()
