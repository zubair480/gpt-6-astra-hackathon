"""Shared types for the demo. Every track builds against these; change only with the lead."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
Level = Literal["hide_use", "approval", "blocked"]

# Mirrors the reference privacy-policy.json. The demo UI may edit it per run.
DEFAULT_POLICY: dict[str, Level] = {
    "NAME": "hide_use",
    "EMAIL": "hide_use",
    "PHONE": "hide_use",
    "ADDRESS": "hide_use",
    "DOB": "hide_use",
    "GOV_ID": "blocked",
    "SSN": "blocked",
    "BANK_ACCOUNT": "blocked",
    "CARD_NUMBER": "blocked",
    "CVC": "blocked",
    "PASSWORD": "blocked",
    "API_KEY": "approval",
    "AUTH_TOKEN": "approval",
    "PRIVATE_KEY": "blocked",
    "SECRET": "blocked",
}


@dataclass(frozen=True, slots=True)
class Box:
    """CSS-pixel rectangle in viewport coordinates (same frame as the screenshot)."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class TextSpan:
    """One visible run of text on the page with where it is drawn."""

    text: str
    box: Box
    field_id: str | None = None  # id/name of the enclosing input, if the text is an input value
    input_type: str | None = None  # "password", "text", ... for inputs


@dataclass(frozen=True, slots=True)
class Field:
    """An interactive input on the page, for destination verification and typing."""

    field_id: str
    label: str
    box: Box
    input_type: str
    focused: bool


@dataclass(slots=True)
class Snapshot:
    """What the browser captured at one step. `png` is RAW pixels: local only, never upstream."""

    url: str
    origin: str
    title: str
    width: int
    height: int
    png: bytes
    spans: list[TextSpan]
    fields: list[Field]
    focused_field_id: str | None


@dataclass(frozen=True, slots=True)
class Finding:
    pii_class: PiiClass
    value: str
    boxes: tuple[Box, ...]
    field_id: str | None = None


@dataclass(frozen=True, slots=True)
class Mask:
    """A rectangle painted over the raw frame, with the placeholder chip drawn on top."""

    box: Box
    token: str | None  # None for blocked classes (opaque mask, no resolvable token)
    pii_class: PiiClass


@dataclass(slots=True)
class RedactedFrame:
    """The ONLY image that may leave the machine."""

    png: bytes
    masks: list[Mask]
    manifest: list[dict[str, str]]  # [{"token": ..., "class": ..., "level": ...}] no values
    sha256: str


ActionKind = Literal[
    "click", "type", "press", "scroll", "navigate", "private_compute", "done", "fail"
]


@dataclass(slots=True)
class Action:
    """What the cloud model asked for. `text` may contain placeholder tokens, never values."""

    kind: ActionKind
    x: float | None = None
    y: float | None = None
    text: str | None = None  # type / navigate url / done summary / fail reason
    key: str | None = None  # press
    dy: int | None = None  # scroll
    operation: Literal["sort", "select"] | None = None  # private_compute
    tokens: list[str] = field(default_factory=list)  # private_compute inputs
    select_count: int | None = None
    reasoning: str = ""  # model's short reasoning, shown in UI, never resolved


@dataclass(slots=True)
class StepEvent:
    """UI/trace record for one step. Values never appear here; tokens and classes only."""

    step: int
    # action | observation | resolution_ok | resolution_denied | approval_requested |
    # approval_denied | blocked_class_attempt | destination_mismatch | token_invalid |
    # scrub_hit | error | halt
    kind: str
    detail: str = ""
    token: str | None = None
    pii_class: PiiClass | None = None
    tool_name: str | None = None
    error_code: str | None = None
