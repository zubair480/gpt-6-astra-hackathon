"""Trace review: policy floors halt regardless of backend; malformed backend output halts."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from plva_private_reasoning.contracts import ReviewTraceRequest
from plva_private_reasoning.operations import review_trace


def request(events: list[dict[str, Any]], **policy: Any) -> ReviewTraceRequest:
    return ReviewTraceRequest.model_validate(
        {
            "schema_version": "1.0",
            "session_id": "s1",
            "request_id": "t1",
            "events": events,
            "task_context": "Update the display name.",
            "policy": policy,
        }
    )


def test_nominal_trace_continues() -> None:
    response = review_trace.run(
        request([{"step": 1, "kind": "action"}, {"step": 2, "kind": "observation"}]),
        review_trace.mock_backend,
    )
    assert response.action == "continue" and response.reason_code == "NOMINAL"


def test_single_denial_warns() -> None:
    response = review_trace.run(
        request([{"step": 1, "kind": "action"}, {"step": 2, "kind": "resolution_denied"}]),
        review_trace.mock_backend,
    )
    assert response.action == "warn" and response.reason_code == "SUSPICIOUS_ACTIVITY"


def test_blocked_class_attempt_halts_even_if_backend_says_continue() -> None:
    def optimist(_: ReviewTraceRequest) -> tuple[str, str]:
        return "continue", "NOMINAL"

    response = review_trace.run(
        request([{"step": 1, "kind": "blocked_class_attempt", "pii_class": "CARD_NUMBER"}]),
        optimist,
    )
    assert response.action == "halt" and response.reason_code == "BLOCKED_CLASS_ATTEMPT"


def test_blocked_class_flag_off_falls_to_backend() -> None:
    response = review_trace.run(
        request(
            [{"step": 1, "kind": "blocked_class_attempt"}], halt_on_blocked_class_attempt=False
        ),
        review_trace.mock_backend,
    )
    assert response.action == "continue"


@pytest.mark.parametrize(
    ("kind", "reason"),
    [("destination_mismatch", "DESTINATION_MISMATCH"), ("token_invalid", "TOKEN_INVALID")],
)
def test_hard_halt_kinds(kind: str, reason: str) -> None:
    response = review_trace.run(request([{"step": 3, "kind": kind}]), review_trace.mock_backend)
    assert response.action == "halt" and response.reason_code == reason


def test_repeated_denials_inside_window_halt() -> None:
    events = [{"step": s, "kind": "resolution_denied"} for s in (5, 6, 7)]
    response = review_trace.run(
        request(events, denied_resolution_threshold=3, window_steps=8), review_trace.mock_backend
    )
    assert response.action == "halt" and response.reason_code == "REPEATED_DENIALS"


def test_denials_outside_window_do_not_count() -> None:
    events = [
        {"step": 1, "kind": "resolution_denied"},
        {"step": 2, "kind": "resolution_denied"},
        {"step": 50, "kind": "resolution_denied"},
    ]
    response = review_trace.run(
        request(events, denied_resolution_threshold=3, window_steps=8), review_trace.mock_backend
    )
    assert response.action == "warn"


def test_backend_failure_halts() -> None:
    def boom(_: ReviewTraceRequest) -> tuple[str, str]:
        raise TimeoutError

    response = review_trace.run(request([{"step": 1, "kind": "action"}]), boom)
    assert response.action == "halt" and response.reason_code == "MODEL_UNAVAILABLE"


def test_backend_bad_action_halts() -> None:
    def weird(_: ReviewTraceRequest) -> tuple[str, str]:
        return "proceed", "NOMINAL"

    response = review_trace.run(request([{"step": 1, "kind": "action"}]), weird)
    assert response.action == "halt" and response.reason_code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"step": 2, "kind": "action"}, {"step": 1, "kind": "action"}],
        [{"step": 1, "kind": "screenshot"}],
        [{"step": 1, "kind": "action", "detail": "raw log line"}],
        [{"step": 1, "kind": "error", "error_code": "lowercase"}],
        [{"step": s, "kind": "action"} for s in range(1, 202)],
    ],
)
def test_invalid_traces_rejected(events: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        request(events)


def test_backend_output_error_halts_with_model_output_invalid() -> None:
    from plva_private_reasoning.operations import BackendOutputError

    def bad(_: ReviewTraceRequest) -> tuple[str, str]:
        raise BackendOutputError("fixed message")

    response = review_trace.run(request([{"step": 1, "kind": "action"}]), bad)
    assert response.action == "halt" and response.reason_code == "MODEL_OUTPUT_INVALID"
