"""In-memory run state shared by the runner (writer) and the UI (reader). Thread-safe.

Raw screenshots and vault values stay in this process only. Anything exposed through
``public_view`` is value-free unless the local operator explicitly asks to reveal.
"""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .types import DEFAULT_POLICY, Level, StepEvent


@dataclass(slots=True)
class RunConfig:
    url: str = ""
    task: str = ""
    policy: dict[str, Level] = field(default_factory=lambda: dict(DEFAULT_POLICY))
    model: str = ""
    max_steps: int = 15
    plva_enabled: bool = True  # False = raw frames upstream (the "without PLVA" comparison)
    private_reasoning_url: str = "http://127.0.0.1:18555"
    private_reasoning_credential_file: str = ".plva-pr/credential"


@dataclass(slots=True)
class StepRecord:
    step: int
    reasoning: str = ""
    action: dict[str, Any] = field(default_factory=dict)
    events: list[StepEvent] = field(default_factory=list)
    redacted_png: bytes = b""  # what the cloud model received
    raw_png: bytes = b""  # local only
    manifest: list[dict[str, str]] = field(default_factory=list)
    frame_sha256: str = ""
    mask_count: int = 0
    outbound_bytes: int = 0
    redact_ms: float = 0.0
    model_ms: float = 0.0
    url: str = ""


@dataclass(slots=True)
class ApprovalRecord:
    step: int
    token: str
    pii_class: str
    decision: str
    reason_code: str
    scope: dict[str, Any] | None
    latency_ms: float


class RunState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.version = 0
        self.config = RunConfig()
        self.status = "idle"  # idle | running | done | halted | failed
        self.summary = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self.steps: list[StepRecord] = []
        self.approvals: list[ApprovalRecord] = []
        self.reviews: list[dict[str, Any]] = []  # {step, action, reason_code, latency_ms}
        self.computes: list[dict[str, Any]] = []  # {step, operation, status, reason_code, tokens}
        self.vault: dict[str, dict[str, Any]] = {}  # token -> {class, level, value, resolved}
        self.readiness: dict[str, Any] = {}
        self.outbound_requests = 0
        self.leaks_found = 0
        self.stop_requested = False

    # -- writer side ---------------------------------------------------------
    def _bump(self) -> None:
        self.version += 1

    def reset(self, config: RunConfig) -> None:
        with self._lock:
            self.__init__()  # type: ignore[misc]
            self.config = config
            self._bump()

    def set_status(self, status: str, summary: str = "") -> None:
        with self._lock:
            self.status = status
            if summary:
                self.summary = summary
            if status == "running" and not self.started_at:
                self.started_at = time.time()
            if status in ("done", "halted", "failed"):
                self.finished_at = time.time()
            self._bump()

    def add_step(self, record: StepRecord) -> None:
        with self._lock:
            self.steps.append(record)
            self._bump()

    def update_step(self, step: int, **fields: Any) -> None:
        with self._lock:
            for record in self.steps:
                if record.step == step:
                    for key, value in fields.items():
                        setattr(record, key, value)
            self._bump()

    def add_event(self, event: StepEvent) -> None:
        with self._lock:
            for record in self.steps:
                if record.step == event.step:
                    record.events.append(event)
                    break
            else:
                self.steps.append(StepRecord(step=event.step, events=[event]))
            self._bump()

    def vault_put(self, token: str, pii_class: str, level: str, value: str | None) -> None:
        with self._lock:
            self.vault[token] = {"class": pii_class, "level": level, "value": value, "resolved": 0}
            self._bump()

    def vault_resolved(self, token: str) -> None:
        with self._lock:
            if token in self.vault:
                self.vault[token]["resolved"] += 1
            self._bump()

    def add_approval(self, record: ApprovalRecord) -> None:
        with self._lock:
            self.approvals.append(record)
            self._bump()

    def add_review(self, item: dict[str, Any]) -> None:
        with self._lock:
            self.reviews.append(item)
            self._bump()

    def add_compute(self, item: dict[str, Any]) -> None:
        with self._lock:
            self.computes.append(item)
            self._bump()

    def set_readiness(self, readiness: dict[str, Any]) -> None:
        with self._lock:
            self.readiness = readiness
            self._bump()

    def note_outbound(self, leaked: bool) -> None:
        with self._lock:
            self.outbound_requests += 1
            if leaked:
                self.leaks_found += 1
            self._bump()

    def all_events(self) -> list[StepEvent]:
        with self._lock:
            return [event for record in self.steps for event in record.events]

    # -- reader side ---------------------------------------------------------
    def public_view(
        self, *, reveal_values: bool = False, include_images: bool = True
    ) -> dict[str, Any]:
        """JSON-safe snapshot. Values only when the local operator toggled reveal."""
        with self._lock:
            steps = []
            for record in self.steps:
                item = asdict(record)
                item["events"] = [asdict(event) for event in record.events]
                if include_images:
                    item["redacted_png"] = (
                        base64.b64encode(record.redacted_png).decode()
                        if record.redacted_png
                        else ""
                    )
                    item["raw_png"] = (
                        base64.b64encode(record.raw_png).decode() if record.raw_png else ""
                    )
                else:
                    item["redacted_png"] = item["raw_png"] = ""
                steps.append(item)
            vault = {
                token: {
                    "class": entry["class"],
                    "level": entry["level"],
                    "resolved": entry["resolved"],
                    "value": (entry["value"] if reveal_values else None),
                    "stored": entry["value"] is not None,
                }
                for token, entry in self.vault.items()
            }
            return {
                "version": self.version,
                "status": self.status,
                "summary": self.summary,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "config": asdict(self.config),
                "steps": steps,
                "approvals": [asdict(a) for a in self.approvals],
                "reviews": list(self.reviews),
                "computes": list(self.computes),
                "vault": vault,
                "readiness": dict(self.readiness),
                "outbound_requests": self.outbound_requests,
                "leaks_found": self.leaks_found,
            }
