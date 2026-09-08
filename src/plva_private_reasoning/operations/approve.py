"""Approval recommendations.

``guard`` is the deterministic gate every recommendation passes through, regardless of
whether a model produced it. It can only narrow scope; it never widens it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..contracts import (
    BLOCKED_CLASSES,
    ApprovalScope,
    ApproveRequest,
    ApproveResponse,
)
from . import BackendOutputError

# Mock/default recommendation limits: the tightest scope that still lets the task continue.
DEFAULT_TTL_SECONDS = 30
DEFAULT_MAX_USES = 1


@dataclass(frozen=True, slots=True)
class Recommendation:
    """What a reasoning backend proposes; the guard decides whether it stands."""

    approve: bool
    reason_code: str
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    max_uses: int = DEFAULT_MAX_USES


Backend = Callable[[ApproveRequest], Recommendation]


def deny(request: ApproveRequest, reason_code: str) -> ApproveResponse:
    return ApproveResponse(
        schema_version=request.schema_version,
        session_id=request.session_id,
        request_id=request.request_id,
        decision="deny",
        reason_code=reason_code,
        scope=None,
    )


def precheck(request: ApproveRequest) -> str | None:
    """Deterministic denials that need no reasoning at all. Returns a reason code or None."""
    if request.policy is None:
        return "POLICY_MISSING"
    if request.pii_class in BLOCKED_CLASSES:
        return "CLASS_BLOCKED"
    if request.destination is None or not request.destination.verified_by_runtime:
        return "DESTINATION_UNVERIFIED"
    if request.destination.origin not in request.policy.allowed_origins:
        return "ORIGIN_NOT_ALLOWED"
    if request.destination.field_id not in request.policy.allowed_fields:
        return "FIELD_NOT_ALLOWED"
    allowed_tools = request.policy.allowed_tools
    if allowed_tools is not None and request.tool_name not in allowed_tools:
        return "TOOL_NOT_ALLOWED"
    return None


def guard(request: ApproveRequest, recommendation: Recommendation) -> ApproveResponse:
    """Clamp a recommendation to the request and policy. Scope can only shrink."""
    blocked = precheck(request)
    if blocked is not None:
        return deny(request, blocked)
    if not recommendation.approve:
        return deny(request, recommendation.reason_code)
    assert request.policy is not None and request.destination is not None  # precheck passed
    if recommendation.ttl_seconds < 1 or recommendation.max_uses < 1:
        return deny(request, "MODEL_OUTPUT_INVALID")
    scope = ApprovalScope(
        token=request.token,
        tool_name=request.tool_name,
        argument_path=request.argument_path,
        origin=request.destination.origin,
        field_id=request.destination.field_id,
        ttl_seconds=min(recommendation.ttl_seconds, request.policy.max_ttl_seconds),
        max_uses=min(recommendation.max_uses, request.policy.max_uses),
    )
    return ApproveResponse(
        schema_version=request.schema_version,
        session_id=request.session_id,
        request_id=request.request_id,
        decision="approve",
        reason_code=recommendation.reason_code,
        scope=scope,
    )


def mock_backend(request: ApproveRequest) -> Recommendation:
    """Deterministic mock: policy match is the whole judgment. No model, no free text."""
    return Recommendation(approve=True, reason_code="POLICY_MATCH")


def run(request: ApproveRequest, backend: Backend) -> ApproveResponse:
    blocked = precheck(request)
    if blocked is not None:
        return deny(request, blocked)
    try:
        recommendation = backend(request)
    except BackendOutputError:
        return deny(request, "MODEL_OUTPUT_INVALID")
    except Exception:
        return deny(request, "MODEL_UNAVAILABLE")
    return guard(request, recommendation)
