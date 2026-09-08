"""The demo agent loop.

Per step: snapshot → redact locally → send ONLY the redacted frame plus a value-free manifest to
the cloud model → parse a structured action → resolve placeholder tokens locally, asking the
private reasoning service when policy requires → execute → review the trace. The cloud model
never receives a vault value; the leak counter in the UI checks every outbound body.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, ClassVar

from plva_private_reasoning.contracts import EVENT_KINDS, TOKEN_PATTERN

from .state import ApprovalRecord, RunConfig, RunState, StepRecord
from .types import Action, Snapshot, StepEvent

ROOT = Path(__file__).resolve().parents[2]
TOKEN_RE = re.compile(r"«?\s*(?P<token>[A-Z][A-Z0-9_]*_[1-9][0-9]*_[0-9a-f]{4})\s*»?")
_TOKEN_SHAPE = re.compile(TOKEN_PATTERN)
CONTRACT_EVENT_KINDS = frozenset(EVENT_KINDS)
CREDENTIAL_FIELD_HINTS = ("key", "token", "secret", "credential", "password")

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "One or two short sentences. Never guess hidden values.",
        },
        "kind": {
            "type": "string",
            "enum": [
                "click",
                "type",
                "press",
                "scroll",
                "navigate",
                "private_compute",
                "done",
                "fail",
            ],
        },
        "x": {"type": ["number", "null"]},
        "y": {"type": ["number", "null"]},
        "text": {
            "type": ["string", "null"],
            "description": "type: text to type (placeholder tokens allowed verbatim); navigate: url; done/fail: summary",
        },
        "key": {"type": ["string", "null"]},
        "dy": {"type": ["integer", "null"]},
        "operation": {"type": ["string", "null"], "enum": ["sort", "select", None]},
        "tokens": {"type": "array", "items": {"type": "string"}},
        "select_count": {"type": ["integer", "null"]},
    },
    "required": [
        "reasoning",
        "kind",
        "x",
        "y",
        "text",
        "key",
        "dy",
        "operation",
        "tokens",
        "select_count",
    ],
}

SYSTEM_PROMPT = """You are a careful browser agent. You see a screenshot of a web page and decide ONE next action.
Coordinates are pixels in the screenshot (origin top-left). The page is 1280x900.

PRIVACY RULES (strict):
- Sensitive values on the page are hidden behind placeholder tokens like EMAIL_1_a3f9 or API_KEY_1_a3f9. The token manifest lists every token, its class, and its policy level. You will NEVER see the real values. Do not guess them.
- To enter a hidden value somewhere, first click the target field, then use kind="type" with the token written verbatim, for example text="«API_KEY_1_a3f9»". The local system substitutes the real value only if policy allows.
- Level hide_use: you may type the token freely. Level approval: typing it triggers a local approval check; it may be denied. Level blocked: it can never be used; do not try.
- To sort or pick among hidden values (for example sort team members by name), use kind="private_compute" with operation "sort" or "select", the relevant tokens, and put the criterion in text. The result comes back as tokens in order.
- Never ask the user for a hidden value. Never put a hidden value into a message, email, or search box unless the task explicitly requires that field and policy allows.

