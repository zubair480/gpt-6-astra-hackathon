"""Bounded sort/select over explicitly supplied private values.

Values are visible only inside this process. The result carries input tokens only, and
``validate_answer`` enforces membership, uniqueness, and counts before anything is returned.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

from ..contracts import ComputeRequest, ComputeResponse
from . import BackendOutputError

Backend = Callable[[ComputeRequest], Sequence[str]]

_DESCENDING_HINTS: Final = ("descending", "reverse", "z to a", "z-a", "largest first", "newest")


def _respond(
    request: ComputeRequest, status: str, tokens: list[str], reason: str
) -> ComputeResponse:
    return ComputeResponse(
        schema_version=request.schema_version,
        session_id=request.session_id,
        request_id=request.request_id,
        status=status,  # type: ignore[arg-type]
        tokens=tokens,
        reason_code=reason,
    )


def validate_answer(request: ComputeRequest, answer: Sequence[str]) -> str | None:
    """Return a reason code when the answer is unacceptable, else None."""
    allowed = {item.token for item in request.items}
    if any(token not in allowed for token in answer):
        return "MODEL_OUTPUT_INVALID"
    if len(set(answer)) != len(answer):
        return "MODEL_OUTPUT_INVALID"
    if request.operation == "sort" and len(answer) != len(request.items):
        return "COUNT_MISMATCH"
    if (
        request.operation == "select"
        and request.select_count is not None
        and len(answer) != request.select_count
    ):
        return "COUNT_MISMATCH"
    return None


def mock_backend(request: ComputeRequest) -> Sequence[str]:
    """Deterministic mock: case-insensitive value order, stable on input position.

    Instructions are untrusted data: only a few ordering hints are honored, nothing else in the
    text can change the output shape.
    """
    hint = request.instruction.lower()
    reverse = any(word in hint for word in _DESCENDING_HINTS)
    ordered = sorted(
        enumerate(request.items),
        key=lambda pair: (pair[1].value.casefold(), pair[0]),
        reverse=reverse,
    )
    tokens = [item.token for _, item in ordered]
    if request.operation == "sort":
        return tokens
    count = request.select_count if request.select_count is not None else 0
    return tokens[:count]


def run(request: ComputeRequest, backend: Backend) -> ComputeResponse:
    try:
        answer = list(backend(request))
    except BackendOutputError:
        return _respond(request, "error", [], "MODEL_OUTPUT_INVALID")
    except Exception:
        return _respond(request, "error", [], "MODEL_UNAVAILABLE")
    problem = validate_answer(request, answer)
    if problem is not None:
        return _respond(request, "error", [], problem)
    return _respond(request, "ok", answer, "COMPLETED")
