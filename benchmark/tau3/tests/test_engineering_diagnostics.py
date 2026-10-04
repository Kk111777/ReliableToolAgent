"""Offline error/payload contracts, not additional retail benchmark tasks."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from engineering_diagnostics import (  # noqa: E402
    EmptyModelOutputError,
    EvaluatorPayloadError,
    normalize_evaluator_payload,
    require_model_text,
    safe_exception_diagnostic,
)
from evaluator_retry_wrapper import validate_official_nl_payload  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
PAYLOAD = {
    "results": [
        {
            "expectedOutcome": "finish the requested WRITE",
            "metExpectation": False,
            "reasoning": "未完成；preserve exactly\n``` text",
        }
    ]
}
DOCUMENT = json.dumps(PAYLOAD, ensure_ascii=False)


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "```\n{}\n```", " \r\n```json\r\n{}\r\n```\r\n "])
def test_exact_fence_preserves_every_field_and_original_parser_contract(wrapper):
    normalized = normalize_evaluator_payload(
        wrapper.format(DOCUMENT), expected_outcomes=["finish the requested WRITE"]
    )
    assert json.loads(normalized) == PAYLOAD
    assert normalized == DOCUMENT
    validate_official_nl_payload(normalized)


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        " \n\t",
        "Here is the answer:\n```json\n" + DOCUMENT + "\n```",
        "```json\n" + DOCUMENT + "\n```\nExplanation",
        "```json\n" + DOCUMENT + "\n```\n```json\n" + DOCUMENT + "\n```",
        "```JSON\n" + DOCUMENT + "\n```",
        "```json " + DOCUMENT + "```",
        "~~~json\n" + DOCUMENT + "\n~~~",
        "```json\n" + DOCUMENT,
        "```json\n{} BROKEN\n```",
        DOCUMENT + DOCUMENT,
        "[]",
        "{}",
        '{"results": []}',
        '{"results": null}',
        '{"results": [], "explanation": "extra"}',
        '{"results": [], "results": []}',
        '{"results": [{"expectedOutcome":"x", "metExpectation":true, "reasoning":"x", "reasoning":"y"}]}',
        '{"results": [{"expectedOutcome":"x", "metExpectation":NaN, "reasoning":"x"}]}',
    ],
)
def test_invalid_documents_stay_invalid_without_repair_or_result_invention(content):
    with pytest.raises(EvaluatorPayloadError):
        normalize_evaluator_payload(content)


@pytest.mark.parametrize(
    "item",
    [
        [],
        None,
        {"expectedOutcome": "x", "metExpectation": True},
        {"expectedOutcome": "x", "metExpectation": True, "reasoning": "x", "extra": 1},
        {"expectedOutcome": 1, "metExpectation": True, "reasoning": "x"},
        {"expectedOutcome": " ", "metExpectation": True, "reasoning": "x"},
        {"expectedOutcome": "x", "metExpectation": "false", "reasoning": "x"},
        {"expectedOutcome": "x", "metExpectation": 1, "reasoning": "x"},
        {"expectedOutcome": "x", "metExpectation": True, "reasoning": None},
    ],
)
def test_schema_types_are_strict_and_boolean_is_never_coerced(item):
    with pytest.raises(EvaluatorPayloadError, match="unexpected_schema"):
        normalize_evaluator_payload(json.dumps({"results": [item]}))


def test_assertion_membership_count_and_values_cannot_be_silently_changed():
    item = {"expectedOutcome": "x", "metExpectation": True, "reasoning": ""}
    document = json.dumps({"results": [item, item]})
    assert normalize_evaluator_payload(document, expected_outcomes=["x", "x"]) == document
    for expected in (["x"], ["x", "y"], [], "x"):
        with pytest.raises(EvaluatorPayloadError, match="assertion_mismatch"):
            normalize_evaluator_payload(document, expected_outcomes=expected)


@pytest.mark.parametrize("content", [None, "", " \n"])
def test_empty_model_response_has_no_valid_text(content):
    with pytest.raises(EmptyModelOutputError, match="empty_model_output"):
        require_model_text(content)


def test_nonblank_model_response_is_preserved_exactly():
    assert require_model_text(" \nno invented repair\n ") == " \nno invented repair\n "


def test_safe_metadata_excludes_runtime_values():
    secret = "sk-contract-secret-do-not-publish"
    headers = {"Authorization": "Bearer " + secret}
    provider_payload = {"content": secret}
    try:
        try:
            json.loads(secret)
        except json.JSONDecodeError as cause:
            raise ValueError(secret, headers, provider_payload) from cause
    except ValueError as exc:
        diagnostic = safe_exception_diagnostic(
            exc,
            stage="evaluation",
            trusted_root=ROOT,
            trusted_sources=[str(Path(__file__).relative_to(ROOT))],
        )
    encoded = json.dumps(diagnostic)
    assert secret not in encoded
    assert "Authorization" not in encoded and "provider_payload" not in encoded
    assert diagnostic["exception_type"] == "ValueError"
    assert diagnostic["cause_types"] == ["JSONDecodeError"]
    assert diagnostic["frames"][-1]["path"] == "benchmark/tau3/tests/test_engineering_diagnostics.py"
    assert diagnostic["frames"][-1]["line"] > 0
    assert set(diagnostic) == {"schema_version", "stage", "exception_type", "frames", "cause_types"}


def test_untrusted_file_function_exception_name_and_stage_are_redacted(tmp_path):
    secret = "private-token-in-path-and-name"
    namespace = {"secret": secret}
    code = compile(
        "class ProviderPrivateToken(BaseException): pass\ndef private_secret_function():\n raise ProviderPrivateToken(secret)\n",
        str(tmp_path / secret / "sdk.py"),
        "exec",
    )
    exec(code, namespace)
    try:
        namespace["private_secret_function"]()
    except BaseException as exc:
        diagnostic = safe_exception_diagnostic(exc, stage=secret, trusted_root=ROOT)
    encoded = json.dumps(diagnostic)
    for token in (secret, "private_secret_function", "ProviderPrivateToken", str(tmp_path), "sdk.py"):
        assert token not in encoded
    assert diagnostic["stage"] == "unknown"
    assert diagnostic["exception_type"] == "UnknownException"
    assert all(frame == {"source": "external"} for frame in diagnostic["frames"])


def test_trusted_source_symlink_escape_is_redacted(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    script = outside / "provider_private.py"
    script.write_text("raise ValueError('secret')")
    root = tmp_path / "root"
    root.mkdir()
    (root / "known.py").symlink_to(script)
    try:
        exec(compile(script.read_text(), str(root / "known.py"), "exec"), {})
    except ValueError as exc:
        diagnostic = safe_exception_diagnostic(
            exc, stage="simulation", trusted_root=root, trusted_sources=["known.py"]
        )
    assert all(frame == {"source": "external"} for frame in diagnostic["frames"])


def test_context_suppression_and_cycles_are_bounded():
    first, second = ValueError("secret-one"), TypeError("secret-two")
    first.__cause__, second.__cause__ = second, first
    diagnostic = safe_exception_diagnostic(first, stage="simulation", trusted_root=ROOT)
    assert diagnostic["cause_types"] == ["TypeError"]
    first.__cause__, first.__context__, first.__suppress_context__ = None, second, True
    assert safe_exception_diagnostic(first, stage="simulation", trusted_root=ROOT)["cause_types"] == []


def test_exception_formatting_and_truthiness_hooks_are_never_called():
    class UnsafeFormatting(BaseException):
        def __str__(self):
            pytest.fail("exception str must not be accessed")

        def __repr__(self):
            pytest.fail("exception repr must not be accessed")

        def __bool__(self):
            pytest.fail("exception truthiness must not be accessed")

    error = ValueError("private message")
    error.__cause__ = UnsafeFormatting()
    diagnostic = safe_exception_diagnostic(error, stage="evaluation", trusted_root=ROOT)
    assert diagnostic["cause_types"] == ["UnknownException"]


def test_cancel_and_budget_control_types_remain_invalid_without_catching_or_replay():
    class StudyDeadline(BaseException):
        pass

    cancelled = StudyDeadline("secret-cancel-message")
    diagnostic = safe_exception_diagnostic(
        cancelled, stage="simulation", trusted_root=ROOT, control_exception_types={StudyDeadline: "StudyDeadline"}
    )
    assert diagnostic["exception_type"] == "StudyDeadline"
    assert "secret-cancel-message" not in json.dumps(diagnostic)
    assert "valid" not in diagnostic
    with pytest.raises(StudyDeadline):
        raise cancelled
    assert (
        safe_exception_diagnostic(asyncio.CancelledError("secret"), stage="request", trusted_root=ROOT)[
            "exception_type"
        ]
        == "CancelledError"
    )


def test_parser_error_message_never_contains_raw_payload():
    secret = "sk-invalid-json-secret"
    with pytest.raises(EvaluatorPayloadError) as caught:
        normalize_evaluator_payload("```json\n" + secret + "\n```")
    assert str(caught.value) == "invalid_json"
    assert secret not in json.dumps(safe_exception_diagnostic(caught.value, stage="evaluation", trusted_root=ROOT))
