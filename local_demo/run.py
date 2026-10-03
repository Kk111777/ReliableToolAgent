"""Run the deterministic ReliableToolAgent experiment harness."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from smolagents import Model, OpenAIServerModel, Tool, ToolCallingAgent
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole
from smolagents.utils import normalize_tool_arguments


try:  # Support both ``python -m local_demo.run`` and direct execution.
    from .cases import TASK_CASES, FaultRule, TaskCase, get_case
except ImportError:  # pragma: no cover - only used for direct script execution.
    from cases import TASK_CASES, FaultRule, TaskCase, get_case


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


def upstream_revision(root: Path = ROOT) -> str | None:
    """Optional provenance; forks and source archives may lack upstream/main."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "upstream/main^{commit}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


class TemporaryUnavailable(TimeoutError):
    """A deterministic, retryable tool failure."""

    structured_error_type = "TEMPORARY_UNAVAILABLE"


class UnknownSKU(ValueError):
    """The caller supplied an order ID where a SKU was required."""

    structured_error_type = "UNKNOWN_ENTITY"


class OrderNotFound(LookupError):
    """The requested order is not present in the local database."""

    structured_error_type = "TARGET_NOT_FOUND"


class PermissionDenied(PermissionError):
    """A fixture-only permission failure for structured error tests."""

    structured_error_type = "PERMISSION_DENIED"


