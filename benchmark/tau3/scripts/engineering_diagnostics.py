"""Offline contracts for a separately versioned worker; frozen workers stay unchanged.

Diagnostics contain metadata only. Caller-owned source/type allowlists must never
be constructed from exception messages, provider responses, or request data.
Payload normalization removes one exact outer Markdown fence, validates the
document, and returns the original inner JSON text without changing any values.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


STAGES = frozenset(
    {
        "setup",
        "startup",
        "source_verification",
        "simulation",
        "evaluation",
        "user_generation",
        "agent_generation",
        "request",
        "shutdown",
    }
)
CONTROL_TYPES = frozenset({"StudyDeadline", "StudyBudget", "Cancellation", "deadline", "budget"})
DEFAULT_TRUSTED_SOURCES = (
    "benchmark/tau3/scripts/engineering_diagnostics.py",
    "benchmark/tau3/scripts/engineering_worker.py",
    "benchmark/tau3/scripts/study_worker.py",
    "tau2-bench-baseline/src/tau2/data_model/message.py",
    "tau2-bench-baseline/src/tau2/orchestrator/orchestrator.py",
    "tau2-bench-baseline/src/tau2/user/user_simulator.py",
    "tau2-bench-baseline/src/tau2/evaluator/evaluator_nl_assertions.py",
)
_FUNCTION = re.compile(
    r"(?:[A-Za-z_][A-Za-z0-9_]{0,79}|<module>|<lambda>|<listcomp>|<dictcomp>|<setcomp>|<genexpr>)\Z"
)
_FENCE = re.compile(r"```(?:json)?\r?\n(?P<body>[\s\S]*?)\r?\n```\Z")
_ITEM_KEYS = {"expectedOutcome", "metExpectation", "reasoning"}
_SAFE_TYPES = (
    (json.JSONDecodeError, "JSONDecodeError"),
    (asyncio.CancelledError, "CancelledError"),
    (KeyboardInterrupt, "KeyboardInterrupt"),
    (SystemExit, "SystemExit"),
    (TimeoutError, "TimeoutError"),
    (ConnectionError, "ConnectionError"),
    (FileNotFoundError, "FileNotFoundError"),
    (PermissionError, "PermissionError"),
    (OSError, "OSError"),
    (ValueError, "ValueError"),
    (TypeError, "TypeError"),
    (AttributeError, "AttributeError"),
    (KeyError, "KeyError"),
    (RuntimeError, "RuntimeError"),
    (AssertionError, "AssertionError"),
)


class EvaluatorPayloadError(ValueError):
    """An invalid evaluator document; its message is a fixed reason code only."""

    CODES = frozenset(
        {
            "empty_output",
            "invalid_fence",
            "invalid_json",
            "duplicate_json_key",
            "nonfinite_json",
            "unexpected_schema",
            "assertion_mismatch",
        }
    )

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "unexpected_schema"
        super().__init__(self.code)


class EmptyModelOutputError(ValueError):
    """An empty response remains invalid; no text is invented or regenerated."""

    def __init__(self):
        super().__init__("empty_model_output")


def require_model_text(content: str | None) -> str:
    """Return nonblank model text exactly, or reject it without logging its value."""
    if not isinstance(content, str) or not content.strip():
        raise EmptyModelOutputError()
    return content


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvaluatorPayloadError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise EvaluatorPayloadError("nonfinite_json")


def normalize_evaluator_payload(content: str | None, *, expected_outcomes: Sequence[str] | None = None) -> str:
    """Validate strict official NL fields and unwrap only a complete single fence.

    Accepted wrappers are exactly `````json`` or ``````, with a newline after
    the opener and before the closing ``````, allowing CRLF and outer whitespace.
    Prose, multiple blocks, alternate fence languages, duplicate JSON keys, empty
    results and coercible-but-wrong field types are invalid. Optional expected
    outcomes enforce a one-to-one match, including duplicate assertion counts;
    result ordering and field values are preserved. No model calls or retries.
    """
    if not isinstance(content, str) or not content.strip():
        raise EvaluatorPayloadError("empty_output")
    document = content.strip()
    if document.startswith("```"):
        fence = _FENCE.fullmatch(document)
        if not fence:
            raise EvaluatorPayloadError("invalid_fence")
        document = fence.group("body")
        # A second block or nested Markdown wrapper is never extracted.
        if re.search(r"(?m)^\s*```", document):
            raise EvaluatorPayloadError("invalid_fence")
    try:
        payload = json.loads(document, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, RecursionError):
        raise EvaluatorPayloadError("invalid_json") from None
    if type(payload) is not dict or set(payload) != {"results"}:
        raise EvaluatorPayloadError("unexpected_schema")
    results = payload["results"]
    if type(results) is not list or not results:
        raise EvaluatorPayloadError("unexpected_schema")
    for result in results:
        if type(result) is not dict or set(result) != _ITEM_KEYS:
            raise EvaluatorPayloadError("unexpected_schema")
        if (
            type(result["expectedOutcome"]) is not str
            or not result["expectedOutcome"].strip()
            or type(result["metExpectation"]) is not bool
            or type(result["reasoning"]) is not str
        ):
            raise EvaluatorPayloadError("unexpected_schema")
    if expected_outcomes is not None:
        if (
            isinstance(expected_outcomes, (str, bytes))
            or any(type(value) is not str or not value.strip() for value in expected_outcomes)
            or Counter(expected_outcomes) != Counter(result["expectedOutcome"] for result in results)
        ):
            raise EvaluatorPayloadError("assertion_mismatch")
    return document


