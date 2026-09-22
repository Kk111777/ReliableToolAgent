"""Infrastructure-only retry wrapper for the official NL evaluator.

This module is intentionally kept outside ``src/tau2``.  It retries only when
the evaluator model returns output that the unchanged official parser cannot
consume.  Request failures remain governed by LiteLLM's ``num_retries``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


PARSE_ERRORS = (json.JSONDecodeError, AttributeError, KeyError, TypeError)


def validate_official_nl_payload(content: str | None) -> None:
    """Raise the same class of parse/schema errors the official parser can hit."""

    data = json.loads(content or "")
    if not isinstance(data, dict):
        raise AttributeError("NL evaluator payload must be an object")

    results = data.get("results", [])
    if not isinstance(results, list):
        raise TypeError("NL evaluator results must be a list")
    for result in results:
        if not isinstance(result, dict):
            raise TypeError("NL evaluator result must be an object")
        for key in ("expectedOutcome", "metExpectation", "reasoning"):
            if key not in result:
                raise KeyError(key)


@dataclass
class EvaluatorRetryRecorder:
    """Collect per-evaluation retry telemetry for a sidecar artifact."""

    records: list[dict[str, Any]] = field(default_factory=list)
    current_task_id: str | None = None

    def set_task(self, task_id: str | None) -> None:
        self.current_task_id = task_id

    def record(
        self,
        retry_count: int,
        *,
        invalid_responses: list[str],
        error: str | None = None,
    ) -> None:
        self.records.append(
            {
                "task_id": self.current_task_id,
                "evaluator_retry_count": retry_count,
                "invalid_response_count": len(invalid_responses),
                "invalid_responses": invalid_responses,
                "error": error,
            }
        )


def install_evaluator_parse_retry(
    evaluator_module: Any,
    recorder: EvaluatorRetryRecorder,
    *,
    max_parse_retries: int = 2,
) -> Callable[[], None]:
    """Patch only the evaluator module's model call and return an uninstall hook."""

    if max_parse_retries < 0:
        raise ValueError("max_parse_retries must be non-negative")

    original_generate = evaluator_module.generate

    def retrying_generate(*args: Any, **kwargs: Any) -> Any:
        retry_count = 0
        invalid_responses: list[str] = []
        while True:
            response = original_generate(*args, **kwargs)
            try:
                validate_official_nl_payload(response.content)
            except PARSE_ERRORS as exc:
                invalid_responses.append(response.content or "")
                if retry_count >= max_parse_retries:
                    recorder.record(
                        retry_count,
                        invalid_responses=invalid_responses,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    raise
                retry_count += 1
                continue

            recorder.record(
                retry_count,
                invalid_responses=invalid_responses,
            )
            return response

    evaluator_module.generate = retrying_generate

    def uninstall() -> None:
        evaluator_module.generate = original_generate

    return uninstall
