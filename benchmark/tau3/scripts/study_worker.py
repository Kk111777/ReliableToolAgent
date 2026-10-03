"""One isolated native tau2 attempt. Secrets stay in environment variables."""

from __future__ import annotations

import argparse
import json
import signal
import time
import uuid
from pathlib import Path

from evaluator_retry_wrapper import PARSE_ERRORS, validate_official_nl_payload
from frozen_study import (
    analyze_simulation,
    append_json,
    budget_totals,
    canonical,
    estimate_rmb,
    file_sha,
    read_json,
    read_jsonl,
    usage_cost,
    write_json,
)


class StudyDeadline(BaseException):
    """Bypass SDK retries and broad native Exception handlers on cancellation."""


class StudyBudget(BaseException):
    """Stop before a request whose reservation would exceed the remaining cap."""


class BillingMonitor:
    def __init__(self, path: Path, budget: float, context: dict, role):
        self.path, self.budget, self.context, self.role = path, budget, context, role
        self.call_index = 0
        self.original = None
        self.request_index = 0
        self.request_path = path.with_name("requests.jsonl")
        self.http_originals = None

    def install(self, llm_module) -> None:
        self.original = llm_module.completion
        llm_module.completion = self.completion
        import httpx

        self.http_originals = (httpx.Client.send, httpx.AsyncClient.send)
        monitor = self

        def send(client, request, **kwargs):
            event = monitor.start_http(request)
            try:
                response = monitor.http_originals[0](client, request, **kwargs)
                if event:
                    response.read()
                    monitor.finish_http(event, response)
                return response
            except BaseException as exc:
                if event:
                    monitor.fail_http(event, exc)
                raise

        async def async_send(client, request, **kwargs):
            event = monitor.start_http(request)
            try:
                response = await monitor.http_originals[1](client, request, **kwargs)
                if event:
                    await response.aread()
                    monitor.finish_http(event, response)
                return response
            except BaseException as exc:
                if event:
                    monitor.fail_http(event, exc)
                raise

        httpx.Client.send, httpx.AsyncClient.send = send, async_send

    def uninstall(self, llm_module):
        import httpx

        llm_module.completion = self.original
        if self.http_originals:
            httpx.Client.send, httpx.AsyncClient.send = self.http_originals

    def start_http(self, request):
        if request.url.host != "dashscope.aliyuncs.com" or request.method != "POST":
            return None
        payload = json.loads(request.content)
        if payload.get("stream"):
            raise StudyBudget()  # This study is non-streaming; never silently bypass usage capture.
        model = payload["model"]
        prompt_upper = len(request.content) + 1024 + 32 * len(payload.get("messages") or [])
        if payload.get("max_completion_tokens") is None:
            raise StudyBudget()
        output_upper = payload["max_completion_tokens"] + 10  # Documented provider tolerance.
        reservation = estimate_rmb(model, prompt_upper, output_upper)
        if budget_totals(read_jsonl(self.request_path))["budget_debit_rmb"] + reservation > self.budget:
            raise StudyBudget()
        self.request_index += 1
        event = {
            **self.context,
            "call_index": self.request_index,
            "completion_call_index": self.call_index,
            "role": self.role(),
            "model": model,
            "state": "http_started",
            "usage": None,
            "known_list_price_rmb": None,
            "budget_debit_rmb": reservation,
            "precall_reservation_rmb": reservation,
            "prompt_upper": prompt_upper,
            "completion_upper": output_upper,
        }
        append_json(self.request_path, event)
        return event

    def finish_http(self, event, response):
        try:
            usage = response.json().get("usage")
        except (ValueError, AttributeError):
            usage = None
        known = usage_cost(event["model"], usage)
        within = bool(
            known is not None
            and usage["prompt_tokens"] <= event["prompt_upper"]
            and usage["completion_tokens"] <= event["completion_upper"]
        )
        append_json(
            self.request_path,
            {
                **event,
                "state": "http_returned",
                "http_status": response.status_code,
                "usage": usage,
                "known_list_price_rmb": known,
                "budget_debit_rmb": known if within else max(event["budget_debit_rmb"], known or 0),
                "usage_within_reservation": within,
            },
        )
        if known is not None and not within:
            raise StudyBudget()

    def fail_http(self, event, exc):
        # Retain a returned usage record if the bound check raised after it was saved.
        last = [r for r in read_jsonl(self.request_path) if r["call_index"] == event["call_index"]][-1]
        if last["state"] == "http_started":
            append_json(self.request_path, {**event, "state": "http_error", "error_class": type(exc).__name__})

    def observed(self):
        records = [r for r in read_jsonl(self.request_path) if r["completion_call_index"] == self.call_index]
        return budget_totals(records) if records else None

    def completion(self, *args, **kwargs):
        if args:
            raise ValueError("expected keyword-only native completion")
        model = kwargs["model"]
        request = {key: kwargs.get(key) for key in ("messages", "tools", "tool_choice")}
        # UTF-8 bytes plus chat framing overestimates text-token input. No prompt is logged.
        prompt_upper = len(canonical(request).encode()) + 1024 + 32 * len(kwargs.get("messages") or [])
        output_upper = kwargs.get("max_completion_tokens", kwargs["max_tokens"])
        if "max_completion_tokens" in kwargs:
            output_upper += 10
        retries = kwargs["num_retries"]
        reservation = estimate_rmb(model, prompt_upper, output_upper) * (retries + 1)
        used = budget_totals(read_jsonl(self.path))["budget_debit_rmb"]
        if used + reservation > self.budget:
            raise StudyBudget()
        self.call_index += 1
        event = {
            **self.context,
            "call_index": self.call_index,
            "role": self.role(),
            "model": model,
            "state": "started",
            "usage": None,
            "known_list_price_rmb": None,
            "budget_debit_rmb": reservation,
            "precall_reservation_rmb": reservation,
            "prompt_upper": prompt_upper,
            "completion_upper": output_upper,
            "configured_request_retries": retries,
            "actual_internal_retry_count": None,
            "retry_observation": "SDK-internal retries are not individually visible",
        }
        append_json(self.path, event)
        started = time.monotonic()
        try:
            response = self.original(**kwargs)
        except BaseException as exc:
            observed = self.observed()
            append_json(
                self.path,
                {
                    **event,
                    "state": "request_error",
                    "error_class": type(exc).__name__,
                    "elapsed_seconds": time.monotonic() - started,
                    **(
                        {
                            "known_list_price_rmb": observed["known_list_price_rmb"],
                            "budget_debit_rmb": observed["budget_debit_rmb"],
                            "observed_http_requests": observed["calls"],
                        }
                        if observed
                        else {}
                    ),
                },
            )
            raise
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        known = usage_cost(model, usage)
        within_bound = bool(
            usage
            and isinstance(usage.get("prompt_tokens"), int)
            and isinstance(usage.get("completion_tokens"), int)
            and usage["prompt_tokens"] <= prompt_upper
            and usage["completion_tokens"] <= output_upper
        )
        # Charge all possible internally retried requests conservatively. Failed attempts
        # may have generated output up to the cap, even if the final output was short.
        debit = (
            known + estimate_rmb(model, usage["prompt_tokens"], output_upper) * retries
            if known is not None and within_bound
            else reservation
        )
        if known is not None and not within_bound:
            debit = max(reservation, known * (retries + 1))
        observed = self.observed()
        if self.http_originals and not observed:
            # A different SDK transport must not silently turn unobserved calls into free calls.
            append_json(
                self.path, {**event, "state": "unobserved_transport", "usage": usage, "known_list_price_rmb": known}
            )
            raise StudyBudget()
        if observed:
            debit = observed["budget_debit_rmb"]
            known = observed["known_list_price_rmb"]
        append_json(
            self.path,
            {
                **event,
                "state": "returned",
                "usage": usage,
                "known_list_price_rmb": known,
                "budget_debit_rmb": debit,
                "usage_within_reservation": within_bound,
                "response_model": getattr(response, "model", None),
                "finish_reasons": [choice.finish_reason for choice in response.choices],
                "elapsed_seconds": time.monotonic() - started,
                "observed_http_requests": observed["calls"] if observed else None,
                "retry_observation": "HTTPX requests observed; lower transport connection attempts unknown"
                if observed
                else "not observed",
            },
        )
        if known is not None and not within_bound:
            raise StudyBudget()
        return response


