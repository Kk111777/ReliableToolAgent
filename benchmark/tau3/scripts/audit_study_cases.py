"""Check sanitized case metadata against one audited compact study bundle."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from frozen_study import WRITE_TOOLS, digest, file_sha, read_json
from study_evidence import audit


BOUNDARY = (
    "Case identities, source hashes and tool counters match the compact evidence. "
    "Message text and tool arguments are omitted; this does not authenticate raw trajectories, "
    "semantic judgments or official rewards. Case selection is not independent annotation."
)
INDEX_FIELDS = {
    "schema_version",
    "study_id",
    "manifest_sha256",
    "source_review_sha256",
    "selection",
    "boundary",
    "cases",
    "payload_sha256",
}
CASE_FIELDS = {
    "case_id",
    "study_id",
    "slot_id",
    "attempt",
    "status",
    "outcome_sha256",
    "simulation_sha256",
    "message_indices",
    "selected_message_roles",
    "tool_events",
    "metrics",
}
EVENT_FIELDS = {"message_index", "tool_name", "tool_type", "status", "arguments_sha256"}


def is_hash(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def is_index(value) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class CaseAudit:
    evidence: dict
    index: dict
    evidence_file_sha256: str

    @classmethod
    def load(cls, evidence: Path, cases: Path) -> CaseAudit:
        audit(evidence)
        return cls(read_json(evidence), read_json(cases), file_sha(evidence))

    @staticmethod
    def tool_counts(events: list[dict]) -> dict:
        previous = {}
        cross = 0
        for event in events:
            key = (event["tool_name"], event["arguments_sha256"])
            if key in previous and previous[key] != event["message_index"]:
                cross += 1
            previous[key] = event["message_index"]
        groups = Counter((e["message_index"], e["tool_name"], e["arguments_sha256"]) for e in events)
        return {
            "tool_calls": len(events),
            "explicit_tool_errors": sum(e["status"] == "error" for e in events),
            "unknown_tool_results": sum(e["status"] == "unknown" for e in events),
            "same_message_duplicate_calls": sum(n for n in groups.values() if n >= 2),
            "same_message_excess_calls": sum(n - 1 for n in groups.values() if n >= 2),
            "cross_turn_exact_repeats": cross,
        }

    def check_case(self, case: dict, rows: dict) -> dict:
        if not isinstance(case, dict) or set(case) != CASE_FIELDS:
            raise ValueError("unexpected case fields")
        if not isinstance(case["case_id"], str) or not re.fullmatch(r"C[0-9]+", case["case_id"]):
            raise ValueError("invalid case ID")
        if not is_index(case["attempt"]):
            raise ValueError("invalid attempt index")
        key = (case["study_id"], case["slot_id"], case["attempt"])
        if key not in rows:
            raise ValueError("case attempt is absent from compact evidence")
        row = rows[key]
        for field in ("status", "outcome_sha256", "metrics"):
            if case[field] != row[field]:
                raise ValueError(f"case {field} disagrees with compact evidence")
        simulation_hash = row["artifact_sha256"].get("simulation.json")
        if not is_hash(case["simulation_sha256"]) or case["simulation_sha256"] != simulation_hash:
            raise ValueError("case simulation hash disagrees with compact evidence")
        indices = case["message_indices"]
        roles = case["selected_message_roles"]
        if not isinstance(indices, list) or not all(is_index(i) for i in indices) or indices != sorted(set(indices)):
            raise ValueError("selected message indices must be unique and ordered")
        if (
            not isinstance(roles, list)
            or any(
                not isinstance(role, dict)
                or set(role) != {"message_index", "role"}
                or not is_index(role["message_index"])
                or role["role"] not in {"system", "user", "assistant", "tool"}
                for role in roles
            )
            or [role["message_index"] for role in roles] != indices
        ):
            raise ValueError("selected message roles disagree with indices")
        events = case["tool_events"]
        if not isinstance(events, list):
            raise ValueError("tool events must be a list")
        for event in events:
            if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
                raise ValueError("unexpected tool event fields; arguments and message text must be omitted")
            name = event["tool_name"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
                raise ValueError("invalid tool name")
            if not is_index(event["message_index"]) or not is_hash(event["arguments_sha256"]):
                raise ValueError("invalid tool position or arguments hash")
            if event["status"] not in {"success", "error", "unknown"}:
                raise ValueError("unknown tool status")
            if event["tool_type"] != ("write" if name in WRITE_TOOLS else "other"):
                raise ValueError("tool type disagrees with frozen WRITE names")
        positions = [e["message_index"] for e in events]
        if positions != sorted(positions):
            raise ValueError("tool events must be in message order")
        counters = self.tool_counts(events)
        if any(case["metrics"][name] != value for name, value in counters.items()):
            raise ValueError("sanitized tool counters disagree with frozen metrics")
        return {"case_id": case["case_id"], "slot_id": case["slot_id"], "attempt": case["attempt"], **counters}

    def recompute(self) -> dict:
        index = self.index
        if set(index) != INDEX_FIELDS or type(index["schema_version"]) is not int or index["schema_version"] != 1:
            raise ValueError("unexpected case index schema")
        if digest({k: v for k, v in index.items() if k != "payload_sha256"}) != index["payload_sha256"]:
            raise ValueError("case payload hash mismatch")
        manifest = self.evidence["manifest"]
        if index["study_id"] != manifest["study_id"] or index["manifest_sha256"] != digest(manifest):
            raise ValueError("case cohort or manifest mismatch")
        if not is_hash(index["source_review_sha256"]):
            raise ValueError("invalid source review hash")
        if not all(isinstance(index[f], str) and index[f].strip() for f in ("selection", "boundary")):
            raise ValueError("case selection and evidence boundary required")
        if not isinstance(index["cases"], list) or not index["cases"]:
            raise ValueError("at least one case required")
        rows = {(r["study_id"], r["slot_id"], r["attempt"]): r for r in self.evidence["rows"]}
        checked = [self.check_case(case, rows) for case in index["cases"]]
        ids = [case["case_id"] for case in checked]
        identities = [(case["slot_id"], case["attempt"]) for case in checked]
        if len(set(ids)) != len(ids) or len(set(identities)) != len(identities):
            raise ValueError("duplicate case ID or attempt")
        return {
            "study_id": index["study_id"],
            "case_count": len(checked),
            "evidence_file_sha256": self.evidence_file_sha256,
            "case_payload_sha256": index["payload_sha256"],
            "cases": checked,
            "boundary": BOUNDARY,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    result = CaseAudit.load(args.evidence, args.cases).recompute()
    print({key: result[key] for key in ("study_id", "case_count", "case_payload_sha256", "boundary")})


if __name__ == "__main__":
    main()
