"""Finish the primary run, then execute the separately frozen replication.

One-shot execution supervisor, not a scheduler. It never edits model settings,
event rules, original attempts, or the primary manifest. Derived reports stay local.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import os
import shutil
import subprocess
import time
from pathlib import Path

from analyze_frozen_study import analyze as analyze_primary
from analyze_replication import analyze as analyze_replication
from frozen_study import digest, read_json, schedule, write_json
from run_frozen_study import reconcile, smoke_ready, verify_sources


def unique_paid_rows(*ledgers: list[dict]) -> list[dict]:
    unique = {}
    for ledger in ledgers:
        for row in ledger:
            key = (row["study_id"], row["slot_id"], row["attempt"])
            if key in unique and unique[key]["outcome_sha256"] != row["outcome_sha256"]:
                raise ValueError("same paid identity has conflicting evidence")
            unique[key] = row
    return list(unique.values())


def effective_replication(plan: dict, primary_rows: list[dict]) -> dict:
    result = copy.deepcopy(plan)
    primary_debit = sum(row["billing"]["budget_debit_rmb"] for row in unique_paid_rows(primary_rows))
    reused_smoke_debit = sum(row["billing"]["budget_debit_rmb"] for row in primary_rows if row["phase"] == "smoke")
    preflight = plan["prior_preflight"]["budget_debit_rmb"]
    result["budget_cap_rmb"] = plan["combined_budget_cap_rmb"] - primary_debit - preflight + reused_smoke_debit
    if result["budget_cap_rmb"] <= reused_smoke_debit:
        raise ValueError("combined budget exhausted before replication")
    result["plan_manifest_sha256"] = digest(plan)
    result["status"] = "execution_frozen_before_replication_calls"
    result["operational_budget_materialization"] = {
        "combined_cap_rmb": plan["combined_budget_cap_rmb"],
        "primary_debit_rmb": primary_debit,
        "initial_preflight_debit_rmb": preflight,
        "reused_smoke_debit_rmb": reused_smoke_debit,
        "accounting": "Smoke attempts retain their original cost; reused identities count once in combined billing.",
    }
    return result


def systemic_failure(rows: list[dict]) -> bool:
    return len(rows) >= 3 and all(row["status"] != "valid" for row in rows[-3:])


def runner(root: Path, output: Path, manifest_path: Path, *, retries: bool = False) -> None:
    command = [
        str(root / ".venv/bin/python"),
        str(Path(__file__).with_name("run_frozen_study.py")),
        "--manifest",
        str(manifest_path),
        "--output",
        str(output),
        "--phase",
        "formal",
        "--run",
    ]
    if retries:
        command.append("--retry-infrastructure")
    subprocess.run(command, cwd=root, check=True)


def wait_for_current_runner(output: Path) -> None:
    with (output / "runner.lock").open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(5)
        fcntl.flock(handle, fcntl.LOCK_UN)


def complete_study(root: Path, output: Path, *, wait: bool = False) -> list[dict]:
    if wait:
        wait_for_current_runner(output)
    manifest_path = output / "manifest.json"
    manifest = read_json(manifest_path)
    verify_sources(manifest, root)
    # If the parent died while a child was finishing, wait for that existing attempt.
    while True:
        try:
            rows = reconcile(output, manifest)
            break
        except ValueError as exc:
            if "unfinished worker is still alive" not in str(exc):
                raise
            time.sleep(5)
    if systemic_failure(rows):
        raise RuntimeError("three consecutive infrastructure/deadline failures require diagnosis")
    if any(row["status"] == "budget_stop" for row in rows):
        raise RuntimeError("study budget guard stopped; do not silently change its frozen budget")
    planned = len(schedule(manifest, "formal"))
    primary = [row for row in rows if row["phase"] == "formal" and row["attempt"] == 0]
    if len(primary) < planned:
        runner(root, output, manifest_path)
        rows = reconcile(output, manifest)
        primary = [row for row in rows if row["phase"] == "formal" and row["attempt"] == 0]
    if systemic_failure(rows) or len(primary) != planned:
        raise RuntimeError("primary schedule stopped before completion")
    invalid = sum(row["status"] != "valid" for row in primary)
    if invalid / planned > 0.1:
        raise RuntimeError("infrastructure fraction exceeds engineering gate; diagnose before expansion")
    if invalid:
        runner(root, output, manifest_path, retries=True)
        rows = reconcile(output, manifest)
    return rows


def execute(primary_output: Path, replication_plan: Path, replication_output: Path) -> dict:
    root = Path(__file__).resolve().parents[3]
    status_path = primary_output.parent / "combined_execution_status.json"
    write_json(status_path, {"state": "waiting_for_primary", "supervisor_pid": os.getpid()})
    primary_rows = complete_study(root, primary_output, wait=True)
    primary_summary = analyze_primary(primary_output, primary_output / "analysis")
    if not primary_summary["engineering_gate_pass"]:
        raise RuntimeError("primary pair-completeness gate failed; diagnose before expansion")
    plan = read_json(replication_plan)
    verify_sources(plan, root)
    effective = effective_replication(plan, primary_rows)
    if not replication_output.exists():
        replication_output.mkdir(parents=True)
        write_json(replication_output / "manifest.json", effective, exclusive=True)
        for row in primary_rows:
            if row["phase"] != "smoke":
                continue
            directory = (primary_output / row["outcome_path"]).parent
            shutil.copytree(directory, replication_output / "attempts" / directory.name)
    elif digest(read_json(replication_output / "manifest.json")) != digest(effective):
        raise ValueError("replication output uses a different effective budget/manifest")
    replication_rows = reconcile(replication_output, effective)
    if not smoke_ready(replication_output, replication_rows, effective):
        raise ValueError("reused smoke evidence failed validation")
    write_json(
        status_path,
        {
            "state": "running_replication",
            "supervisor_pid": os.getpid(),
            "primary_finished_slots": primary_summary["finished_primary_slots"],
            "replication_planned_slots": len(schedule(effective, "formal")),
        },
    )
    replication_rows = complete_study(root, replication_output)
    replication_summary = analyze_replication(replication_output, replication_output / "analysis")
    paid = unique_paid_rows(primary_rows, replication_rows)
    result = {
        "state": "completed" if replication_summary["engineering_gate_pass"] else "completed_below_engineering_gate",
        "primary_study": primary_summary["study_id"],
        "replication_study": replication_summary["study_id"],
        "formal_primary_slots_finished": primary_summary["finished_primary_slots"]
        + replication_summary["finished_primary_slots"],
        "distinct_tasks": len(read_json(primary_output / "manifest.json")["task_ids"]) + len(effective["task_ids"]),
        "unique_paid_attempts_including_preflight": len(paid) + plan["prior_preflight"]["attempts"],
        "known_list_price_rmb": sum(row["billing"]["known_list_price_rmb"] for row in paid)
        + plan["prior_preflight"]["known_list_price_rmb"],
        "conservative_budget_debit_rmb": sum(row["billing"]["budget_debit_rmb"] for row in paid)
        + plan["prior_preflight"]["budget_debit_rmb"],
        "combined_cap_rmb": plan["combined_budget_cap_rmb"],
        "provider_invoice_verified": False,
        "interpretation": "Two separate cohorts; no pooled official benchmark score.",
    }
    if result["conservative_budget_debit_rmb"] > result["combined_cap_rmb"]:
        raise ValueError("combined accounting exceeds cap")
    write_json(status_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-output", required=True, type=Path)
    parser.add_argument("--replication-plan", required=True, type=Path)
    parser.add_argument("--replication-output", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        print(
            {
                "mode": "dry-run",
                "model_calls": 0,
                "primary_slots": 210,
                "replication_slots": 120,
                "combined_cap_rmb": 500,
            }
        )
        return
    primary_output = args.primary_output.resolve()
    try:
        with (primary_output.parent / "supervisor.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = execute(primary_output, args.replication_plan.resolve(), args.replication_output.resolve())
        print(result, flush=True)
    except Exception as exc:
        write_json(
            primary_output.parent / "combined_execution_status.json",
            {
                "state": "stopped_for_diagnosis",
                "error_class": type(exc).__name__,
                "reason": str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "supervisor execution failed",
            },
        )
        raise


if __name__ == "__main__":
    main()
