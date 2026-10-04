"""Four new development integration attempts, with a global historical cost cap.

This is deliberately not the frozen holdout runner. No reward-based selection,
attempt retries, or automatic expansion. Dry-run never loads credentials.
"""

from __future__ import annotations

import argparse
import os
import signal
from contextlib import ExitStack
from pathlib import Path

from frozen_study import digest, file_sha, read_json, read_jsonl, schedule, write_json
from run_budgeted_study import BudgetPolicy, lock_outputs, systemic_failures
from run_frozen_study import reconcile, run_child, verify_sources


def audit_retained(output: Path):
    """Read-only check: never adopt or rewrite an old study's orphan attempt."""
    rows = read_jsonl(output / "attempts.jsonl")
    recorded = {(row["slot_id"], row["attempt"]) for row in rows}
    if len(recorded) != len(rows):
        raise ValueError("duplicate retained attempt identity")
    for job_path in output.glob("attempts/*/job.json"):
        job = read_json(job_path)
        if (job["slot"]["slot_id"], job["attempt"]) not in recorded:
            raise ValueError("unreconciled historical attempt; no automatic adoption")
    for row in rows:
        outcome = output / row["outcome_path"]
        if not outcome.resolve().is_relative_to(output.resolve()):
            raise ValueError("retained outcome escapes output")
        if file_sha(outcome) != row["outcome_sha256"]:
            raise ValueError("retained outcome changed")
        for name, expected in row["artifact_sha256"].items():
            if Path(name).name != name or file_sha(outcome.parent / name) != expected:
                raise ValueError("retained artifact changed")


def validate_pilot(manifest):
    if (
        manifest.get("engineering_version") != "engineering-v2"
        or manifest["task_ids"] != ["0", "5"]
        or manifest["trials"] != 1
        or manifest["conditions"] != ["U0", "U2"]
        or manifest["deadline_seconds"] != 600
        or manifest["evaluator_parse_retries"] != 2
        or manifest.get("user_empty_retries") != 1
        or not manifest["study_id"].startswith("engineering-v2-")
    ):
        raise ValueError("expected four engineering integration slots with fixed adapters")
    if manifest["schedule_sha256"] != digest([s.as_dict() for s in schedule(manifest, "formal")]):
        raise ValueError("pilot schedule changed")


def execute(root: Path, output: Path, policy_path: Path, *, run=False):
    output = output.resolve()
    policy = BudgetPolicy.load(policy_path, output.parent)
    manifest = read_json(output / "manifest.json")
    validate_pilot(manifest)
    verify_sources(manifest, root)
    if digest(manifest) != policy.manifest_sha256 or output not in policy.inventory.outputs:
        raise ValueError("policy and engineering study disagree")
    policy_sha = file_sha(policy_path)
    with ExitStack() as stack:
        lock_outputs(stack, output.parent, output, policy.inventory)
        for directory in policy.inventory.outputs:
            if directory == output and run:
                reconcile(directory, manifest)
            else:
                audit_retained(directory)
        policy.verify_baseline()
        snapshot = policy.snapshot()
        ledger = read_jsonl(output / "attempts.jsonl")
        slots = schedule(manifest, "formal")
        planned = {s.key for s in slots}
        if any(r["slot_id"] not in planned or r["attempt"] != 0 for r in ledger):
            raise ValueError("pilot contains extra/retried attempts")
        if any(r["status"] == "budget_stop" for r in ledger) or systemic_failures(ledger, frozenset()):
            raise ValueError("prior pilot stop requires diagnosis, no automatic resume")
        remaining = [s for s in slots if s.key not in {r["slot_id"] for r in ledger}]
        state = {"study_id": manifest["study_id"], "state": "dry_run", "remaining_slots": len(remaining)}
        if not run:
            return {**state, "cost_snapshot": snapshot, "new_model_calls": 0}
        from dotenv import dotenv_values

        env = os.environ.copy()
        values = dotenv_values(root / ".env")
        for key in ("OPENAI_API_KEY", "OPENAI_API_BASE"):
            if values.get(key):
                env[key] = values[key]
        if not env.get("OPENAI_API_KEY") or not env.get("OPENAI_API_BASE", "").startswith(
            "https://dashscope.aliyuncs.com/"
        ):
            raise ValueError("missing credentials or unsupported provider")
        state["state"] = "running"
        write_json(output / "status.json", state)
        try:
            for slot in remaining:
                verify_sources(manifest, root)
                if file_sha(policy_path) != policy_sha:
                    raise ValueError("pilot policy changed")
                policy.verify_baseline()
                snapshot = policy.snapshot()
                allowance = min(
                    policy.allowance(snapshot),
                    manifest["budget_cap_rmb"] - sum(r["billing"]["budget_debit_rmb"] for r in ledger),
                )
                if allowance <= 0:
                    state["state"] = "budget_stop_before_attempt"
                    break
                directory = output / "attempts" / f"{slot.key}-a00"
                directory.mkdir(parents=True, exist_ok=False)
                write_json(
                    directory / "job.json",
                    {
                        "manifest": manifest,
                        "slot": slot.as_dict(),
                        "attempt": 0,
                        "remaining_budget_rmb": allowance,
                        "policy_sha256": policy_sha,
                        "prior_cost_snapshot": snapshot,
                    },
                    exclusive=True,
                )
                run_child(
                    [
                        str(root / "tau2-bench-baseline/.venv/bin/python"),
                        str(Path(__file__).with_name("engineering_worker.py")),
                        "--job",
                        str(directory / "job.json"),
                    ],
                    cwd=root / "tau2-bench-baseline",
                    env=env,
                    log=directory / "worker.log",
                    timeout=600,
                )
                ledger = reconcile(output, manifest)
                row = ledger[-1]
                state.update(finished=len(ledger), remaining_slots=4 - len(ledger), last_status=row["status"])
                write_json(output / "status.json", state)
                if row["status"] == "budget_stop" or systemic_failures(ledger, frozenset()):
                    state["state"] = "stopped_at_gate"
                    break
            else:
                state["state"] = "finished"
        except BaseException:
            reconcile(output, manifest)
            state["state"] = "stopped_after_exception"
            raise
        finally:
            state["cost_snapshot"] = policy.snapshot()
            write_json(output / "status.json", state)
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    def cancel(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, cancel)
    print(execute(Path(__file__).resolve().parents[3], args.input, args.policy, run=args.run))


if __name__ == "__main__":
    main()
