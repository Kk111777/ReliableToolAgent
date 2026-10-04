"""Separate reference-action diagnostics; never rewrite frozen rewards or v1 metrics.

Successful tool responses are matched one-to-one to reference WRITE occurrences.
This is an exact-reference diagnostic, not a task-success evaluator: equivalent
business actions can have different arguments, and an error/unknown result does
not prove that no state change occurred. Terminal markers are literal protocol
markers in the final observed User message, not inferred intent.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from frozen_study import (
    analyze_simulation,
    call_events,
    canonical,
    digest,
    file_sha,
    read_json,
    read_jsonl,
    write_json,
)


MEASUREMENT_VERSION = "retail-reference-events-v2"
BOUNDARY = (
    "Offline exact-reference diagnostics, not official scores or causal evidence. "
    "A successful response can match only one reference WRITE occurrence. "
    "Unknown results remain unmatched but do not prove a failed state change. "
    "Terminal markers refer to the final observed User message. "
    "No independent human annotation is claimed; frozen v1 metrics are unchanged."
)
V1_COMPARISON_FIELDS = (
    "expected_write_key_count",
    "expected_write_matched_count",
    "terminal_before_reference_write_candidate",
    "agent_after_terminal_user",
)


@dataclass(frozen=True)
class ReferenceWriteMeasurement:
    simulation: dict

    def reference_actions(self) -> Counter | None:
        reward = self.simulation.get("reward_info")
        checks = reward.get("action_checks") if isinstance(reward, dict) else None
        if not isinstance(checks, list):
            return None
        references: Counter = Counter()
        for check in checks:
            if not isinstance(check, dict) or check.get("tool_type") not in {"write", "read", "generic"}:
                # Missing taxonomy could hide a WRITE, so do not infer an empty set.
                return None
            if check["tool_type"] != "write":
                continue
            action = check.get("action")
            if not isinstance(action, dict) or not isinstance(action.get("name"), str) or not action["name"]:
                return None
            if not isinstance(action.get("arguments"), dict):
                return None
            references[(action["name"], canonical(action["arguments"]))] += 1
        return references

    @staticmethod
    def counts(references: Counter | None, events: list[dict] | None) -> dict:
        empty = {"matched": None, "missing": None, "unknown_result_candidates": None, "completion": "unknown"}
        if references is None or events is None:
            return empty
        successful = Counter(
            (event["tool_name"], event["arguments_key"])
            for event in events
            if event["status"] == "success" and event["arguments_available"]
        )
        unknown = Counter(
            (event["tool_name"], event["arguments_key"])
            for event in events
            if event["status"] == "unknown" and event["arguments_available"]
        )
        matched = sum((references & successful).values())
        remaining = references - successful
        missing = sum(remaining.values())
        total = sum(references.values())
        completion = "no_reference_writes" if not total else "all" if not missing else "partial" if matched else "none"
        return {
            "matched": matched,
            "missing": missing,
            "unknown_result_candidates": sum((remaining & unknown).values()),
            "completion": completion,
        }

    def measure(self) -> dict:
        messages = self.simulation.get("messages")
        trace_available = isinstance(messages, list)
        if trace_available and any(not isinstance(message, dict) for message in messages):
            raise ValueError("messages must contain objects")
        events = call_events(self.simulation) if trace_available else None
        if events is not None:
            for event in events:
                call = messages[event["message_index"]]["tool_calls"][event["call_index"]]
                event["arguments_available"] = isinstance(call.get("arguments"), dict)
        users = [
            (index, message)
            for index, message in enumerate(messages if trace_available else [])
            if message.get("role") == "user"
        ]
        last_user_index, last_user = users[-1] if users else (None, {})
        content = last_user.get("content")
        content_available = isinstance(content, str)
        marker = (
            "TRANSFER"
            if content_available and "###TRANSFER###" in content
            else "STOP"
            if content_available and "###STOP###" in content
            else "NONE"
        )
        terminal_present = marker != "NONE" if trace_available and (not users or content_available) else None
        after_terminal = (
            any(message.get("role") == "assistant" for message in messages[last_user_index + 1 :])
            if terminal_present
            else None
        )
        references = self.reference_actions()
        full = self.counts(references, events)
        # A success is observed before the terminal only when its joined response
        # also precedes it. An attempted call alone cannot satisfy a reference.
        before_events = (
            [
                event
                for event in events
                if event["message_index"] < last_user_index
                and (event["result_message_index"] is None or event["result_message_index"] < last_user_index)
            ]
            if terminal_present and events is not None
            else None
        )
        before = self.counts(references, before_events)
        candidate = (
            before["missing"] > 0
            if terminal_present and before["missing"] is not None
            else False
            if terminal_present is False
            else None
        )
        return {
            "measurement_version": MEASUREMENT_VERSION,
            "message_trace_available": trace_available,
            "reference_write_actions_available": references is not None,
            "reference_write_actions_expected": sum(references.values()) if references is not None else None,
            "reference_write_actions_matched": full["matched"],
            "reference_write_actions_missing": full["missing"],
            "reference_write_unknown_result_candidates": full["unknown_result_candidates"],
            "reference_write_completion": full["completion"],
            "final_user_message_index": last_user_index,
            "final_user_content_available": content_available if users else None,
            "terminal_user_present": terminal_present,
            "final_user_terminal_marker": marker if terminal_present is not None else None,
            "agent_after_terminal_user_v2": after_terminal,
            "reference_write_actions_matched_before_terminal": before["matched"],
            "reference_write_actions_missing_at_terminal": before["missing"],
            "reference_write_unknown_result_candidates_at_terminal": before["unknown_result_candidates"],
            "reference_write_completion_at_terminal": before["completion"],
            "terminal_with_missing_reference_writes_candidate": candidate,
        }


@dataclass(frozen=True)
class MeasurementAudit:
    """Audit retained source bytes and export only scalar diagnostic metadata."""

    source: Path
    case_index: Path | None = None
    evidence: Path | None = None

    def build(self) -> dict:
        manifest_path = self.source / "manifest.json"
        rows = read_jsonl(self.source / "attempts.jsonl")
        primary = [row for row in rows if row["phase"] == "formal" and row["attempt"] == 0]
        identities = [(row["study_id"], row["slot_id"], row["attempt"]) for row in primary]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate first-attempt identity")
        measured = []
        for row in sorted(primary, key=lambda item: item["slot_id"]):
            outcome_path = self.source / row["outcome_path"]
            if file_sha(outcome_path) != row["outcome_sha256"]:
                raise ValueError("outcome digest mismatch")
            outcome = read_json(outcome_path)
            if any(
                outcome.get(key) != row[key]
                for key in ("study_id", "slot_id", "phase", "attempt", "status", "metrics")
            ):
                raise ValueError("ledger disagrees with retained outcome")
            for name, expected in row["artifact_sha256"].items():
                if file_sha(outcome_path.parent / name) != expected:
                    raise ValueError("artifact digest mismatch")
            simulation_path = outcome_path.parent / "simulation.json"
            if "simulation.json" not in row["artifact_sha256"]:
                raise ValueError("missing source simulation digest")
            simulation = read_json(simulation_path)
            old = analyze_simulation(simulation)
            if old != row["metrics"]:
                raise ValueError("frozen metrics disagree with source")
            measured.append(
                {
                    **{key: row[key] for key in ("study_id", "slot_id", "attempt", "status", "outcome_sha256")},
                    "simulation_sha256": file_sha(simulation_path),
                    "frozen_v1": {key: old[key] for key in V1_COMPARISON_FIELDS},
                    "measurement_v2": ReferenceWriteMeasurement(simulation).measure(),
                }
            )
        cases = []
        if self.case_index:
            index = read_json(self.case_index)
            for case in index["cases"]:
                matches = [
                    row for row in measured if all(row[key] == case[key] for key in ("study_id", "slot_id", "attempt"))
                ]
                if len(matches) != 1:
                    raise ValueError("case identity missing from first attempts")
                match = matches[0]
                if any(match[key] != case[key] for key in ("outcome_sha256", "simulation_sha256")):
                    raise ValueError("case source digest mismatch")
                cases.append({"case_id": case["case_id"], **match})
        report = {
            "schema_version": 1,
            "measurement_version": MEASUREMENT_VERSION,
            "boundary": BOUNDARY,
            "source_manifest_file_sha256": file_sha(manifest_path),
            "source_manifest_sha256": digest(read_json(manifest_path)),
            "source_attempts_file_sha256": file_sha(self.source / "attempts.jsonl"),
            "measurement_source_sha256": file_sha(Path(__file__)),
            "frozen_source_sha256": file_sha(Path(__file__).with_name("frozen_study.py")),
            "source_case_index_sha256": file_sha(self.case_index) if self.case_index else None,
            "source_public_evidence_sha256": file_sha(self.evidence) if self.evidence else None,
            "first_attempts": len(measured),
            "first_attempt_status_counts": dict(Counter(row["status"] for row in measured)),
            "summary_all_first_attempts": self.summarize(measured),
            "summary_valid_first_attempts": self.summarize([row for row in measured if row["status"] == "valid"]),
            "rows": measured,
            "selected_cases": cases,
        }
        report["payload_sha256"] = digest(report)
        return report

    @staticmethod
    def summarize(rows: list[dict]) -> dict:
        metrics = [row["measurement_v2"] for row in rows]
        known = [item for item in metrics if item["terminal_with_missing_reference_writes_candidate"] is not None]
        return {
            "attempts": len(rows),
            "known_candidate_denominator": len(known),
            "unknown_candidate_count": len(metrics) - len(known),
            "terminal_with_missing_reference_writes_candidates": sum(
                item["terminal_with_missing_reference_writes_candidate"] for item in known
            ),
            "partial_completion_terminal_candidates": sum(
                item["terminal_with_missing_reference_writes_candidate"] is True
                and item["reference_write_completion_at_terminal"] == "partial"
                for item in metrics
            ),
            "v1_terminal_before_reference_write_candidates": sum(
                row["frozen_v1"]["terminal_before_reference_write_candidate"] for row in rows
            ),
            "v1_agent_after_terminal_without_terminal_user": sum(
                row["frozen_v1"]["agent_after_terminal_user"]
                and row["measurement_v2"]["terminal_user_present"] is False
                for row in rows
            ),
            "reference_diagnostic_available": sum(item["reference_write_actions_available"] for item in metrics),
            "reference_completion_counts": dict(Counter(item["reference_write_completion"] for item in metrics)),
        }


@dataclass(frozen=True)
class CompactMeasurementAudit:
    """Recompute public summaries and provenance joins, not private semantics."""

    path: Path
    evidence: Path
    case_index: Path | None = None

    @staticmethod
    def identity(row: dict) -> tuple:
        return row["study_id"], row["slot_id"], row["attempt"]

    @staticmethod
    def check_metrics(metrics: dict) -> None:
        expected_fields = set(ReferenceWriteMeasurement({}).measure())
        if not isinstance(metrics, dict) or set(metrics) != expected_fields:
            raise ValueError("unexpected v2 metric fields")
        if metrics["measurement_version"] != MEASUREMENT_VERSION:
            raise ValueError("unknown measurement version")
        boolean_fields = {
            "message_trace_available",
            "reference_write_actions_available",
            "final_user_content_available",
            "terminal_user_present",
            "agent_after_terminal_user_v2",
            "terminal_with_missing_reference_writes_candidate",
        }
        enum_fields = {
            "final_user_terminal_marker": {None, "NONE", "STOP", "TRANSFER"},
            "reference_write_completion": {"unknown", "no_reference_writes", "none", "partial", "all"},
            "reference_write_completion_at_terminal": {"unknown", "no_reference_writes", "none", "partial", "all"},
        }
        for key, value in metrics.items():
            if key == "measurement_version":
                continue
            if key in boolean_fields:
                if value is not None and type(value) is not bool:
                    raise ValueError("invalid boolean metric")
            elif key in enum_fields:
                if not isinstance(value, (str, type(None))) or value not in enum_fields[key]:
                    raise ValueError("invalid metric category")
            elif value is not None and (type(value) is not int or value < 0):
                raise ValueError("invalid metric count")
        if (
            type(metrics["message_trace_available"]) is not bool
            or type(metrics["reference_write_actions_available"]) is not bool
        ):
            raise ValueError("missing availability flag")
        expected = metrics["reference_write_actions_expected"]
        if (expected is not None) != metrics["reference_write_actions_available"]:
            raise ValueError("reference availability/count disagreement")
        for matched_key, missing_key, unknown_key, completion_key, available in [
            (
                "reference_write_actions_matched",
                "reference_write_actions_missing",
                "reference_write_unknown_result_candidates",
                "reference_write_completion",
                metrics["reference_write_actions_available"] and metrics["message_trace_available"],
            ),
            (
                "reference_write_actions_matched_before_terminal",
                "reference_write_actions_missing_at_terminal",
                "reference_write_unknown_result_candidates_at_terminal",
                "reference_write_completion_at_terminal",
                metrics["reference_write_actions_available"]
                and metrics["message_trace_available"]
                and metrics["terminal_user_present"] is True,
            ),
        ]:
            matched, missing, unknown = (metrics[key] for key in (matched_key, missing_key, unknown_key))
            if not available:
                if (
                    any(value is not None for value in (matched, missing, unknown))
                    or metrics[completion_key] != "unknown"
                ):
                    raise ValueError("unavailable diagnostic contains counts")
                continue
            if (
                any(value is None for value in (matched, missing, unknown))
                or matched + missing != expected
                or unknown > missing
            ):
                raise ValueError("inconsistent reference occurrence counts")
            completion = (
                "no_reference_writes" if expected == 0 else "all" if not missing else "partial" if matched else "none"
            )
            if metrics[completion_key] != completion:
                raise ValueError("reference completion disagrees with counts")
        terminal = metrics["terminal_user_present"]
        marker = metrics["final_user_terminal_marker"]
        if (
            (terminal is True and marker not in {"STOP", "TRANSFER"})
            or (terminal is False and marker != "NONE")
            or (terminal is None and marker is not None)
        ):
            raise ValueError("terminal marker disagrees with availability")
        after = metrics["agent_after_terminal_user_v2"]
        if (terminal is True and type(after) is not bool) or (terminal is not True and after is not None):
            raise ValueError("agent-after-terminal requires a terminal User")
        missing = metrics["reference_write_actions_missing_at_terminal"]
        candidate = missing > 0 if terminal is True and missing is not None else False if terminal is False else None
        if metrics["terminal_with_missing_reference_writes_candidate"] is not candidate:
            raise ValueError("terminal candidate disagrees with counts")

    def recompute(self) -> dict:
        from study_evidence import audit

        audit(self.evidence)
        original = read_json(self.evidence)
        report = read_json(self.path)
        fields = {
            "schema_version",
            "measurement_version",
            "boundary",
            "source_manifest_file_sha256",
            "source_manifest_sha256",
            "source_attempts_file_sha256",
            "measurement_source_sha256",
            "frozen_source_sha256",
            "source_case_index_sha256",
            "source_public_evidence_sha256",
            "first_attempts",
            "first_attempt_status_counts",
            "summary_all_first_attempts",
            "summary_valid_first_attempts",
            "rows",
            "selected_cases",
            "payload_sha256",
        }
        if not isinstance(report, dict) or set(report) != fields or report["schema_version"] != 1:
            raise ValueError("unexpected measurement bundle schema")
        if report["measurement_version"] != MEASUREMENT_VERSION or report["boundary"] != BOUNDARY:
            raise ValueError("measurement version or interpretation boundary mismatch")
        if (
            digest({key: value for key, value in report.items() if key != "payload_sha256"})
            != report["payload_sha256"]
        ):
            raise ValueError("measurement payload hash mismatch")
        for key in [key for key in fields if key.endswith("sha256")]:
            value = report[key]
            if key == "source_case_index_sha256" and value is None:
                continue
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("invalid source digest")
        if report["source_public_evidence_sha256"] != file_sha(self.evidence):
            raise ValueError("public source evidence hash mismatch")
        if report["source_manifest_sha256"] != digest(original["manifest"]):
            raise ValueError("source manifest hash mismatch")
        if report["measurement_source_sha256"] != file_sha(Path(__file__)) or report[
            "frozen_source_sha256"
        ] != file_sha(Path(__file__).with_name("frozen_study.py")):
            raise ValueError("measurement source version mismatch")
        expected_rows = {
            self.identity(row): row for row in original["rows"] if row["phase"] == "formal" and row["attempt"] == 0
        }
        rows = report["rows"]
        if not isinstance(rows, list):
            raise ValueError("measurement rows must be a list")
        row_fields = {
            "study_id",
            "slot_id",
            "attempt",
            "status",
            "outcome_sha256",
            "simulation_sha256",
            "frozen_v1",
            "measurement_v2",
        }
        seen = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != row_fields:
                raise ValueError("unexpected measurement row fields")
            identity = self.identity(row)
            if identity in seen:
                raise ValueError("duplicate measurement row")
            seen[identity] = row
            source = expected_rows.get(identity)
            if source is None:
                raise ValueError("measurement identity missing from source")
            if (
                row["status"] != source["status"]
                or row["outcome_sha256"] != source["outcome_sha256"]
                or row["simulation_sha256"] != source["artifact_sha256"].get("simulation.json")
            ):
                raise ValueError("measurement source identity/hash mismatch")
            if row["frozen_v1"] != {key: source["metrics"][key] for key in V1_COMPARISON_FIELDS}:
                raise ValueError("frozen comparison metrics mismatch")
            self.check_metrics(row["measurement_v2"])
        if set(seen) != set(expected_rows):
            raise ValueError("measurement rows missing from source population")
        if report["first_attempts"] != len(rows) or report["first_attempt_status_counts"] != dict(
            Counter(row["status"] for row in rows)
        ):
            raise ValueError("measurement population counts mismatch")
        if report["summary_all_first_attempts"] != MeasurementAudit.summarize(rows) or report[
            "summary_valid_first_attempts"
        ] != MeasurementAudit.summarize([row for row in rows if row["status"] == "valid"]):
            raise ValueError("measurement summary disagrees with rows")
        if self.case_index is None:
            if report["source_case_index_sha256"] is not None or report["selected_cases"] != []:
                raise ValueError("case index required for selected cases")
        else:
            if report["source_case_index_sha256"] != file_sha(self.case_index):
                raise ValueError("case source index hash mismatch")
            cases = read_json(self.case_index)["cases"]
            expected_cases = []
            for case in cases:
                source = seen.get(self.identity(case))
                if source is None or any(case[key] != source[key] for key in ("outcome_sha256", "simulation_sha256")):
                    raise ValueError("case source identity/hash mismatch")
                expected_cases.append({"case_id": case["case_id"], **source})
            if report["selected_cases"] != expected_cases:
                raise ValueError("selected case metadata mismatch")
        return {
            "first_attempts": len(rows),
            "summary_valid_first_attempts": report["summary_valid_first_attempts"],
            "case_count": len(report["selected_cases"]),
            "payload_sha256": report["payload_sha256"],
            "boundary": "Public counts, identities and hashes verified. Raw semantic measurements are not independently recomputed.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export", help="audit retained sources and export scalar measurements")
    exporter.add_argument("--input", type=Path, required=True)
    exporter.add_argument("--cases", type=Path)
    exporter.add_argument("--evidence", type=Path, required=True, help="Frozen public compact evidence")
    exporter.add_argument("--output", type=Path, required=True, help="New metadata JSON path; refuses overwrite")
    checker = commands.add_parser("audit", help="recompute compact summaries and join frozen public evidence")
    checker.add_argument("--input", type=Path, required=True)
    checker.add_argument("--evidence", type=Path, required=True)
    checker.add_argument("--cases", type=Path)
    args = parser.parse_args()
    if args.command == "audit":
        print(CompactMeasurementAudit(args.input, args.evidence, args.cases).recompute())
    else:
        report = MeasurementAudit(args.input, args.cases, args.evidence).build()
        write_json(args.output, report, exclusive=True)
        print(CompactMeasurementAudit(args.output, args.evidence, args.cases).recompute())


if __name__ == "__main__":
    main()