def _exception_type(exc: BaseException, control_types: Mapping[type[BaseException], str]) -> str:
    label = control_types.get(type(exc))
    if label in CONTROL_TYPES:
        return label
    if isinstance(exc, EvaluatorPayloadError):
        return "EvaluatorPayloadError"
    if isinstance(exc, EmptyModelOutputError):
        return "EmptyModelOutputError"
    for cls, name in _SAFE_TYPES:
        if isinstance(exc, cls):
            return name
    return "UnknownException"


def safe_exception_diagnostic(
    exc: BaseException,
    *,
    stage: str,
    trusted_root: str | Path,
    trusted_sources: Sequence[str] = DEFAULT_TRUSTED_SOURCES,
    control_exception_types: Mapping[type[BaseException], str] | None = None,
) -> dict:
    """Extract bounded traceback metadata, never messages, locals or source text.

    Only exact caller-allowlisted source files beneath trusted_root expose their
    relative location and function. Symlink escapes and external frames expose
    no filename/function/line. Causes expose safe type labels only, respecting
    suppressed context and limiting cycles/depth. This function neither catches
    worker cancellation nor changes a worker's validity/status classification.
    """
    root = Path(trusted_root).resolve()
    sources = {}
    for relative in trusted_sources:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            continue
        resolved = (root / path).resolve()
        if resolved.is_relative_to(root):
            sources[resolved] = path.as_posix()
    control_types = control_exception_types or {}
    frames = []
    current = exc.__traceback__
    while current is not None and len(frames) < 32:
        code = current.tb_frame.f_code
        filename = code.co_filename
        relative = sources.get(Path(filename).resolve()) if Path(filename).is_absolute() else None
        if relative is None:
            frames.append({"source": "external"})
        else:
            frames.append(
                {
                    "source": "trusted",
                    "path": relative,
                    "function": code.co_name if _FUNCTION.fullmatch(code.co_name) else "redacted",
                    "line": current.tb_lineno,
                }
            )
        current = current.tb_next
    causes, seen = [], {id(exc)}
    cause = exc
    for _ in range(8):
        explicit = cause.__cause__
        cause = explicit if explicit is not None else (None if cause.__suppress_context__ else cause.__context__)
        if cause is None or id(cause) in seen:
            break
        seen.add(id(cause))
        causes.append(_exception_type(cause, control_types))
    return {
        "schema_version": 1,
        "stage": stage if stage in STAGES else "unknown",
        "exception_type": _exception_type(exc, control_types),
        "frames": frames,
        "cause_types": causes,
    }
