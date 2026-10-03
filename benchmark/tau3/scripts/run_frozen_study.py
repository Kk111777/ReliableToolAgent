"""Serial, resumable paid study runner. Dry-run never loads credentials or tau2."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

from frozen_study import (
    append_json,
    budget_totals,
    digest,
    file_sha,
    read_json,
    read_jsonl,
    schedule,
    validate_manifest,
    write_json,
)


def run_child(command: list[str], *, cwd: Path, env: dict, log: Path, timeout: float) -> int:
    """SIGTERM gives the worker time to save; SIGKILL stops a nonresponsive SDK."""
    with log.open("xb") as handle:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=handle, start_new_session=True)
        write_json(log.parent / "process.json", {"pid": child.pid}, exclusive=True)
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            import signal

            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            return 124
        except BaseException:
            import signal

            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
            raise


def verify_sources(manifest: dict, root: Path) -> None:
    for relative, expected in manifest["source_sha256"].items():
        if file_sha(root / relative) != expected:
            raise ValueError(f"frozen source changed: {relative}")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root / "tau2-bench-baseline", text=True).strip()
    if actual != manifest["benchmark_commit"]:
        raise ValueError("benchmark commit changed")


def reconcile(output: Path, manifest: dict) -> list[dict]:
    """Adopt finished orphan outcomes after a crash, never repeat a paid attempt."""
    ledger_path = output / "attempts.jsonl"
    ledger = read_jsonl(ledger_path)
    existing = {(r["slot_id"], r["attempt"]) for r in ledger}
    if len(existing) != len(ledger):
        raise ValueError("duplicate attempt ledger keys")
    for job_path in sorted(output.glob("attempts/*/job.json")):
        job = read_json(job_path)
        key = (job["slot"]["slot_id"], job["attempt"])
        if key in existing:
            continue
        outcome_path = job_path.parent / "outcome.json"
        if not outcome_path.exists():
            process_path = job_path.parent / "process.json"
            if process_path.exists():
                try:
                    os.kill(read_json(process_path)["pid"], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise ValueError("unfinished worker is still alive; refusing concurrent paid execution")
            # A crashed/killed worker is an attempt, including any unknown charged calls.
            row = {
                **job["slot"],
                "study_id": manifest["study_id"],
                "attempt": job["attempt"],
                "status": "interrupted",
                "error_class": "MissingWorkerOutcome",
                "metrics": {},
                "billing": budget_totals(
                    read_jsonl(job_path.parent / "requests.jsonl") or read_jsonl(job_path.parent / "calls.jsonl")
                ),
            }
            write_json(outcome_path, row, exclusive=True)
        row = read_json(outcome_path)
        row["outcome_path"] = str(outcome_path.relative_to(output))
        row["outcome_sha256"] = file_sha(outcome_path)
        row["artifact_sha256"] = {
            name: file_sha(job_path.parent / name)
            for name in ["job.json", "simulation.json", "calls.jsonl", "requests.jsonl", "evaluator.jsonl"]
            if (job_path.parent / name).exists()
        }
        append_json(ledger_path, row)
        ledger.append(row)
        existing.add(key)
    for row in ledger:
        if file_sha(output / row["outcome_path"]) != row["outcome_sha256"]:
            raise ValueError("saved outcome changed")
        for name, expected in row["artifact_sha256"].items():
            if file_sha((output / row["outcome_path"]).parent / name) != expected:
                raise ValueError("saved attempt artifact changed")
    return ledger


def smoke_ready(output: Path, ledger: list[dict], manifest: dict) -> bool:
    """Recovered request failures are allowed only when their reservation is retained.

    Successful HTTP responses must have usage. A ReadTimeout followed by a measured
    retry is different from a successful response with silently missing usage.
    """
    smoke = [r for r in ledger if r["phase"] == "smoke" and r["attempt"] == 0]
    if {r["slot_id"] for r in smoke} != {slot.key for slot in schedule(manifest, "smoke")}:
        return False
    for row in smoke:
        if row["status"] != "valid" or not row["billing"]["calls"]:
            return False
        directory = (output / row["outcome_path"]).parent
        events = read_jsonl(directory / "requests.jsonl")
        latest = {event["call_index"]: event for event in events}
        if not latest or budget_totals(events) != row["billing"]:
            return False
        for event in latest.values():
            if event["state"] == "http_started":
                return False
            if event["state"] == "http_returned" and 200 <= event["http_status"] < 300:
                if event["known_list_price_rmb"] is None:
                    return False
            elif event["budget_debit_rmb"] != event["precall_reservation_rmb"]:
                return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", choices=["smoke", "formal"], default="formal")
    parser.add_argument("--run", action="store_true", help="authorize model calls; default is dry-run")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-infrastructure", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive")
    root = Path(__file__).resolve().parents[3]
    manifest = read_json(args.manifest)
    validate_manifest(manifest)
    verify_sources(manifest, root)
    slots = schedule(manifest, args.phase)
    output = args.output.resolve()
    frozen_path = output / "manifest.json"
    if frozen_path.exists() and digest(read_json(frozen_path)) != digest(manifest):
        raise ValueError("refusing to reuse output with a different manifest")
    if not args.run:
        print(
            {
                "mode": "dry-run; no credentials or model calls",
                "phase": args.phase,
                "slots": len(slots),
                "manifest_sha256": digest(manifest),
                "first_slots": [slot.as_dict() for slot in slots[:6]],
            }
        )
        return
    output.mkdir(parents=True, exist_ok=True)
    # Exclude a second runner before reconciliation of possibly still-running children.
    lock_path = output / "runner.lock"
    lock = lock_path.open("a+")
    import fcntl

    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not frozen_path.exists():
        write_json(frozen_path, manifest, exclusive=True)
    ledger = reconcile(output, manifest)
    if args.phase == "formal":
        if not smoke_ready(output, ledger, manifest):
            raise ValueError(
                "formal execution requires four valid smoke attempts with successful-request usage and reserved failed requests"
            )
    # Credentials are read only after explicit --run and all offline checks.
    from dotenv import dotenv_values

    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "OPENAI_API_BASE"):
        value = dotenv_values(root / ".env").get(key)
        if value:
            env[key] = value
    if not env.get("OPENAI_API_KEY") or not env.get("OPENAI_API_BASE"):
        raise ValueError("missing provider credentials")
    performed = 0
    for slot in slots:
        rows = [r for r in ledger if r["slot_id"] == slot.key]
        if rows and not args.retry_infrastructure:
            continue
        if args.retry_infrastructure:
            if not rows or any(r["status"] == "valid" for r in rows):
                continue
            if rows[0]["status"] == "budget_stop":
                continue
        attempt = max((r["attempt"] for r in rows), default=-1) + 1
        additional = sum(r["attempt"] > 0 for r in ledger)
        if additional >= manifest["additional_attempt_limit"] and attempt > 0:
            break
        if len(ledger) >= manifest["total_attempt_limit"]:
            break
        used = sum(r["billing"]["budget_debit_rmb"] for r in ledger)
        remaining = manifest["budget_cap_rmb"] - used
        if remaining <= 0:
            break
        directory = output / "attempts" / f"{slot.key}-a{attempt:02d}"
        directory.mkdir(parents=True, exist_ok=False)
        job = {"manifest": manifest, "slot": slot.as_dict(), "attempt": attempt, "remaining_budget_rmb": remaining}
        job_path = directory / "job.json"
        write_json(job_path, job, exclusive=True)
        started = time.monotonic()
        exit_code = run_child(
            [
                str(root / "tau2-bench-baseline/.venv/bin/python"),
                str(Path(__file__).with_name("study_worker.py")),
                "--job",
                str(job_path),
            ],
            cwd=root / "tau2-bench-baseline",
            env=env,
            log=directory / "worker.log",
            timeout=manifest["deadline_seconds"],
        )
        ledger = reconcile(output, manifest)
        row = next(r for r in ledger if r["slot_id"] == slot.key and r["attempt"] == attempt)
        used = sum(r["billing"]["budget_debit_rmb"] for r in ledger)
        summary = {
            "study_id": manifest["study_id"],
            "attempts_finished": len(ledger),
            "formal_first_attempts_finished": sum(r["phase"] == "formal" and r["attempt"] == 0 for r in ledger),
            "budget_debit_rmb": used,
            "known_list_price_rmb": sum(r["billing"]["known_list_price_rmb"] for r in ledger),
            "last_slot": slot.key,
            "last_status": row["status"],
            "exit_code": exit_code,
            "last_wall_seconds": time.monotonic() - started,
        }
        write_json(output / "status.json", summary)
        print(summary, flush=True)
        performed += 1
        if row["status"] == "budget_stop" or (args.limit is not None and performed >= args.limit):
            break
        # Stop systemic infrastructure failure early instead of spending through the schedule.
        if len(ledger) >= 3 and all(r["status"] != "valid" for r in ledger[-3:]):
            print("stopped: three consecutive infrastructure/deadline failures", flush=True)
            break


if __name__ == "__main__":
    main()
