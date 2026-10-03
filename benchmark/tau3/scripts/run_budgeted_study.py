"""Resume a frozen study under a stricter total budget, including earlier runs.

The frozen worker checks every HTTP request against the remaining allowance.
Holding all runner locks makes cap - historical debit a global request cap.
No discounts are inferred from approximate account balances.
"""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import signal
import time
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from frozen_study import (
    budget_totals,
    digest,
    file_sha,
    read_json,
    read_jsonl,
    schedule,
    validate_manifest,
    write_json,
)
from run_frozen_study import reconcile, run_child, smoke_ready, verify_sources


@dataclass(frozen=True)
class CostInventory:
    outputs: tuple[Path, ...]

    def snapshot(self) -> dict:
        """Deduplicate identical reused attempts; reject changed evidence or torn JSON."""
        records = self.records()
        return {
            "unique_paid_attempts": len(records),
            "known_list_price_rmb": sum(r["billing"]["known_list_price_rmb"] for r in records),
            "conservative_budget_debit_rmb": sum(r["billing"]["budget_debit_rmb"] for r in records),
            "usage_unknown_calls": sum(r["billing"]["usage_unknown_calls"] for r in records),
            "observed_requests": sum(r["billing"]["calls"] for r in records),
            "inventory_sha256": digest(records),
            "provider_invoice_verified": False,
        }

    def records(self) -> list[dict]:
        attempts = {}
        for output in self.outputs:
            for job_path in sorted(output.glob("attempts/*/job.json")):
                directory = job_path.parent
                job = read_json(job_path)
                identity = (job["manifest"]["study_id"], job["slot"]["slot_id"], job["attempt"])
                files = {
                    name: file_sha(directory / name)
                    for name in ("job.json", "requests.jsonl", "calls.jsonl", "outcome.json")
                    if (directory / name).exists()
                }
                events = read_jsonl(directory / "requests.jsonl") or read_jsonl(directory / "calls.jsonl")
                billing = budget_totals(events)
                if any(not math.isfinite(v) or v < 0 for v in billing.values()):
                    raise ValueError("negative or nonfinite cost")
                if (directory / "outcome.json").exists():
                    if read_json(directory / "outcome.json")["billing"] != billing:
                        raise ValueError("outcome billing disagrees with request evidence")
                else:
                    raise ValueError("unfinished attempt; reconcile before resuming")
                record = {"identity": list(identity), "billing": billing, "files_sha256": files}
                if identity in attempts and attempts[identity] != record:
                    raise ValueError("reused paid identity has conflicting evidence")
                attempts[identity] = record
        return [attempts[key] for key in sorted(attempts)]


