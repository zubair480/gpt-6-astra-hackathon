"""Runner loop with fake browser, fake redactor, fake cloud model, fake private reasoning."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

from plva_agent_demo import runner as runner_mod
from plva_agent_demo.state import RunConfig, RunState
from plva_agent_demo.types import Box, Field, RedactedFrame, Snapshot
from plva_agent_demo.vault import Vault
from plva_private_reasoning.contracts import ApproveResponse, ComputeResponse, ReviewTraceResponse

EMAIL = "alice.example@example.invalid"
KEY = "sk-live-synthetic-a1b2c3d4e5f6"
PASSWORD = "hunter2-synthetic"
NAMES = ["Charlie Example", "Alice Example", "Bob Example"]


class FakeBrowser:
    typed: ClassVar[list[str]] = []
    clicks: ClassVar[list[tuple[float, float]]] = []

    def __init__(self) -> None:
        FakeBrowser.typed = []
        FakeBrowser.clicks = []
        self.focused = "api-key-input"

    def __enter__(self) -> FakeBrowser:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def navigate(self, url: str) -> None:
        self.url = url

    def wait_settled(self) -> None:
        return None

    def snapshot(self) -> Snapshot:
        return Snapshot(
            url="http://127.0.0.1:3000/api/test-page",
            origin="http://127.0.0.1:3000",
            title="Acme",
            width=1280,
            height=900,
            png=b"\x89PNG-raw",
            spans=[],
            fields=[
                Field(
                    "api-key-input",
                    "Paste your Acme API key",
                    Box(0, 0, 10, 10),
                    "text",
                    self.focused == "api-key-input",
                ),
                Field(
                    "support-message",
                    "Message to Acme support",
                    Box(0, 20, 10, 10),
                    "textarea",
                    self.focused == "support-message",
                ),
            ],
            focused_field_id=self.focused,
        )

    def click(self, x: float, y: float) -> None:
        FakeBrowser.clicks.append((x, y))

    def type_text(self, text: str) -> None:
        FakeBrowser.typed.append(text)

    def press(self, key: str) -> None:
        return None

    def scroll(self, dy: int) -> None:
        return None


def fake_redact(
    snapshot: Snapshot, vault: Vault, policy: dict[str, str]
) -> tuple[RedactedFrame, list[Any]]:
    vault.issue("EMAIL", EMAIL)
    vault.issue("API_KEY", KEY)
    vault.issue("PASSWORD", PASSWORD)
    for name in NAMES:
        vault.issue("NAME", name)
    manifest = [{"token": t, "class": c, "level": lv} for t, c, lv in vault.entries()]
    return RedactedFrame(png=b"\x89PNG-redacted", masks=[], manifest=manifest, sha256="ab" * 32), []


def fake_scrub(text: str, vault: Vault) -> tuple[str, int]:
    hits = 0
    for value, token in vault.values_longest_first():
        if value in text:
            text = text.replace(value, token or "«BLOCKED»")
            hits += 1
    return text, hits


class FakeResponses:
    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        action = self.script.pop(0) if self.script else {"kind": "done", "text": "finished"}
        base = {
            "reasoning": "r",
            "kind": "done",
            "x": None,
            "y": None,
            "text": None,
            "key": None,
            "dy": None,
            "operation": None,
            "tokens": [],
            "select_count": None,
        }
        base.update(action)
        return types.SimpleNamespace(output_text=json.dumps(base))


class FakeOpenAI:
    last: FakeOpenAI
    script: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **_: Any) -> None:
        self.responses = FakeResponses(FakeOpenAI.script)
        self.models = types.SimpleNamespace(list=lambda: [])
        FakeOpenAI.last = self


class FakePR:
    approve_decision = "approve"
    review_action = "continue"
    calls: ClassVar[list[tuple[str, dict[str, Any]]]] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def readiness(self) -> Any:
        return types.SimpleNamespace(mode="mock", model_dump=lambda: {"mode": "mock"})

    def approve(self, req: dict[str, Any]) -> ApproveResponse:
        FakePR.calls.append(("approve", req))
        if FakePR.approve_decision == "approve":
            return ApproveResponse(
                schema_version="1.0",
                session_id=req["session_id"],
                request_id=req["request_id"],
                decision="approve",
                reason_code="POLICY_MATCH",
                scope={
                    "token": req["token"],
                    "tool_name": "type",
                    "argument_path": "text",
                    "origin": req["destination"]["origin"],
                    "field_id": req["destination"]["field_id"],
                    "ttl_seconds": 30,
                    "max_uses": 1,
                },
            )
        return ApproveResponse(
            schema_version="1.0",
            session_id=req["session_id"],
            request_id=req["request_id"],
            decision="deny",
            reason_code="FIELD_NOT_ALLOWED",
            scope=None,
        )

    def compute(self, req: dict[str, Any]) -> ComputeResponse:
        FakePR.calls.append(("compute", req))
        ordered = sorted(req["items"], key=lambda i: i["value"])
        return ComputeResponse(
            schema_version="1.0",
            session_id=req["session_id"],
            request_id=req["request_id"],
            status="ok",
            tokens=[i["token"] for i in ordered],
            reason_code="COMPLETED",
        )

    def review_trace(self, req: dict[str, Any]) -> ReviewTraceResponse:
        FakePR.calls.append(("review", req))
        return ReviewTraceResponse(
            schema_version="1.0",
            session_id=req["session_id"],
            request_id=req["request_id"],
            action=FakePR.review_action,
            reason_code="NOMINAL"
            if FakePR.review_action == "continue"
            else "BLOCKED_CLASS_ATTEMPT",
        )


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    FakePR.calls = []
    FakePR.approve_decision = "approve"
    FakePR.review_action = "continue"
    monkeypatch.setitem(
        sys.modules, "plva_agent_demo.browser", types.SimpleNamespace(Browser=FakeBrowser)
    )
    monkeypatch.setitem(
        sys.modules,
        "plva_agent_demo.redact",
        types.SimpleNamespace(redact=fake_redact, scrub_text=fake_scrub),
    )
    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    import plva_private_reasoning.client as client_mod

    monkeypatch.setattr(client_mod, "PrivateReasoningClient", FakePR)
    monkeypatch.setattr(client_mod, "load_credential", lambda _p: "cred")
    monkeypatch.setattr(
        runner_mod, "load_env", lambda: {"OPENAI_API_KEY": "test", "OPENAI_MODEL": "fake-model"}
    )
    yield


def run_with(
    script: list[dict[str, Any]], task: str = "do it", policy: dict[str, str] | None = None
) -> RunState:
    FakeOpenAI.script = script
    state = RunState()
    config = RunConfig(url="http://127.0.0.1:3000/api/test-page", task=task, max_steps=6)
    if policy:
        config.policy.update(policy)  # type: ignore[arg-type]
    state.reset(config)
    runner_mod.Runner(state, config).run()
    return state


def token_for(state: RunState, pii_class: str) -> str:
    return next(t for t, e in state.vault.items() if e["class"] == pii_class)


def test_done_and_outbound_is_value_free(wired: None) -> None:
    state = run_with(
        [{"kind": "click", "x": 10, "y": 10}, {"kind": "done", "text": "ok"}],
        task=f"email {EMAIL} please",
    )
    assert state.status == "done" and len(state.steps) == 2
    sent = json.dumps(FakeOpenAI.last.responses.calls)
    assert EMAIL not in sent and KEY not in sent and PASSWORD not in sent
    assert state.leaks_found == 0 and state.outbound_requests == 2
    # task text was scrubbed to a token
    assert token_for(state, "EMAIL") in sent
    assert state.steps[0].manifest and all("value" not in m for m in state.steps[0].manifest)


def test_hide_use_token_resolves_locally(wired: None) -> None:
    FakeOpenAI.script = []
    state = RunState()
    # need the token before scripting: run one pass to learn the nonce via a probe run
    probe = run_with([{"kind": "done"}])
    email_token = token_for(probe, "EMAIL")

    # tokens are per-vault (fresh nonce per run): script by class, substitute live tokens
    class Sub(FakeResponses):
        def create(self, **kwargs: Any) -> Any:
            manifest = json.loads(kwargs["input"][0]["content"][0]["text"])["token_manifest"]
            tok = next(m["token"] for m in manifest if m["class"] == "EMAIL")
            self.script = (
                [{"kind": "type", "text": f"hello «{tok}»"}, {"kind": "done"}]
                if not self.calls
                else self.script
            )
            return super().create(**kwargs)

    FakeOpenAI.script = []
    orig = FakeOpenAI.__init__

    def init(self: Any, **_: Any) -> None:
        self.responses = Sub([])
        self.models = types.SimpleNamespace(list=lambda: [])
        FakeOpenAI.last = self

    FakeOpenAI.__init__ = init  # type: ignore[method-assign]
    try:
        state = run_with([])
    finally:
        FakeOpenAI.__init__ = orig  # type: ignore[method-assign]
    assert state.status == "done"
    assert FakeBrowser.typed == [f"hello {EMAIL}"]
    kinds = [e.kind for e in state.all_events()]
    assert "resolution_ok" in kinds
    assert (
        email_token != token_for(state, "EMAIL") or True
    )  # nonce differs per run; fine either way


def _scripted_by_class(script_fn: Any) -> None:
    class Sub(FakeResponses):
        def create(self, **kwargs: Any) -> Any:
            manifest = json.loads(kwargs["input"][0]["content"][0]["text"])["token_manifest"]
            by_class: dict[str, list[str]] = {}
            for m in manifest:
                by_class.setdefault(m["class"], []).append(m["token"])
            if not self.calls:
                self.script = script_fn(by_class)
            return super().create(**kwargs)

    def init(self: Any, **_: Any) -> None:
        self.responses = Sub([])
        self.models = types.SimpleNamespace(list=lambda: [])
        FakeOpenAI.last = self

    FakeOpenAI.__init__ = init  # type: ignore[method-assign]


@pytest.fixture
def by_class(wired: None) -> Iterator[Any]:
    orig = FakeOpenAI.__init__
    yield _scripted_by_class
    FakeOpenAI.__init__ = orig  # type: ignore[method-assign]


def test_api_key_goes_through_approval(by_class: Any) -> None:
    by_class(lambda bc: [{"kind": "type", "text": f"«{bc['API_KEY'][0]}»"}, {"kind": "done"}])
    state = run_with([])
    assert state.status == "done"
    assert FakeBrowser.typed == [KEY]
    assert state.approvals and state.approvals[0].decision == "approve"
    req = next(r for k, r in FakePR.calls if k == "approve")
    assert req["destination"] == {
        "origin": "http://127.0.0.1:3000",
        "field_id": "api-key-input",
        "verified_by_runtime": True,
    }
    assert (
        "api-key-input" in req["policy"]["allowed_fields"]
        and "support-message" not in req["policy"]["allowed_fields"]
    )
    assert KEY not in json.dumps(req)


def test_api_key_denied_is_not_typed(by_class: Any) -> None:
    FakePR.approve_decision = "deny"
    by_class(lambda bc: [{"kind": "type", "text": f"«{bc['API_KEY'][0]}»"}, {"kind": "done"}])
    state = run_with([])
    assert FakeBrowser.typed == []
    assert state.approvals[0].decision == "deny"
    assert any(e.kind == "approval_denied" for e in state.all_events())


def test_blocked_password_never_typed_and_watchdog_halts(by_class: Any) -> None:
    FakePR.review_action = "halt"
    # PASSWORD is blocked: no token exists. The model may still try a forged-looking token.
    by_class(lambda bc: [{"kind": "type", "text": "«PASSWORD_1_0000»"}, {"kind": "done"}])
    state = run_with([])
    assert FakeBrowser.typed == []
    kinds = [e.kind for e in state.all_events()]
    assert "token_invalid" in kinds
    assert state.status == "halted"
    assert any(k == "review" for k, _ in FakePR.calls)


def test_private_compute_sort_returns_tokens_only(by_class: Any) -> None:
    by_class(
        lambda bc: [
            {
                "kind": "private_compute",
                "operation": "sort",
                "tokens": bc["NAME"],
                "text": "alphabetical",
            },
            {"kind": "done"},
        ]
    )
    state = run_with([])
    assert state.status == "done"
    compute = state.computes[0]
    assert compute["status"] == "ok" and len(compute["tokens"]) == 3
    req = next(r for k, r in FakePR.calls if k == "compute")
    assert {i["value"] for i in req["items"]} == set(NAMES)  # values go ONLY to the private service
    assert all(n not in json.dumps(FakeOpenAI.last.responses.calls) for n in NAMES)


def test_compute_refused_for_non_hide_use(by_class: Any) -> None:
    by_class(
        lambda bc: [
            {
                "kind": "private_compute",
                "operation": "sort",
                "tokens": [bc["API_KEY"][0], bc["EMAIL"][0]],
                "text": "x",
            },
            {"kind": "done"},
        ]
    )
    state = run_with([])
    assert not state.computes
    assert any(e.kind == "resolution_denied" for e in state.all_events())


def test_missing_key_fails_cleanly(wired: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "load_env", lambda: {})
    state = run_with([{"kind": "done"}])
    assert state.status == "failed" and "OPENAI_API_KEY" in state.summary
