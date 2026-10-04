"""Export a small engineering integration report; check it without credentials.

Public auditing verifies recorded counters and hashes, not private trajectory
semantics. All four first attempts remain in the report, including failures.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from frozen_study import budget_totals, digest, file_sha, read_json, read_jsonl, schedule, write_json
from run_engineering_pilot import audit_retained, validate_pilot


def summary(rows):
    return {
        "attempts": len(rows),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "known_list_price_rmb": sum(r["billing"]["known_list_price_rmb"] for r in rows),
        "conservative_list_debit_rmb": sum(r["billing"]["budget_debit_rmb"] for r in rows),
        "http_requests": sum(r["billing"]["calls"] for r in rows),
        "unknown_usage_requests": sum(r["billing"]["usage_unknown_calls"] for r in rows),
        "empty_user_responses": sum(r["empty_user_responses"] for r in rows),
        "user_response_retries": sum(r["user_response_retries"] for r in rows),
        "evaluator_format_retries": sum(r["evaluator_format_retries"] for r in rows),
        "accepted_normalized_evaluator_responses": sum(r["normalized_evaluator_responses"] for r in rows),
    }


def export(source):
    manifest = read_json(source / "manifest.json")
    validate_pilot(manifest)
    audit_retained(source)
    rows = []
    for row in read_jsonl(source / "attempts.jsonl"):
        directory = (source / row["outcome_path"]).parent
        billing = budget_totals(read_jsonl(directory / "requests.jsonl") or read_jsonl(directory / "calls.jsonl"))
        if billing != row["billing"]:
            raise ValueError("billing differs from request evidence")
        events = read_jsonl(directory / "response_adapters.jsonl")
        rows.append(
            {
                **{k: row[k] for k in ("study_id", "slot_id", "task_id", "condition", "trial", "attempt", "status")},
                "billing": billing,
                "empty_user_responses": sum(e["role"] == "user" and e["empty"] for e in events),
                "user_response_retries": sum(e["role"] == "user" and e["response_attempt"] > 0 for e in events),
                "evaluator_format_retries": sum(
                    e["role"] == "evaluator" and e["response_attempt"] > 0 for e in events
                ),
                "normalized_evaluator_responses": sum(
                    e["role"] == "evaluator" and e["accepted"] and e["normalized"] for e in events
                ),
                "source_sha256": {p.name: file_sha(p) for p in sorted(directory.iterdir()) if p.is_file()},
            }
        )
    payload = {
        "schema_version": 1,
        "boundary": "Four exposed-development integration attempts; no error-rate estimate or algorithm gain.",
        "execution_state": read_json(source / "status.json")["state"],
        "manifest_file_sha256": file_sha(source / "manifest.json"),
        "protocol": {
            k: manifest[k]
            for k in (
                "engineering_version",
                "study_id",
                "task_ids",
                "trials",
                "conditions",
                "schedule_sha256",
                "base_seed",
                "agent_model",
                "user_models",
                "evaluator_model",
                "model_args",
                "deadline_seconds",
                "user_empty_retries",
                "evaluator_parse_retries",
                "benchmark_commit",
                "source_sha256",
            )
        },
        "rows": rows,
        "summary": summary(rows),
    }
    payload["payload_sha256"] = digest(payload)
    audit(payload)
    return payload


def audit(payload):
    plain = {k: v for k, v in payload.items() if k != "payload_sha256"}
    if digest(plain) != payload["payload_sha256"]:
        raise ValueError("engineering report digest mismatch")
    protocol, rows = payload["protocol"], payload["rows"]
    validate_pilot(protocol)
    planned = {s.key: s for s in schedule(protocol, "formal")}
    identities = {r["slot_id"] for r in rows}
    if len(rows) != len(identities) or not identities <= set(planned):
        raise ValueError("duplicate or unplanned first attempt")
    if payload["execution_state"] not in {"finished", "stopped_at_gate", "budget_stop_before_attempt"}:
        raise ValueError("integration execution has not reached a stable boundary")
    if payload["execution_state"] == "finished" and identities != set(planned):
        raise ValueError("finished execution is missing planned attempts")
    for row in rows:
        slot = planned[row["slot_id"]]
        if any(row.get(k) != v for k, v in slot.as_dict().items() if k not in {"phase", "seed"}):
            raise ValueError("attempt identity differs from schedule")
        if row["attempt"] != 0 or row["study_id"] != protocol["study_id"]:
            raise ValueError("additional or foreign attempt")
    if payload["summary"] != summary(rows):
        raise ValueError("engineering aggregate mismatch")
    return {
        "attempts": len(rows),
        "missing_slots": sorted(set(planned) - identities),
        "summary": payload["summary"],
        "scope": "public counters and provenance only",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.audit:
        print(audit(read_json(args.audit)))
    elif args.source and args.output:
        write_json(args.output, export(args.source), exclusive=True)
    else:
        parser.error("use --audit or --source with --output")


if __name__ == "__main__":
    main()