ACTIONS: click(x,y) · type(text) into the focused field · press(key e.g. Enter, Tab) · scroll(dy) · navigate(text=url) · private_compute(operation, tokens, text, select_count) · done(text=summary using tokens, never values) · fail(text=reason).
Take the shortest path. When the task is complete, return kind="done" with a one-line summary."""


class RunnerError(Exception):
    pass


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("OPENAI_")})
    return env


def pick_model(client: Any, preferred: str) -> str:
    if preferred:
        return preferred
    try:
        ids = sorted(m.id for m in client.models.list())
    except Exception:
        return "gpt-5"
    for family in ("gpt-6", "gpt-5"):
        matches = [
            i
            for i in ids
            if i.startswith(family) and "mini" not in i and "nano" not in i and "codex" not in i
        ]
        if matches:
            return matches[0]
    return "gpt-5"


def _center(box: Any) -> tuple[int, int]:
    return int(box.x + box.w / 2), int(box.y + box.h / 2)


def start_run(state: RunState, config: RunConfig) -> None:
    thread = threading.Thread(target=_run, args=(state, config), name="plva-demo-run", daemon=True)
    thread.start()


def stop_run(state: RunState) -> None:
    state.stop_requested = True


def _run(state: RunState, config: RunConfig) -> None:
    try:
        Runner(state, config).run()
    except Exception as exc:
        state.set_status("failed", f"{type(exc).__name__}: {str(exc)[:200]}")
        traceback.print_exc()


class Runner:
    def __init__(self, state: RunState, config: RunConfig) -> None:
        self.state = state
        self.config = config
        self.step = 0
        self.history: list[str] = []  # scrubbed one-line records of past actions/observations

    # -- setup ---------------------------------------------------------------
    def run(self) -> None:
        from openai import OpenAI

        from plva_private_reasoning.client import PrivateReasoningClient, load_credential

        from .browser import Browser
        from .vault import Vault

        env = load_env()
        api_key = env.get("OPENAI_API_KEY")
        if not api_key:
            self.state.set_status(
                "failed", "OPENAI_API_KEY missing: add it to .env at the repo root"
            )
            return
        self.openai = OpenAI(
            api_key=api_key, base_url=env.get("OPENAI_BASE_URL") or None, timeout=120
        )
        self.model = pick_model(self.openai, self.config.model or env.get("OPENAI_MODEL", ""))
        self.config.model = self.model

        cred_path = ROOT / self.config.private_reasoning_credential_file
        try:
            credential = load_credential(cred_path)
        except OSError:
            credential = ""
        self.pr = PrivateReasoningClient(
            self.config.private_reasoning_url,
            credential,
            timeout_seconds=90,
            enabled=bool(credential),
        )
        readiness = self.pr.readiness() if credential else None
        self.state.set_readiness(readiness.model_dump() if readiness else {"mode": "unavailable"})
        self.pr_mode = readiness.mode if readiness else "unavailable"
        if self.pr_mode == "mock":
            # Demo data is synthetic; allow the mock to answer compute so the flow is visible.
            self.pr = PrivateReasoningClient(
                self.config.private_reasoning_url,
                credential,
                timeout_seconds=90,
                allow_mock_for_private_values=True,
            )

        self.vault = Vault(self.config.policy)
        self.session_id = f"demo-{int(time.time())}"
        self.state.set_status("running")
        with Browser() as browser:
            self.browser = browser
            browser.navigate(self.config.url)
            browser.wait_settled()
            while self.step < self.config.max_steps:
                if self.state.stop_requested:
                    self.state.set_status("halted", "stopped by operator")
                    return
                self.step += 1
                if self._do_step():
                    return
            self.state.set_status("failed", f"max steps ({self.config.max_steps}) reached")
        self.vault.clear()

    # -- one step ------------------------------------------------------------
    def _do_step(self) -> bool:
        """Returns True when the run is finished (done/halted/failed)."""
        from .redact import redact, scrub_text

        record = StepRecord(step=self.step)
        self.state.add_step(record)
        snapshot = self._snapshot_with_retry()
        self.state.update_step(self.step, url=snapshot.url, raw_png=snapshot.png)

        t0 = time.perf_counter()
        if self.config.plva_enabled:
            frame, _findings = redact(snapshot, self.vault, self.config.policy)
            for token, pii_class, level in self.vault.entries():
                if token not in self.state.vault:
                    self.state.vault_put(token, pii_class, level, self.vault.resolve(token))
            outbound_png, manifest, sha, masks = (
                frame.png,
                frame.manifest,
                frame.sha256,
                len(frame.masks),
            )
        else:
            outbound_png, manifest, sha, masks = (
                snapshot.png,
                [],
                hashlib.sha256(snapshot.png).hexdigest(),
                0,
            )
        redact_ms = (time.perf_counter() - t0) * 1000
        self.state.update_step(
            self.step,
            redacted_png=outbound_png,
            manifest=manifest,
            frame_sha256=sha,
            mask_count=masks,
            redact_ms=round(redact_ms, 1),
        )

        task_text, hits = (
            scrub_text(self.config.task, self.vault)
            if self.config.plva_enabled
            else (self.config.task, 0)
        )
        if hits:
            self._event("scrub_hit", f"{hits} value(s) in task text replaced by tokens")

        fields = [
            {
                "field_id": f.field_id,
                "label": f.label[:60],
                "type": f.input_type,
                "center": list(_center(f.box)),
                "focused": f.focused,
            }
            for f in snapshot.fields
        ]
        user_text = json.dumps(
            {
                "task": task_text,
                "step": self.step,
                "page": {"url": snapshot.url, "title": snapshot.title},
                "token_manifest": manifest,
                "fields": fields,
                "history": self.history[-12:],
            },
            ensure_ascii=False,
        )
        leaked = self.config.plva_enabled and self.vault.contains_value(user_text)
        self.state.note_outbound(leaked)
        if leaked:
            self._event(
                "error",
                "leak check tripped: outbound text contained a vault value",
                error_code="LEAK",
            )
            self.state.set_status("halted", "leak check tripped before upstream call")
            return True

        t1 = time.perf_counter()
        action = self._ask_model(user_text, outbound_png)
        model_ms = (time.perf_counter() - t1) * 1000
        self.state.update_step(
            self.step,
            reasoning=action.reasoning[:400],
            model_ms=round(model_ms, 1),
            action={
                k: v
                for k, v in asdict(action).items()
                if k != "reasoning" and v not in (None, [], "")
            },
            outbound_bytes=len(user_text) + len(outbound_png),
        )
        finished = self._execute(action, snapshot)
        if finished:
            return True
        return self._maybe_review()

    def _snapshot_with_retry(self, attempts: int = 4) -> Snapshot:
        """Pages navigate under us; a snapshot taken mid-navigation raises. Settle and retry."""
        last: Exception | None = None
        for _ in range(attempts):
            try:
                self.browser.wait_settled()
                return self.browser.snapshot()
            except Exception as exc:  # playwright raises plain Error subclasses
                last = exc
                time.sleep(0.6)
        raise RunnerError("could not capture a stable snapshot") from last

    # -- cloud model ---------------------------------------------------------
    def _ask_model(self, user_text: str, png: bytes) -> Action:
        image_url = "data:image/png;base64," + base64.b64encode(png).decode()
        response = self.openai.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {"type": "input_image", "image_url": image_url, "detail": "high"},
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "action",
                    "schema": ACTION_SCHEMA,
                    "strict": True,
                }
            },
            store=False,
        )
        raw = response.output_text
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise RunnerError("model returned non-JSON") from exc
        return Action(
            kind=data.get("kind", "fail"),
            x=data.get("x"),
            y=data.get("y"),
            text=data.get("text"),
            key=data.get("key"),
            dy=data.get("dy"),
            operation=data.get("operation"),
            tokens=[t for t in data.get("tokens", []) if isinstance(t, str)],
            select_count=data.get("select_count"),
            reasoning=data.get("reasoning", ""),
        )

    # -- execution -----------------------------------------------------------
    def _event(self, kind: str, detail: str = "", **kw: Any) -> None:
        self.state.add_event(StepEvent(step=self.step, kind=kind, detail=detail, **kw))

    def _execute(self, action: Action, snapshot: Snapshot) -> bool:
        kind = action.kind
        if kind == "done":
            summary = self._scrub(action.text or "task complete")
            self.history.append(f"done: {summary}")
            self.state.set_status("done", summary)
            return True
        if kind == "fail":
            self.state.set_status("failed", self._scrub(action.text or "model gave up"))
            return True
        if kind == "click" and action.x is not None and action.y is not None:
            self.browser.click(action.x, action.y)
            self.browser.wait_settled()
            self._event("action", f"click ({int(action.x)},{int(action.y)})", tool_name="click")
            self.history.append(f"step {self.step}: click ({int(action.x)},{int(action.y)})")
            return False
        if kind == "press" and action.key:
            self.browser.press(action.key[:20])
            self._event("action", f"press {action.key[:20]}")
            self.history.append(f"step {self.step}: press {action.key[:20]}")
            return False
        if kind == "scroll":
            self.browser.scroll(int(action.dy or 400))
            self._event("action", f"scroll {int(action.dy or 400)}")
            self.history.append(f"step {self.step}: scroll")
            return False
        if kind == "navigate" and action.text:
            url = action.text.strip()
            if url.startswith(("http://", "https://")):
                self.browser.navigate(url)
                self.browser.wait_settled()
                self._event("action", "navigate")
                self.history.append(f"step {self.step}: navigate {url[:80]}")
            else:
                self._event(
                    "error", "navigate refused: unsupported scheme", error_code="NAV_REFUSED"
                )
            return False
        if kind == "type":
            return self._type(action.text or "", snapshot)
        if kind == "private_compute":
            self._compute(action)
            return False
        self._event("error", f"unsupported action {kind}", error_code="ACTION_INVALID")
        return False

    def _scrub(self, text: str) -> str:
        from .redact import scrub_text

        return scrub_text(text, self.vault)[0] if self.config.plva_enabled else text

    def _type(self, text: str, snapshot: Snapshot) -> bool:
        """Resolve tokens in the text locally; refuse the whole action if any token is not allowed."""
        resolved = text
        for match in list(TOKEN_RE.finditer(text)):
            token = match.group("token")
            level = self.vault.level_of(token)
            pii_class = self.vault.class_of(token)
            if level is None or pii_class is None:
                self._event(
                    "token_invalid",
                    "unknown or forged token in type action",
                    token=token,
                    tool_name="type",
                )
                self.history.append(f"step {self.step}: type refused (unknown token {token})")
                return False
            if level == "blocked":
                self._event(
                    "blocked_class_attempt",
                    "blocked class requested in type",
                    token=token,
                    pii_class=pii_class,
                    tool_name="type",
                )
                self.history.append(f"step {self.step}: type refused ({token} is blocked)")
                return False
            if level == "approval" and not self._approve(token, pii_class, snapshot):
                self.history.append(f"step {self.step}: type refused ({token} not approved)")
                return False
            value = self.vault.resolve(token)
            if value is None:
                self._event(
                    "resolution_denied",
                    "vault refused resolution",
                    token=token,
                    pii_class=pii_class,
                    tool_name="type",
                )
                return False
            resolved = resolved.replace(match.group(0), value)
            self.state.vault_resolved(token)
            self._event(
                "resolution_ok",
                "token resolved for local typing",
                token=token,
                pii_class=pii_class,
                tool_name="type",
            )
        self.browser.type_text(resolved)
        self.browser.wait_settled()
        shown = self._scrub(text)
        self._event("action", f"type {shown[:60]}", tool_name="type")
        self.history.append(f"step {self.step}: typed {shown[:60]}")
        return False

    def _approve(self, token: str, pii_class: str, snapshot: Snapshot) -> bool:
        field = next((f for f in snapshot.fields if f.focused), None)
        allowed_fields = [
            f.field_id
            for f in snapshot.fields
            if any(h in (f.field_id + " " + f.label).lower() for h in CREDENTIAL_FIELD_HINTS)
            and f.input_type != "password"
        ][:20]
        request = {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "request_id": f"approve-{self.step}-{token[-4:]}-{len(self.state.approvals)}",
            "token": token,
            "pii_class": pii_class,
            "tool_name": "type",
            "argument_path": "text",
            "destination": (
                {"origin": snapshot.origin, "field_id": field.field_id, "verified_by_runtime": True}
                if field and snapshot.origin.startswith("http")
                else None
            ),
            "task_context": self._scrub(self.config.task)[:900],
            "policy": {
                "policy_id": "demo-credential-policy",
                "rules": [
                    f"The user's {pii_class} may be entered into a credential field on this site "
                    f"(allowed fields: {', '.join(allowed_fields) or 'none'}) when the task is to "
                    "connect, configure, or authenticate an integration on that site.",
                    "Never into chat messages, emails, documents, search boxes, or a different site.",
                ],
                "allowed_origins": [snapshot.origin] if snapshot.origin.startswith("http") else [],
                "allowed_fields": allowed_fields,
                "allowed_tools": ["type", "fill"],
                "max_ttl_seconds": 60,
                "max_uses": 1,
            },
        }
        self._event(
            "approval_requested",
            "asked private reasoning service",
            token=token,
            pii_class=pii_class,
            tool_name="type",
        )
        t0 = time.perf_counter()
        response = self.pr.approve(request)
        latency = (time.perf_counter() - t0) * 1000
        scope = response.scope.model_dump() if response.scope else None
        self.state.add_approval(
            ApprovalRecord(
                self.step,
                token,
                pii_class,
                response.decision,
                response.reason_code,
                scope,
                round(latency, 1),
            )
        )
        if response.decision != "approve":
            self._event(
                "approval_denied",
                response.reason_code,
                token=token,
                pii_class=pii_class,
                tool_name="type",
            )
            return False
        return True

    def _compute(self, action: Action) -> None:
        tokens = [t for t in action.tokens if _TOKEN_SHAPE.match(t)]
        items = []
        for token in tokens:
            level = self.vault.level_of(token)
            value = self.vault.resolve(token)
            if level != "hide_use" or value is None:
                self._event(
                    "resolution_denied",
                    "compute over a token that is not hide_use",
                    token=token,
                    pii_class=self.vault.class_of(token),
                )
                self.history.append(f"step {self.step}: private_compute refused ({token})")
                return
            items.append({"token": token, "value": value})
        if not 2 <= len(items) <= 40 or action.operation not in ("sort", "select"):
            self._event(
                "error",
                "private_compute needs 2..40 hide_use tokens and a valid operation",
                error_code="COMPUTE_INVALID",
            )
            self.history.append(f"step {self.step}: private_compute refused (shape)")
            return
        request = {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "request_id": f"compute-{self.step}-{len(self.state.computes)}",
            "operation": action.operation,
            "instruction": (action.text or "as requested")[:500],
            "items": items,
            "select_count": action.select_count if action.operation == "select" else None,
        }
        t0 = time.perf_counter()
        response = self.pr.compute(request)
        latency = (time.perf_counter() - t0) * 1000
        self.state.add_compute(
            {
                "step": self.step,
                "operation": action.operation,
                "status": response.status,
                "reason_code": response.reason_code,
                "tokens": list(response.tokens),
                "latency_ms": round(latency, 1),
                "mode": self.pr_mode,
            }
        )
        for token in response.tokens:
            self.state.vault_resolved(token)
        if response.status == "ok":
            self._event(
                "observation",
                f"private_compute {action.operation}: {len(response.tokens)} tokens",
                tool_name="private_compute",
            )
            self.history.append(
                f"step {self.step}: private_compute {action.operation} result tokens in order: {response.tokens}"
            )
        else:
            self._event(
                "error", f"private_compute {response.reason_code}", error_code=response.reason_code
            )
            self.history.append(
                f"step {self.step}: private_compute failed ({response.reason_code})"
            )

    # -- trace review --------------------------------------------------------
    SUSPICIOUS: ClassVar[frozenset[str]] = frozenset(
        {
            "resolution_denied",
            "approval_denied",
            "blocked_class_attempt",
            "destination_mismatch",
            "token_invalid",
            "error",
        }
    )

    def _maybe_review(self) -> bool:
        events = self.state.all_events()
        recent = [e for e in events if e.step == self.step]
        if not any(e.kind in self.SUSPICIOUS for e in recent) and self.step % 4:
            return False
        contract_events = []
        for e in events[-200:]:
            kind = e.kind if e.kind in CONTRACT_EVENT_KINDS else "observation"
            contract_events.append(
                {
                    "step": e.step,
                    "kind": kind,
                    **({"token": e.token} if e.token and _TOKEN_SHAPE.match(e.token) else {}),
                    **({"pii_class": e.pii_class} if e.pii_class else {}),
                    **(
                        {"tool_name": e.tool_name}
                        if e.tool_name in ("type", "write", "paste", "fill")
                        else {}
                    ),
                    **({"error_code": e.error_code} if e.error_code else {}),
                }
            )
        request = {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "request_id": f"trace-{self.step}-{len(self.state.reviews)}",
            "events": contract_events,
            "task_context": self._scrub(self.config.task)[:900],
            "policy": {
                "denied_resolution_threshold": 3,
                "window_steps": 8,
                "halt_on_blocked_class_attempt": True,
            },
        }
        t0 = time.perf_counter()
        response = self.pr.review_trace(request)
        latency = (time.perf_counter() - t0) * 1000
        self.state.add_review(
            {
                "step": self.step,
                "action": response.action,
                "reason_code": response.reason_code,
                "latency_ms": round(latency, 1),
            }
        )
        if response.action == "halt":
            self._event("halt", response.reason_code)
            self.state.set_status(
                "halted", f"private reasoning service recommended halt: {response.reason_code}"
            )
            return True
        if response.action == "warn":
            self.history.append(f"step {self.step}: watchdog warning {response.reason_code}")
        return False