@dataclass(frozen=True)
class BudgetPolicy:
    cap_rmb: float
    manifest_sha256: str
    inventory: CostInventory
    discount_factor: float = 1.0
    baseline_records: tuple[dict, ...] = ()

    @classmethod
    def load(cls, path: Path, base: Path) -> BudgetPolicy:
        data = read_json(path)
        cap = data["combined_cap_rmb"]
        if type(cap) not in {int, float} or not math.isfinite(cap) or cap <= 0:
            raise ValueError("explicit positive total budget required")
        factor = data.get("discount_factor", 1)
        if type(factor) not in {int, float} or not math.isfinite(factor) or not 0 < factor <= 1:
            raise ValueError("discount must be a positive multiplier no greater than one")
        if data.get("cost_basis") != "list_price_with_unknown_usage_reserve":
            raise ValueError("unsupported cost basis")
        if factor < 1 and data.get("discount_source") != "explicit_user_confirmation":
            raise ValueError("approximate balances cannot authorize a discount")
        names = data["accounting_outputs"]
        if not names or len(set(names)) != len(names):
            raise ValueError("distinct historical output directories required")
        outputs = tuple((base / name).resolve() for name in names)
        if any(not p.is_relative_to(base.resolve()) for p in outputs):
            raise ValueError("accounting path escapes study root")
        for name in data["required_existing_outputs"]:
            if name not in names or not (base / name / "manifest.json").is_file():
                raise ValueError("required historical study is absent")
        if data.get("paid_execution_state") != "approved_with_verified_global_guard":
            raise ValueError("paid resume gate has not been approved")
        baseline_records = ()
        if data.get("balance_baseline"):
            baseline = data["balance_baseline"]
            amount = baseline["available_rmb"]
            if type(amount) not in {int, float} or not math.isfinite(amount) or amount <= 0:
                raise ValueError("balance baseline must be positive")
            baseline_path = (base / baseline["evidence_path"]).resolve()
            if (
                not baseline_path.is_relative_to(base.resolve())
                or file_sha(baseline_path) != baseline["evidence_sha256"]
            ):
                raise ValueError("balance baseline evidence changed")
            evidence = read_json(baseline_path)
            baseline_records = tuple(evidence["records"])
            if digest(list(baseline_records)) != evidence["snapshot"]["inventory_sha256"]:
                raise ValueError("baseline record digest mismatch")
            known = sum(r["billing"]["known_list_price_rmb"] for r in baseline_records)
            maximum = Decimal(str(known)) * Decimal(str(factor)) + Decimal(str(amount))
            if Decimal(str(cap)) > maximum:
                raise ValueError("total cap exceeds the reported balance plus already measured cost")
        return cls(float(cap), data["frozen_manifest_sha256"], CostInventory(outputs), float(factor), baseline_records)

    def verify_baseline(self) -> None:
        """The balance anchor remains valid only while all earlier records are retained."""
        current = {tuple(r["identity"]): r for r in self.inventory.records()}
        if any(current.get(tuple(row["identity"])) != row for row in self.baseline_records):
            raise ValueError("balance baseline historical evidence changed or disappeared")

    def snapshot(self) -> dict:
        result = self.inventory.snapshot()
        result.update(
            discount_factor=self.discount_factor,
            estimated_discounted_cost_rmb=result["known_list_price_rmb"] * self.discount_factor,
            conservative_discounted_debit_rmb=result["conservative_budget_debit_rmb"] * self.discount_factor,
        )
        return result

    def remaining_rmb(self, snapshot: dict) -> float:
        remaining = Decimal(str(self.cap_rmb)) - Decimal(str(snapshot["conservative_budget_debit_rmb"])) * Decimal(
            str(self.discount_factor)
        )
        return float(max(Decimal(0), remaining.quantize(Decimal("0.0000001"), rounding=ROUND_DOWN)))

    def allowance(self, snapshot: dict) -> float:
        # Round down to avoid allocating a float-rounding excess to the worker.
        remaining = Decimal(str(self.cap_rmb)) / Decimal(str(self.discount_factor)) - Decimal(
            str(snapshot["conservative_budget_debit_rmb"])
        )
        return float(max(Decimal(0), remaining.quantize(Decimal("0.0000001"), rounding=ROUND_DOWN)))


def remaining_slots(manifest: dict, ledger: list[dict], *, retries: bool = False) -> list:
    """Keep frozen order; optionally select one secondary attempt per invalid slot."""
    present = {row["slot_id"] for row in ledger}
    if retries:
        return [
            slot
            for slot in schedule(manifest, "formal")
            if any(
                r["slot_id"] == slot.key and r["status"] in {"infrastructure_error", "timeout", "interrupted"}
                for r in ledger
            )
            and not any(
                r["slot_id"] == slot.key and (r["status"] in {"valid", "budget_stop"} or r["attempt"] > 0)
                for r in ledger
            )
        ]
    return [slot for slot in schedule(manifest, "formal") if slot.key not in present]