def run(job: dict, output: Path) -> dict:
    import litellm
    import tau2.evaluator.evaluator_nl_assertions as evaluator_module
    import tau2.runner.simulation as simulation_module
    import tau2.utils.llm_utils as llm_module
    from loguru import logger
    from tau2.data_model.simulation import TextRunConfig
    from tau2.domains.retail.environment import get_tasks
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.runner.build import build_orchestrator

    logger.remove()  # Native debug logs can contain entire prompts/provider exception text.
    litellm.suppress_debug_info = True
    manifest = job["manifest"]
    root = Path(__file__).resolve().parents[3]
    for relative, expected in manifest["source_sha256"].items():
        if file_sha(root / relative) != expected:
            raise ValueError("frozen source changed before attempt")
    slot = job["slot"]
    simulation_id = str(uuid.uuid4())
    context = {"study_id": manifest["study_id"], **slot, "attempt": job["attempt"], "simulation_id": simulation_id}
    write_json(output / "identity.json", context, exclusive=True)
    task = next(task for task in get_tasks("base") if task.id == slot["task_id"])
    config = TextRunConfig(
        domain="retail",
        task_ids=[task.id],
        agent="llm_agent",
        user="user_simulator",
        llm_agent=manifest["agent_model"],
        llm_user=manifest["user_models"][slot["condition"]],
        llm_args_agent=manifest["model_args"],
        llm_args_user=manifest["model_args"],
        max_steps=manifest["max_steps"],
        max_errors=10,
        timeout=manifest["deadline_seconds"],
        seed=manifest["base_seed"],
        num_trials=manifest["trials"],
        max_concurrency=1,
        max_retries=0,
        auto_review=False,
    )
    orchestrator = build_orchestrator(config, task, seed=slot["seed"], simulation_id=simulation_id)
    stage = "simulation"
    simulation = None
    raw_path = output / "simulation.json"

    def snapshot():
        if simulation is not None:
            data = simulation.model_dump(mode="json")
        else:
            data = {
                "id": simulation_id,
                "task_id": task.id,
                "trial": slot["trial"],
                "seed": slot["seed"],
                "reward_info": None,
                "termination_reason": str(getattr(orchestrator, "termination_reason", "unfinished")),
                "messages": [m.model_dump(mode="json") for m in orchestrator.get_trajectory()],
            }
        data["trial"] = slot["trial"]
        write_json(raw_path, data)

    def terminate(signum, frame):
        raise StudyDeadline()

    signal.signal(signal.SIGTERM, terminate)
    original_step = orchestrator.step

    def checkpointed_step():
        try:
            return original_step()
        finally:
            snapshot()

    orchestrator.step = checkpointed_step
    monitor = BillingMonitor(
        output / "calls.jsonl",
        job["remaining_budget_rmb"],
        context,
        lambda: "evaluator" if stage == "evaluation" else orchestrator.to_role.value,
    )
    monitor.install(llm_module)
    original_evaluate = simulation_module.evaluate_simulation

    def tracked_evaluate(*args, **kwargs):
        nonlocal simulation, stage
        simulation = kwargs["simulation"]
        stage = "evaluation"
        snapshot()  # Preserve the full ungraded trajectory even if evaluation fails.
        return original_evaluate(*args, **kwargs)

    simulation_module.evaluate_simulation = tracked_evaluate
    evaluator_module.DEFAULT_LLM_NL_ASSERTIONS = manifest["evaluator_model"]
    evaluator_module.DEFAULT_LLM_NL_ASSERTIONS_ARGS = dict(manifest["model_args"])
    original_generate = evaluator_module.generate
    evaluator_index = 0

    def retrying_evaluator(*args, **kwargs):
        nonlocal evaluator_index
        evaluator_index += 1
        for parse_attempt in range(manifest["evaluator_parse_retries"] + 1):
            response = original_generate(*args, **kwargs)
            invalid = None
            try:
                validate_official_nl_payload(response.content)
            except PARSE_ERRORS as exc:
                invalid = exc
            append_json(
                output / "evaluator.jsonl",
                {
                    **context,
                    "evaluator_call_index": evaluator_index,
                    "parse_attempt": parse_attempt,
                    "completion_call_index": monitor.call_index,
                    "valid_payload": invalid is None,
                    "error_class": type(invalid).__name__ if invalid else None,
                    "invalid_response": response.content if invalid else None,
                },
            )
            if invalid is None:
                return response
            if parse_attempt == manifest["evaluator_parse_retries"]:
                raise invalid

    evaluator_module.generate = retrying_evaluator
    started = time.monotonic()
    status, error_class = "infrastructure_error", None
    try:
        snapshot()
        simulation = simulation_module.run_simulation(orchestrator, evaluation_type=EvaluationType.ALL)
        simulation.trial = slot["trial"]
        status = "timeout" if str(simulation.termination_reason.value) == "timeout" else "valid"
    except StudyDeadline:
        status, error_class = "timeout", "StudyDeadline"
    except StudyBudget:
        status, error_class = "budget_stop", "StudyBudget"
    except Exception as exc:
        error_class = type(exc).__name__
    finally:
        snapshot()
        evaluator_module.generate = original_generate
        simulation_module.evaluate_simulation = original_evaluate
        monitor.uninstall(llm_module)
    result = {
        **context,
        "status": status,
        "error_class": error_class,
        "stage": stage,
        "wall_seconds": time.monotonic() - started,
        "billing": budget_totals(read_jsonl(output / "requests.jsonl") or read_jsonl(output / "calls.jsonl")),
        "metrics": analyze_simulation(read_json(raw_path)),
    }
    write_json(output / "outcome.json", result, exclusive=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args()
    job = read_json(args.job)
    output = args.job.parent
    try:
        result = run(job, output)
    except Exception as exc:
        # Never serialize provider exception messages, URLs with credentials, or environment.
        result = {
            **job["slot"],
            "study_id": job["manifest"]["study_id"],
            "attempt": job["attempt"],
            "status": "infrastructure_error",
            "error_class": type(exc).__name__,
            "metrics": {},
            "billing": budget_totals(read_jsonl(output / "requests.jsonl") or read_jsonl(output / "calls.jsonl")),
        }
        if not (output / "outcome.json").exists():
            write_json(output / "outcome.json", result, exclusive=True)
    print(
        json.dumps(
            {
                "slot_id": result["slot_id"],
                "status": result["status"],
                "error_class": result.get("error_class"),
                "billing": result["billing"],
            }
        )
    )


if __name__ == "__main__":
    main()
