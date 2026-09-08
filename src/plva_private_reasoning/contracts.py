"""Frozen v1 contract models.

Every request model forbids unknown fields and bounds every string. These models are the
runtime twin of ``contracts/v1/*.schema.json``; the contract tests keep them in sync.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION: Final = "1.0"

# Mirrors the reference core's placeholder shape: CLASS_<ordinal>_<4 hex>.
TOKEN_PATTERN: Final = r"^[A-Z][A-Z0-9_]*_[1-9][0-9]*_[0-9a-f]{4}$"
IDENTIFIER_PATTERN: Final = r"^[A-Za-z0-9._-]{1,64}$"
ARGUMENT_PATH_PATTERN: Final = r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*|\[[0-9]+\])*$"
CODE_PATTERN: Final = r"^[A-Z][A-Z0-9_]{0,39}$"
ORIGIN_PATTERN: Final = r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$"

PII_CLASSES: Final = (
    "NAME",
    "EMAIL",
    "PHONE",
    "ADDRESS",
    "DOB",
    "GOV_ID",
    "SSN",
    "BANK_ACCOUNT",
    "CARD_NUMBER",
    "CVC",
    "PASSWORD",
    "API_KEY",
    "AUTH_TOKEN",
    "PRIVATE_KEY",
    "SECRET",
)
# Never resolvable anywhere; approval requests for these are denied deterministically.
BLOCKED_CLASSES: Final = frozenset(
    {"GOV_ID", "SSN", "BANK_ACCOUNT", "CARD_NUMBER", "CVC", "PASSWORD", "PRIVATE_KEY", "SECRET"}
)
TOOL_NAMES: Final = ("type", "write", "paste", "fill")
EVENT_KINDS: Final = (
    "action",
    "observation",
    "resolution_ok",
    "resolution_denied",
    "approval_requested",
    "approval_denied",
    "blocked_class_attempt",
    "destination_mismatch",
    "token_invalid",
    "scrub_hit",
    "error",
)

MAX_ITEMS: Final = 40
MIN_ITEMS: Final = 2
MAX_VALUE_CHARS: Final = 500
MAX_INSTRUCTION_CHARS: Final = 500
MAX_CONTEXT_CHARS: Final = 1000
MAX_RULES: Final = 20
MAX_RULE_CHARS: Final = 300
MAX_ALLOWLIST: Final = 20
MAX_TRACE_EVENTS: Final = 200
MAX_TTL_SECONDS: Final = 300
MAX_USES: Final = 10
MAX_REQUEST_BODY_BYTES: Final = 65536

PiiClass = Literal[
    "NAME",
    "EMAIL",
    "PHONE",
    "ADDRESS",
    "DOB",
    "GOV_ID",
    "SSN",
    "BANK_ACCOUNT",
    "CARD_NUMBER",
    "CVC",
    "PASSWORD",
    "API_KEY",
    "AUTH_TOKEN",
    "PRIVATE_KEY",
    "SECRET",
]
ToolName = Literal["type", "write", "paste", "fill"]
EventKind = Literal[
    "action",
    "observation",
    "resolution_ok",
    "resolution_denied",
    "approval_requested",
    "approval_denied",
    "blocked_class_attempt",
    "destination_mismatch",
    "token_invalid",
    "scrub_hit",
    "error",
]
Mode = Literal["mock", "local"]
Isolation = Literal["unverified", "verified", "failed"]
Capability = Literal["approve", "compute", "review-trace"]

Token = Annotated[str, StringConstraints(pattern=TOKEN_PATTERN, max_length=64)]
Identifier = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]
ArgumentPath = Annotated[str, StringConstraints(pattern=ARGUMENT_PATH_PATTERN, max_length=64)]
Code = Annotated[str, StringConstraints(pattern=CODE_PATTERN)]
Origin = Annotated[str, StringConstraints(pattern=ORIGIN_PATTERN, max_length=253)]
FieldId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,128}$")]
ContextText = Annotated[str, StringConstraints(max_length=MAX_CONTEXT_CHARS)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)


class Envelope(_Strict):
    schema_version: Literal["1.0"]
    session_id: Identifier
    request_id: Identifier


# --- readiness -------------------------------------------------------------


class ReadinessResponse(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    mode: Mode
    ready_for_private_values: bool
    model_loaded: bool
    isolation: Isolation
    capabilities: list[Capability]
    instance_id: Identifier
    service_version: Annotated[str, StringConstraints(max_length=32)]
    verified_at: Annotated[str, StringConstraints(max_length=40)] | None = None


# --- approve ---------------------------------------------------------------


class Destination(_Strict):
    origin: Origin
    field_id: FieldId
    verified_by_runtime: bool


class ApprovalPolicy(_Strict):
    policy_id: Identifier
    rules: Annotated[
        list[Annotated[str, StringConstraints(max_length=MAX_RULE_CHARS)]],
        Field(max_length=MAX_RULES),
    ] = []
    allowed_origins: Annotated[list[Origin], Field(max_length=MAX_ALLOWLIST)]
    allowed_fields: Annotated[list[FieldId], Field(max_length=MAX_ALLOWLIST)]
    allowed_tools: Annotated[list[ToolName], Field(max_length=len(TOOL_NAMES))] | None = None
    max_ttl_seconds: Annotated[int, Field(ge=1, le=MAX_TTL_SECONDS)]
    max_uses: Annotated[int, Field(ge=1, le=MAX_USES)]


class ApproveRequest(Envelope):
    token: Token
    pii_class: PiiClass
    tool_name: ToolName
    argument_path: ArgumentPath
    destination: Destination | None = None
    task_context: ContextText = ""
    policy: ApprovalPolicy | None = None


class ApprovalScope(_Strict):
    token: Token
    tool_name: ToolName
    argument_path: ArgumentPath
    origin: Origin
    field_id: FieldId
    ttl_seconds: Annotated[int, Field(ge=1, le=MAX_TTL_SECONDS)]
    max_uses: Annotated[int, Field(ge=1, le=MAX_USES)]


class ApproveResponse(Envelope):
    decision: Literal["approve", "deny"]
    reason_code: Code
    scope: ApprovalScope | None

    @model_validator(mode="after")
    def _scope_matches_decision(self) -> ApproveResponse:
        if (self.decision == "approve") != (self.scope is not None):
            raise ValueError("approve requires scope; deny requires scope: null")
        return self


# --- compute ---------------------------------------------------------------


class ComputeItem(_Strict):
    token: Token
    value: Annotated[str, StringConstraints(min_length=1, max_length=MAX_VALUE_CHARS)]


class ComputeRequest(Envelope):
    operation: Literal["sort", "select"]
    instruction: Annotated[str, StringConstraints(min_length=1, max_length=MAX_INSTRUCTION_CHARS)]
    items: Annotated[list[ComputeItem], Field(min_length=MIN_ITEMS, max_length=MAX_ITEMS)]
    select_count: Annotated[int, Field(ge=0, le=MAX_ITEMS)] | None = None

    @model_validator(mode="after")
    def _shape(self) -> ComputeRequest:
        tokens = [item.token for item in self.items]
        if len(set(tokens)) != len(tokens):
            raise ValueError("duplicate token")
        if self.select_count is not None:
            if self.operation != "select":
                raise ValueError("select_count only valid for select")
            if self.select_count > len(self.items):
                raise ValueError("select_count exceeds item count")
        return self


class ComputeResponse(Envelope):
    status: Literal["ok", "denied", "error"]
    tokens: Annotated[list[Token], Field(max_length=MAX_ITEMS)]
    reason_code: Code

    @model_validator(mode="after")
    def _tokens_match_status(self) -> ComputeResponse:
        if self.status != "ok" and self.tokens:
            raise ValueError("non-ok status must carry no tokens")
        return self


# --- review-trace ----------------------------------------------------------


class TraceEvent(_Strict):
    step: Annotated[int, Field(ge=1, le=100000)]
    kind: EventKind
    token: Token | None = None
    pii_class: PiiClass | None = None
    tool_name: ToolName | None = None
    error_code: Code | None = None


class TracePolicy(_Strict):
    denied_resolution_threshold: Annotated[int, Field(ge=1, le=100)] = 3
    window_steps: Annotated[int, Field(ge=1, le=1000)] = 8
    halt_on_blocked_class_attempt: bool = True


class ReviewTraceRequest(Envelope):
    events: Annotated[list[TraceEvent], Field(min_length=1, max_length=MAX_TRACE_EVENTS)]
    task_context: ContextText = ""
    policy: TracePolicy = TracePolicy()

    @model_validator(mode="after")
    def _steps_monotonic(self) -> ReviewTraceRequest:
        steps = [event.step for event in self.events]
        if any(later < earlier for earlier, later in pairwise(steps)):
            raise ValueError("steps must be non-decreasing")
        return self


class ReviewTraceResponse(Envelope):
    action: Literal["continue", "warn", "halt"]
    reason_code: Code


# --- errors ----------------------------------------------------------------


class ErrorBody(_Strict):
    """Fixed error body. Never carries any part of the rejected input."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    error_code: Code