def lock_outputs(stack: ExitStack, base: Path, output: Path, inventory: CostInventory) -> None:
    paths = {base / "budget_runner.lock", base / "supervisor.lock", output / "runner.lock"}
    paths.update(p / "runner.lock" for p in inventory.outputs if p.exists())
    for path in sorted(paths):
        handle = stack.enter_context(path.open("a+"))
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def execute(
    root: Path, output: Path, policy_path: Path, *, run: bool, limit: int | None = None, retries: bool = False
) -> dict:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    base = output.parent
    policy = BudgetPolicy.load(policy_path, base)
    if output.resolve() not in policy.inventory.outputs:
        raise ValueError("current study absent from total-budget inventory")
    manifest = read_json(output / "manifest.json")
    policy_sha = file_sha(policy_path)
    runner_sha = file_sha(Path(__file__))
    if digest(manifest) != policy.manifest_sha256:
        raise ValueError("operational policy refers to another frozen manifest")
    validate_manifest(manifest)
    verify_sources(manifest, root)
    with ExitStack() as stack:
        lock_outputs(stack, base, output, policy.inventory)
        # Only explicit paid/resume mode may adopt completed orphan outcomes.
        # Dry-run checks evidence without changing the paid-attempt ledger.
        for directory in policy.inventory.outputs:
            if directory.exists():
                if run:
                    reconcile(directory, read_json(directory / "manifest.json"))
                else:
                    rows = read_jsonl(directory / "attempts.jsonl")
                    recorded = {(r["slot_id"], r["attempt"]) for r in rows}
                    for job_path in directory.glob("attempts/*/job.json"):
                        job = read_json(job_path)
                        if (job["slot"]["slot_id"], job["attempt"]) not in recorded:
                            raise ValueError("unreconciled attempt; adopt it explicitly before dry-run")
                    for row in rows:
                        outcome = directory / row["outcome_path"]
                        if file_sha(outcome) != row["outcome_sha256"]:
                            raise ValueError("saved outcome changed")
                        if any(
                            file_sha(outcome.parent / name) != expected
                            for name, expected in row["artifact_sha256"].items()
                        ):
                            raise ValueError("saved attempt artifact changed")
        ledger = read_jsonl(output / "attempts.jsonl")
        if not smoke_ready(output, ledger, manifest):
            raise ValueError("four original smoke attempts must pass validation")
        if any(r["status"] == "budget_stop" for r in ledger):
            raise ValueError("a prior budget stop is final for this operational run")
        if len(ledger) >= 3 and all(r["status"] != "valid" for r in ledger[-3:]):
            raise ValueError("three consecutive execution failures require diagnosis")
        snapshot = policy.snapshot()
        policy.verify_baseline()
        initial_requests = snapshot["observed_requests"]
        result = {
            "state": "dry_run",
            "model_calls_started": 0,
            "combined_cap_rmb": policy.cap_rmb,
            "remaining_conservative_rmb": policy.remaining_rmb(snapshot),
            "remaining_primary_slots": len(remaining_slots(manifest, ledger)),
            "eligible_retry_slots": len(remaining_slots(manifest, ledger, retries=True)),
            **snapshot,
        }
        if not run:
            return result
        # Credentials are loaded only after --run, source checks and all locks.
        from dotenv import dotenv_values

        env = os.environ.copy()
        values = dotenv_values(root / ".env")
        for key in ("OPENAI_API_KEY", "OPENAI_API_BASE"):
            if values.get(key):
                env[key] = values[key]
        if not env.get("OPENAI_API_KEY") or not env.get("OPENAI_API_BASE"):
            raise ValueError("missing provider credentials")
        if not env["OPENAI_API_BASE"].startswith("https://dashscope.aliyuncs.com/"):
            raise ValueError("provider must match the frozen billing monitor")
        performed = 0
        result["state"] = "running_under_global_cap"
        status = base / "combined_execution_status.json"
        write_json(status, result)
        try:
            for slot in remaining_slots(manifest, ledger, retries=retries):
                if file_sha(policy_path) != policy_sha or file_sha(Path(__file__)) != runner_sha:
                    raise ValueError("operational policy or runner changed during execution")
                verify_sources(manifest, root)
                policy.verify_baseline()
                snapshot = policy.snapshot()
                allowance = min(
                    policy.allowance(snapshot),
                    manifest["budget_cap_rmb"] - sum(r["billing"]["budget_debit_rmb"] for r in ledger),
                )
                if allowance <= 0 or len(ledger) >= manifest["total_attempt_limit"]:
                    result["state"] = "stopped_at_operational_limit"
                    break
                attempt = 1 if retries else 0
                if retries:
                    if sum(r["attempt"] > 0 for r in ledger) >= manifest["additional_attempt_limit"]:
                        result["state"] = "stopped_at_operational_limit"
                        break
                    first = next(r for r in ledger if r["slot_id"] == slot.key and r["attempt"] == 0)
                    diagnostic = read_json(policy_path).get("diagnosed_retry_outcomes", {})
                    if diagnostic.get(slot.key) != first["outcome_sha256"]:
                        raise ValueError("infrastructure retry lacks a diagnosed original outcome hash")
                directory = output / "attempts" / f"{slot.key}-a{attempt:02d}"
                directory.mkdir(exist_ok=False)
                write_json(
                    directory / "job.json",
                    {
                        "manifest": manifest,
                        "slot": slot.as_dict(),
                        "attempt": attempt,
                        "remaining_budget_rmb": allowance,
                        "operational_budget": {
                            "combined_cap_rmb": policy.cap_rmb,
                            "prior_cost_snapshot": snapshot,
                            "policy_sha256": policy_sha,
                            "runner_sha256": runner_sha,
                        },
                    },
                    exclusive=True,
                )
                started = time.monotonic()
                run_child(
                    [
                        str(root / "tau2-bench-baseline/.venv/bin/python"),
                        str(Path(__file__).with_name("study_worker.py")),
                        "--job",
                        str(directory / "job.json"),
                    ],
                    cwd=root / "tau2-bench-baseline",
                    env=env,
                    log=directory / "worker.log",
                    timeout=manifest["deadline_seconds"],
                )
                ledger = reconcile(output, manifest)
                row = next(r for r in ledger if r["slot_id"] == slot.key and r["attempt"] == attempt)
                snapshot = policy.snapshot()
                performed += 1
                result.update(
                    **snapshot,
                    remaining_conservative_rmb=policy.remaining_rmb(snapshot),
                    remaining_primary_slots=len(remaining_slots(manifest, ledger)),
                    last_slot=slot.key,
                    last_status=row["status"],
                    last_wall_seconds=time.monotonic() - started,
                    new_attempts=performed,
                    model_calls_started=snapshot["observed_requests"] - initial_requests,
                )
                write_json(
                    output / "status.json",
                    {
                        "study_id": manifest["study_id"],
                        "attempts_finished": len(ledger),
                        "formal_first_attempts_finished": sum(
                            r["phase"] == "formal" and r["attempt"] == 0 for r in ledger
                        ),
                        "budget_debit_rmb": sum(r["billing"]["budget_debit_rmb"] for r in ledger),
                        "known_list_price_rmb": sum(r["billing"]["known_list_price_rmb"] for r in ledger),
                        "last_slot": slot.key,
                        "last_status": row["status"],
                        "last_wall_seconds": result["last_wall_seconds"],
                        "operational_budget_policy_sha256": file_sha(policy_path),
                    },
                )
                if snapshot["conservative_discounted_debit_rmb"] > policy.cap_rmb:
                    raise ValueError("observed usage exceeded reservation; all further execution stopped")
                if row["status"] == "budget_stop":
                    result["state"] = "stopped_at_request_reservation_gate"
                elif len(ledger) >= 3 and all(r["status"] != "valid" for r in ledger[-3:]):
                    result["state"] = "stopped_for_consecutive_execution_failures"
                elif limit is not None and performed >= limit:
                    result["state"] = "stopped_at_requested_attempt_limit"
                write_json(status, result)
                print(result, flush=True)
                if result["state"].startswith("stopped_"):
                    break
            else:
                result["state"] = "eligible_retries_finished" if retries else "primary_schedule_finished"
        except BaseException:
            # run_child saves and stops its current worker before releasing locks.
            reconcile(output, manifest)
            result.update(**policy.snapshot(), state="stopped_after_exception_or_cancellation")
            write_json(status, result)
            raise
        write_json(status, result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-infrastructure", action="store_true")
    args = parser.parse_args()

    def cancel(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, cancel)
    print(
        execute(
            Path(__file__).resolve().parents[3],
            args.input.resolve(),
            args.policy.resolve(),
            run=args.run,
            limit=args.limit,
            retries=args.retry_infrastructure,
        )
    )


if __name__ == "__main__":
    main()