class FaultInjector:
    """Inject configured failures using deterministic call identity and count."""

    def __init__(self, task_id: str, rules: tuple[FaultRule, ...] = ()):
        self.task_id = task_id
        self._rules = {self._key(rule.task_id, rule.tool_name, rule.arguments): rule for rule in rules}
        self._counts: Counter[tuple[str, str, str]] = Counter()

    @staticmethod
    def normalize_arguments(arguments: dict[str, Any]) -> str:
        """Produce a stable representation for equivalent JSON arguments."""

        return normalize_tool_arguments(arguments)

    @classmethod
    def _key(cls, task_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[str, str, str]:
        return task_id, tool_name, cls.normalize_arguments(arguments)

    def maybe_raise(self, tool_name: str, arguments: dict[str, Any]) -> None:
        key = self._key(self.task_id, tool_name, arguments)
        self._counts[key] += 1
        rule = self._rules.get(key)
        if rule is None or self._counts[key] not in rule.fail_on_calls:
            return

        error_classes = {
            "TemporaryUnavailable": TemporaryUnavailable,
            "UnknownSKU": UnknownSKU,
            "OrderNotFound": OrderNotFound,
        }
        error_class = error_classes.get(rule.error_type, RuntimeError)
        raise error_class(rule.message)


class OrderTool(Tool):
    """Backward-compatible single-order tool used by the original smoke tests."""

    name = "get_order"
    description = "Look up an order and return its SKU and shipping status."
    inputs = {"order_id": {"type": "string", "description": "Order identifier, e.g. ORDER_001."}}
    output_type = "string"

    def forward(self, order_id: str) -> str:
        if order_id != "ORDER_001":
            raise ValueError(f"Unknown order: {order_id}")
        return json.dumps({"order_id": order_id, "sku": "SKU_A", "status": "unshipped"})


class OrderDetailTool(Tool):
    """Read order details from the deterministic local database."""

    name = "get_order_detail"
    description = "Look up an order and return its SKU."
    inputs = {"order_id": {"type": "string", "description": "Order identifier."}}
    output_type = "string"
    database = {
        "ORDER_001": {"sku": "SKU_A"},
        "ORDER_002": {"sku": "SKU_B"},
        "ORDER_003": {"sku": "SKU_C"},
    }

    def forward(self, order_id: str) -> str:
        order = self.database.get(order_id)
        if order is None:
            raise OrderNotFound(f"OrderNotFound: {order_id}")
        return json.dumps({"order_id": order_id, **order})


class InventoryTool(Tool):
    """Read deterministic inventory and optionally inject a configured fault."""

    name = "get_inventory"
    description = "Return stock for a SKU obtained from an order."
    inputs = {"sku": {"type": "string", "description": "A SKU identifier, not an order identifier."}}
    output_type = "string"
    database = {"SKU_A": 7, "SKU_B": 12, "SKU_C": 3}

    def __init__(
        self,
        transient_failure: bool = False,
        task_id: str = "legacy",
        fault_injector: FaultInjector | None = None,
    ):
        super().__init__()
        self.transient_failure = transient_failure
        self.task_id = task_id
        self.fault_injector = fault_injector
        self.attempts = 0

    def forward(self, sku: str) -> str:
        self.attempts += 1
        if self.fault_injector is not None:
            self.fault_injector.maybe_raise(self.name, {"sku": sku})
        elif self.transient_failure and self.attempts == 1:
            raise TemporaryUnavailable("TemporaryUnavailable: retry this read-only call once")

        if sku not in self.database:
            raise UnknownSKU(f"Unknown SKU: {sku}")
        return json.dumps({"sku": sku, "stock": self.database[sku]})


class ScriptedModel(Model):
    """Return a known transcript so the platform can be tested without an LLM."""

    def __init__(self, case: TaskCase | None = None, fault: bool = False):
        super().__init__(model_id="scripted-integration-fixture")
        if case is None:
            case = get_case("T02" if fault else "T01")
        self.task_id = case.task_id
        self.calls = 0
        self.actions = [(action.tool_name, action.arguments) for action in case.actions]

    def generate(self, messages, **kwargs):
        if self.calls >= len(self.actions):
            raise RuntimeError(f"Fixture {self.task_id} exceeded its expected transcript")
        name, arguments = self.actions[self.calls]
        self.calls += 1
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="Scripted integration fixture; no LLM inference.",
            tool_calls=[
                ChatMessageToolCall(
                    id=f"call_{self.calls}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                )
            ],
        )


def _task_prompt(case: TaskCase) -> str:
    return (
        f"{case.query} Use the available tools and return the expected business result with final_answer. "
        "For an expected business error, report its status instead of inventing inventory."
    )


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _error_type(error: dict[str, Any] | None) -> str | None:
    if not error:
        return None
    message = error.get("message", "")
    for candidate, structured_type in (
        ("TemporaryUnavailable", "TEMPORARY_UNAVAILABLE"),
        ("UnknownSKU", "UNKNOWN_ENTITY"),
        ("OrderNotFound", "TARGET_NOT_FOUND"),
    ):
        if candidate in message:
            return structured_type
    return error.get("type")


def final_output_matches(expected: Any, actual: Any, trajectory: list[dict[str, Any]] | None = None) -> bool:
    """Accept exact structured answers and equivalent concise natural language."""

    if actual == expected:
        return True
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(actual.get(key) == value for key, value in expected.items())
    if not isinstance(expected, dict) or not isinstance(actual, str):
        return False

    if expected.get("status") == "order_not_found":
        return any(
            phrase in actual.lower() for phrase in ("order_not_found", "order not found", "订单不存在", "不存在")
        )
    if expected.get("status") == "duplicate_failure_observed":
        return any(
            phrase in actual.lower() for phrase in ("duplicate_failure_observed", "duplicate", "重复", "相同失败")
        )
    successful_observations = [
        record["result"]
        for record in trajectory or []
        if record["error"] is None and isinstance(record["result"], dict)
    ]
    observed_values = {key: value for observation in successful_observations for key, value in observation.items()}
    return (
        str(expected.get("stock")) in actual
        and (str(expected.get("order_id")) in actual or observed_values.get("order_id") == expected.get("order_id"))
        and (str(expected.get("sku")) in actual or observed_values.get("sku") == expected.get("sku"))
    )


def _trajectory(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert verbose framework memory into one inspectable record per call."""

    records: list[dict[str, Any]] = []
    for step in run["steps"]:
        if "step_number" not in step:
            continue
        per_call_results = step.get("tool_call_results")
        if per_call_results is not None:
            for call in per_call_results:
                error = {"type": call.get("error_type"), "message": call.get("error")} if call.get("error") else None
                tool_name = call["tool_name"]
                arguments = call.get("arguments")
                normalized_arguments = call.get("normalized_arguments")
                if isinstance(normalized_arguments, dict):
                    normalized_arguments = normalize_tool_arguments(normalized_arguments)
                elif normalized_arguments is None:
                    normalized_arguments = (
                        FaultInjector.normalize_arguments(arguments) if isinstance(arguments, dict) else str(arguments)
                    )
                records.append(
                    {
                        "step_index": step["step_number"],
                        "call_index": call["call_index"],
                        "tool": tool_name,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "normalized_arguments": normalized_arguments,
                        "status": call["status"],
                        "result": _parse_json(call.get("result")) if call["status"] == "success" else None,
                        "error": error,
                        "error_type": call.get("error_type"),
                        "retryable_same_call": call.get("retryable_same_call"),
                        "scope": call.get("scope"),
                        "message": call.get("message"),
                        "details": call.get("details"),
                        "block_reason": call.get("block_reason"),
                        "previous_error_type": call.get("previous_error_type"),
                    }
                )
            continue
        step_error = step.get("error")
        tool_calls = step.get("tool_calls") or []
        if not tool_calls:
            # smolagents records model output before execution. If execution raises,
            # the later memory_step.tool_calls assignment is skipped, so recover the
            # attempted call from model_output_message for complete error telemetry.
            tool_calls = (step.get("model_output_message") or {}).get("tool_calls") or []
        for call_index, tool_call in enumerate(tool_calls, start=1):
            function = tool_call["function"]
            tool_name = function["name"]
            arguments = function.get("arguments")
            error = step_error if tool_name != "final_answer" else None
            records.append(
                {
                    "step_index": step["step_number"],
                    "call_index": call_index,
                    "tool": tool_name,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "normalized_arguments": (
                        FaultInjector.normalize_arguments(arguments) if isinstance(arguments, dict) else str(arguments)
                    ),
                    "status": "error" if error else "success",
                    "result": None if error else _parse_json(step.get("observations")),
                    "error": error,
                    "error_type": _error_type(error),
                    "retryable_same_call": None,
                    "scope": None,
                    "message": None,
                    "details": None,
                    "block_reason": None,
                    "previous_error_type": None,
                }
            )
    return records


def evaluate_case(case: TaskCase, result: Any, mode: str = "scripted") -> dict[str, Any]:
    """Evaluate business outcome and platform metrics separately."""

    run = result.dict()
    output = _parse_json(result.output)
    trajectory = _trajectory(run)
    business_calls = [record for record in trajectory if record["tool_name"] != "final_answer"]
    failed_calls = [record for record in business_calls if record["error"]]
    successful_after_error = (
        any(
            record["error"] is None and record["step_index"] > failed_calls[0]["step_index"]
            for record in business_calls
        )
        if failed_calls
        else False
    )
    failed_keys = Counter(
        (record["tool_name"], record["normalized_arguments"], record["error_type"]) for record in failed_calls
    )
    same_failed_call_count = max(failed_keys.values(), default=0)
    expected = case.expected
    output_matches = final_output_matches(expected["final_output"], output, trajectory)
    trajectory_matches_expected = (
        output_matches
        and len(business_calls) == expected["tool_calls"]
        and len(failed_calls) == expected["errors"]
        and (successful_after_error and output_matches) == expected["recovered"]
        and same_failed_call_count >= expected.get("same_failed_call_count", 0)
        and run["state"] == "success"
    )
    business_success = output_matches and run["state"] == "success"
    metrics = {
        "task_id": case.task_id,
        "task_success": trajectory_matches_expected if mode == "scripted" else business_success,
        "business_success": business_success,
        "trajectory_matches_expected": trajectory_matches_expected,
        "model_calls": sum(1 for step in run["steps"] if step.get("model_output_message")),
        "tool_calls": len(business_calls),
        "errors_encountered": len(failed_calls),
        "recovered": successful_after_error and output_matches,
        "stop_reason": (
            "final_answer" if any(record["tool_name"] == "final_answer" for record in trajectory) else run["state"]
        ),
        "same_failed_call_count": same_failed_call_count,
    }
    return {"output": output, "metrics": metrics, "trajectory": trajectory}


def build_api_model(
    model_id: str | None = None,
    *,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> OpenAIServerModel:
    """Build the configured OpenAI-compatible model without changing agent behavior."""

    load_dotenv(ROOT / ".env", override=False)
    missing = [name for name in ("MODEL_ID", "OPENAI_API_BASE", "OPENAI_API_KEY") if not os.getenv(name)]
    if missing:
        raise ValueError("Configure .env first: " + ", ".join(missing))
    selected_model_id = model_id or os.environ["MODEL_ID"]
    model_kwargs: dict[str, Any] = {
        "max_tokens": 512,
        "client_kwargs": {"timeout": 60.0, "max_retries": 0},
    }
    if temperature is not None:
        model_kwargs["temperature"] = temperature
    # Qwen3.8-Flash thinking mode rejects smolagents' default
    # tool_choice="required". Disable thinking for the tool-calling baseline.
    if reasoning_effort is not None:
        model_kwargs["reasoning_effort"] = reasoning_effort
    elif selected_model_id.lower() == "qwen3.8-flash":
        model_kwargs["reasoning_effort"] = os.getenv("REASONING_EFFORT", "none")
    return OpenAIServerModel(
        model_id=selected_model_id,
        api_base=os.environ["OPENAI_API_BASE"],
        api_key=os.environ["OPENAI_API_KEY"],
        **model_kwargs,
    )


def run_case(task_id: str = "T01", mode: str = "scripted", fault: bool = False) -> dict[str, Any]:
    """Run one deterministic case and return its report."""

    if fault and task_id == "T01":  # Preserve the original ``--fault`` interface.
        task_id = "T02"
    case = get_case(task_id)
    model = ScriptedModel(case=case) if mode == "scripted" else build_api_model()

    fault_injector = FaultInjector(case.task_id, case.fault_rules)
    inventory = InventoryTool(task_id=case.task_id, fault_injector=fault_injector)
    agent = ToolCallingAgent(
        tools=[OrderDetailTool(), inventory],
        model=model,
        max_steps=6,
        max_tool_threads=1,
        verbosity_level=0,
    )
    result = agent.run(_task_prompt(case), return_full_result=True)
    run = result.dict()
    evaluated = evaluate_case(case, result, mode=mode)
    return {
        "task_id": case.task_id,
        "query": case.query,
        "expected": case.expected,
        "mode": mode,
        "scope": "integration_platform_harness",
        "fault": bool(case.fault_rules),
        **evaluated,
        "run": run,
        "upstream_commit": upstream_revision(),
    }


def _write_report(report: dict[str, Any]) -> Path:
    ARTIFACTS.mkdir(exist_ok=True)
    destination = ARTIFACTS / f"{report['mode']}-{report['task_id']}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scripted", "api"], default="scripted")
    parser.add_argument("--task-id", choices=[case.task_id for case in TASK_CASES])
    parser.add_argument("--fault", action="store_true", help="Compatibility alias for running T02")
    args = parser.parse_args()

    task_ids = [args.task_id] if args.task_id else (["T02"] if args.fault else [case.task_id for case in TASK_CASES])
    reports = [run_case(task_id, mode=args.mode) for task_id in task_ids]
    paths = [_write_report(report) for report in reports]
    summary = {
        "passed": all(report["metrics"]["task_success"] for report in reports),
        "cases": [
            {"task_id": report["task_id"], **report["metrics"], "report": str(path)}
            for report, path in zip(reports, paths)
        ],
    }
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
