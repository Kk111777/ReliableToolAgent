"""Versioned adapters around the unchanged v1 worker; never a v1 result repair.

Each worker is a single isolated process. Patches are scoped and restored even on
deadline/budget cancellation. Retries pass through the original billing monitor.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from engineering_diagnostics import (
    EmptyModelOutputError,
    EvaluatorPayloadError,
    normalize_evaluator_payload,
    safe_exception_diagnostic,
)
from frozen_study import append_json, budget_totals, digest, read_json, read_jsonl, write_json
from study_worker import StudyBudget, StudyDeadline


class EmptyUserOutput(EmptyModelOutputError):
    """No text or tool calls after the declared response retry allowance."""


@dataclass
class ResponseAdapters:
    output: Path
    expected_outcomes: list[str]
    user_empty_retries: int = 1
    evaluator_parse_retries: int = 2

    def __post_init__(self):
        if self.user_empty_retries != 1 or self.evaluator_parse_retries != 2:
            raise ValueError("engineering-v2 fixes response retries at one/two")

    def record(self, role: str, attempt: int, response, **fields):
        raw = getattr(response, "raw_data", None) or {}
        reasons = [r.get("finish_reason") for r in raw.get("choices", [])]
        append_json(
            self.output / "response_adapters.jsonl",
            {
                "role": role,
                "response_attempt": attempt,
                "response_sha256": digest(raw or {"content": response.content}),
                "completion_call_index": max(
                    (r["call_index"] for r in read_jsonl(self.output / "calls.jsonl")), default=0
                ),
                "finish_reasons": [r if r in {"stop", "length", "tool_calls"} else "other" for r in reasons],
                **fields,
            },
        )

    def user(self, generate: Callable) -> Callable:
        def wrapped(*args, **kwargs):
            # Repeat only a content-less response, not a tool failure or exception.
            # History is not appended again: the native simulator calls this once.
            for attempt in range(self.user_empty_retries + 1):
                response = generate(*args, **kwargs)
                text = response.content
                usable = bool(isinstance(text, str) and text.strip()) or bool(response.tool_calls)
                self.record("user", attempt, response, accepted=usable, empty=not usable)
                if usable:
                    return response
            raise EmptyUserOutput()

        return wrapped

    def evaluator(self, generate: Callable) -> Callable:
        def wrapped(*args, **kwargs):
            for attempt in range(self.evaluator_parse_retries + 1):
                response = generate(*args, **kwargs)
                try:
                    content = normalize_evaluator_payload(response.content, expected_outcomes=self.expected_outcomes)
                except (ValueError, TypeError) as exc:
                    self.record("evaluator", attempt, response, accepted=False, normalized=False)
                    if attempt == self.evaluator_parse_retries:
                        raise exc
                else:
                    self.record("evaluator", attempt, response, accepted=True, normalized=content != response.content)
                    # Preserve native raw_data/usage; change only the parser's input.
                    return response.model_copy(update={"content": content})

        return wrapped


@contextmanager
def install_adapters(adapters, *, user_module, evaluator_module, simulation_module, trusted_root):
    originals = (user_module.generate, evaluator_module.generate, simulation_module.run_simulation)

    def diagnosed_simulation(*args, **kwargs):
        try:
            return originals[2](*args, **kwargs)
        except BaseException as exc:
            stage = (
                "evaluation"
                if any(r.get("role") == "evaluator" for r in read_jsonl(adapters.output / "calls.jsonl"))
                else "simulation"
            )
            diagnostic = safe_exception_diagnostic(
                exc,
                stage=stage,
                trusted_root=trusted_root,
                control_exception_types={StudyDeadline: "deadline", StudyBudget: "budget"},
            )
            append_json(adapters.output / "diagnostics.jsonl", diagnostic)
            # The frozen writer emits type(exc).__name__. Do not forward an
            # external class name (even a ValueError subclass) into that field.
            local_control = type(exc) in {StudyDeadline, StudyBudget, EmptyUserOutput, EvaluatorPayloadError}
            if not local_control and type(exc).__name__ != diagnostic["exception_type"]:
                raise RuntimeError() from exc
            raise

    user_module.generate = adapters.user(originals[0])
    evaluator_module.generate = adapters.evaluator(originals[1])
    simulation_module.run_simulation = diagnosed_simulation
    try:
        yield
    finally:
        user_module.generate, evaluator_module.generate, simulation_module.run_simulation = originals


def run(job: dict, output: Path) -> dict:
    import study_worker
    import tau2.evaluator.evaluator_nl_assertions as evaluator_module
    import tau2.runner.simulation as simulation_module
    import tau2.user.user_simulator as user_module
    from tau2.domains.retail.environment import get_tasks

    if job["manifest"].get("engineering_version") != "engineering-v2":
        raise ValueError("requires a separate engineering-v2 manifest")
    task = next(t for t in get_tasks("base") if t.id == job["slot"]["task_id"])
    expected = task.evaluation_criteria.nl_assertions if task.evaluation_criteria else []
    adapters = ResponseAdapters(output, expected or [])
    with install_adapters(
        adapters,
        user_module=user_module,
        evaluator_module=evaluator_module,
        simulation_module=simulation_module,
        trusted_root=Path(__file__).resolve().parents[3],
    ):
        return study_worker.run(job, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args()
    job, output = read_json(args.job), args.job.parent
    try:
        result = run(job, output)
    except BaseException as exc:
        diagnostic = safe_exception_diagnostic(
            exc,
            stage="setup",
            trusted_root=Path(__file__).resolve().parents[3],
            control_exception_types={StudyDeadline: "deadline", StudyBudget: "budget"},
        )
        append_json(output / "diagnostics.jsonl", diagnostic)
        result = {
            **job["slot"],
            "study_id": job["manifest"]["study_id"],
            "attempt": job["attempt"],
            "status": "timeout"
            if isinstance(exc, StudyDeadline)
            else "budget_stop"
            if isinstance(exc, StudyBudget)
            else "infrastructure_error",
            "error_class": diagnostic["exception_type"],
            "metrics": {},
            "billing": budget_totals(read_jsonl(output / "requests.jsonl") or read_jsonl(output / "calls.jsonl")),
        }
        if not (output / "outcome.json").exists():
            write_json(output / "outcome.json", result, exclusive=True)
    print({"slot_id": result["slot_id"], "status": result["status"]})


if __name__ == "__main__":
    main()
