"""Continue / warn / halt recommendations over value-free traces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from ..contracts import ReviewTraceRequest, ReviewTraceResponse
from . import BackendOutputError

Backend = Callable[[ReviewTraceRequest], tuple[str, str]]

_HALT_KINDS: Final = {
    "destination_mismatch": "DESTINATION_MISMATCH",
    "token_invalid": "TOKEN_INVALID",
}
_WARN_KINDS: Final = frozenset({"resolution_denied", "approval_denied", "error", "scrub_hit"})
_DENIAL_KINDS: Final = frozenset({"resolution_denied", "approval_denied"})
_ACTIONS: Final = frozenset({"continue", "warn", "halt"})


def _respond(request: ReviewTraceRequest, action: str, reason: str) -> ReviewTraceResponse:
    return ReviewTraceResponse(
        schema_version=request.schema_version,
        session_id=request.session_id,
        request_id=request.request_id,
        action=action,  # type: ignore[arg-type]
        reason_code=reason,
    )


def deterministic_floor(request: ReviewTraceRequest) -> tuple[str, str] | None:
    """Policy-driven halts that no backend may soften. Returns (action, reason) or None."""
    policy = request.policy
    for event in request.events:
        if event.kind == "blocked_class_attempt" and policy.halt_on_blocked_class_attempt:
            return "halt", "BLOCKED_CLASS_ATTEMPT"
        if event.kind in _HALT_KINDS:
            return "halt", _HALT_KINDS[event.kind]
    last_step = max(event.step for event in request.events)
    window_start = last_step - policy.window_steps + 1
    denials = sum(1 for e in request.events if e.step >= window_start and e.kind in _DENIAL_KINDS)
    if denials >= policy.denied_resolution_threshold:
        return "halt", "REPEATED_DENIALS"
    return None


def mock_backend(request: ReviewTraceRequest) -> tuple[str, str]:
    if any(event.kind in _WARN_KINDS for event in request.events):
        return "warn", "SUSPICIOUS_ACTIVITY"
    return "continue", "NOMINAL"


def run(request: ReviewTraceRequest, backend: Backend) -> ReviewTraceResponse:
    floor = deterministic_floor(request)
    if floor is not None:
        return _respond(request, *floor)
    try:
        action, reason = backend(request)
    except BackendOutputError:
        return _respond(request, "halt", "MODEL_OUTPUT_INVALID")
    except Exception:
        return _respond(request, "halt", "MODEL_UNAVAILABLE")
    if action not in _ACTIONS:
        return _respond(request, "halt", "MODEL_OUTPUT_INVALID")
    return _respond(request, action, reason)
