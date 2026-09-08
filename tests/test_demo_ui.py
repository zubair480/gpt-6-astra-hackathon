"""Tests for the operator UI (src/plva_agent_demo/ui.py). Synthetic values only.

The runner is replaced by a fake module injected into ``sys.modules`` so no browser or model
is needed. Every response is checked to be value-free unless ``reveal=1`` is asked for.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plva_agent_demo import ui
from plva_agent_demo.state import ApprovalRecord, RunConfig, RunState, StepRecord
from plva_agent_demo.types import DEFAULT_POLICY, StepEvent

RUNNER_MODULE = "plva_agent_demo.runner"
SYNTHETIC_EMAIL = "alice.synthetic@example.invalid"
SYNTHETIC_KEY = "sk-synthetic-example-key-0000"
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
GOOD_BODY: dict[str, Any] = {
    "url": "http://127.0.0.1:18600/api/test-page",
    "task": "Send a support message that includes my email address",
    "policy": dict(DEFAULT_POLICY),
    "max_steps": 5,
    "plva_enabled": True,
}


def fake_runner(*, finish: bool = True) -> types.ModuleType:
    """A runner that writes a few synthetic steps synchronously into the state."""
    mod = types.ModuleType(RUNNER_MODULE)
    calls: list[tuple[str, Any]] = []

    def start_run(state: RunState, config: RunConfig) -> None:
        calls.append(("start", config))
        state.set_status("running")
        state.set_readiness(
            {"mode": "mock", "ready_for_private_values": False, "isolation": "unverified"}
        )
        state.vault_put("«EMAIL_1_ab12»", "EMAIL", "hide_use", SYNTHETIC_EMAIL)
        state.vault_put("«API_KEY_1_cd34»", "API_KEY", "approval", SYNTHETIC_KEY)
        state.vault_put("«PASSWORD_1_ef56»", "PASSWORD", "blocked", None)
        state.add_step(
            StepRecord(
                step=1,
                reasoning="Click the support message box.",
                action={"kind": "click", "x": 10, "y": 20, "reasoning": "focus the box"},
                redacted_png=FAKE_PNG,
                raw_png=FAKE_PNG,
                manifest=[{"token": "«EMAIL_1_ab12»", "class": "EMAIL", "level": "hide_use"}],
                frame_sha256="a" * 64,
                mask_count=3,
                outbound_bytes=len(FAKE_PNG),
                redact_ms=12.5,
                model_ms=340.0,
                url=config.url,
            )
        )
        state.note_outbound(leaked=False)
        state.add_event(StepEvent(step=1, kind="action", detail="click"))
        state.add_step(
            StepRecord(
                step=2,
                reasoning="Type the email token.",
                action={"kind": "type", "text": "Hello, my email is «EMAIL_1_ab12»"},
                redacted_png=FAKE_PNG,
                raw_png=FAKE_PNG,
                frame_sha256="b" * 64,
                mask_count=3,
                outbound_bytes=len(FAKE_PNG),
                url=config.url,
            )
        )
        state.note_outbound(leaked=False)
        state.add_event(
            StepEvent(step=2, kind="resolution_ok", token="«EMAIL_1_ab12»", pii_class="EMAIL")
        )
        state.vault_resolved("«EMAIL_1_ab12»")
        state.add_approval(
            ApprovalRecord(
                step=2,
                token="«API_KEY_1_cd34»",
                pii_class="API_KEY",
                decision="deny",
                reason_code="DESTINATION_MISMATCH",
                scope=None,
                latency_ms=8.0,
            )
        )
        state.add_review({"step": 2, "action": "continue", "reason_code": "OK", "latency_ms": 4.0})
        state.add_compute(
            {
                "step": 2,
                "operation": "sort",
                "status": "ok",
                "reason_code": "OK",
                "tokens": ["«NAME_1_0001»", "«NAME_2_0002»"],
            }
        )
        if finish:
            state.set_status("done", "Task completed on synthetic page.")

    def stop_run(state: RunState) -> None:
        calls.append(("stop", None))
        state.stop_requested = True
        state.set_status("halted", "stopped by operator")

    mod.start_run = start_run  # type: ignore[attr-defined]
    mod.stop_run = stop_run  # type: ignore[attr-defined]
    mod.calls = calls  # type: ignore[attr-defined]
    return mod


@pytest.fixture
def state() -> RunState:
    return RunState()


@pytest.fixture
def client(state: RunState) -> TestClient:
    return TestClient(ui.create_ui_app(state))


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    mod = fake_runner()
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, mod)
    return mod


# -- static ---------------------------------------------------------------------


def test_index_serves_inline_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert "PLVA agent demo" in r.text
    assert "/api/state" in r.text
    assert "<script src=" not in r.text  # no external CDNs
    assert "https://" not in r.text.split("<script>")[1]


def test_test_page_served(client: TestClient) -> None:
    r = client.get("/api/test-page")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Acme Cloud" in r.text
    assert "synthetic" in r.text.lower()


def test_policy_endpoint_returns_default_policy(client: TestClient) -> None:
    r = client.get("/api/policy")
    assert r.status_code == 200
    assert r.json() == DEFAULT_POLICY


def test_docs_are_disabled(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# -- state ----------------------------------------------------------------------


def test_state_initial_shape(client: TestClient) -> None:
    r = client.get("/api/state")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "idle"
    assert d["steps"] == [] and d["vault"] == {} and d["approvals"] == []
    assert d["leaks_found"] == 0 and d["outbound_requests"] == 0
    assert d["config"]["policy"] == DEFAULT_POLICY
    assert r.headers["cache-control"] == "no-store"


def test_state_unchanged_path(client: TestClient, state: RunState) -> None:
    v = client.get("/api/state").json()["version"]
    assert v == state.version
    r = client.get("/api/state", params={"since": v})
    assert r.json() == {"version": v, "unchanged": True}
    state.set_status("running")
    r = client.get("/api/state", params={"since": v})
    assert "unchanged" not in r.json()
    assert r.json()["version"] == v + 1


# -- run validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.invalid/x",
        "javascript:alert(1)",
        "not a url",
        "",
        "http://",
        "data:text/html,x",
    ],
)
def test_run_rejects_bad_url(client: TestClient, runner: types.ModuleType, url: str) -> None:
    r = client.post("/api/run", json={**GOOD_BODY, "url": url})
    assert r.status_code == 400
    assert "error" in r.json()
    assert not runner.calls


@pytest.mark.parametrize("task", ["", "   ", None, 12])
def test_run_rejects_empty_task(client: TestClient, runner: types.ModuleType, task: Any) -> None:
    r = client.post("/api/run", json={**GOOD_BODY, "task": task})
    assert r.status_code == 400
    assert not runner.calls


@pytest.mark.parametrize(
    "policy",
    [
        {"NOT_A_CLASS": "hide_use"},
        {"EMAIL": "shout"},
        {"EMAIL": None},
        ["EMAIL", "hide_use"],
        "hide_use",
    ],
)
def test_run_rejects_bad_policy(client: TestClient, runner: types.ModuleType, policy: Any) -> None:
    r = client.post("/api/run", json={**GOOD_BODY, "policy": policy})
    assert r.status_code == 400
    assert not runner.calls


@pytest.mark.parametrize("max_steps", [0, -1, 101, "5", 2.5, True])
def test_run_rejects_bad_max_steps(
    client: TestClient, runner: types.ModuleType, max_steps: Any
) -> None:
    r = client.post("/api/run", json={**GOOD_BODY, "max_steps": max_steps})
    assert r.status_code == 400


def test_run_rejects_non_object_or_invalid_json(
    client: TestClient, runner: types.ModuleType
) -> None:
    assert client.post("/api/run", json=["x"]).status_code == 400
    r = client.post("/api/run", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert not runner.calls


def test_error_messages_never_echo_task_or_url(
    client: TestClient, runner: types.ModuleType
) -> None:
    secret = "ftp://alice.synthetic@example.invalid/very-private-path"
    r = client.post("/api/run", json={**GOOD_BODY, "url": secret, "task": SYNTHETIC_KEY})
    assert r.status_code == 400
    assert "alice.synthetic" not in r.text and "very-private" not in r.text
    assert SYNTHETIC_KEY not in r.text


# -- runner integration ----------------------------------------------------------


def test_run_returns_503_without_runner(
    client: TestClient, state: RunState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, None)  # forces ImportError
    r = client.post("/api/run", json=GOOD_BODY)
    assert r.status_code == 503
    assert r.json() == {"error": "runner not available"}
    assert state.status == "idle"
    assert client.post("/api/stop").status_code == 503


def test_run_builds_config_and_fake_runner_populates_state(
    client: TestClient, state: RunState, runner: types.ModuleType
) -> None:
    body = {
        **GOOD_BODY,
        "policy": {"EMAIL": "approval"},  # partial policy is filled from defaults
        "model": "gpt-synthetic",
        "plva_enabled": False,
    }
    r = client.post("/api/run", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    kind, config = runner.calls[0]
    assert kind == "start"
    assert isinstance(config, RunConfig)
    assert config.url == GOOD_BODY["url"]
    assert config.task == GOOD_BODY["task"]
    assert config.model == "gpt-synthetic"
    assert config.max_steps == 5
    assert config.plva_enabled is False
    assert config.policy["EMAIL"] == "approval"
    assert config.policy["PASSWORD"] == DEFAULT_POLICY["PASSWORD"]
    assert set(config.policy) == set(DEFAULT_POLICY)

    d = client.get("/api/state").json()
    assert d["status"] == "done"
    assert [s["step"] for s in d["steps"]] == [1, 2]
    assert d["config"]["plva_enabled"] is False
    assert d["outbound_requests"] == 2 and d["leaks_found"] == 0
    assert d["readiness"]["mode"] == "mock"
    assert d["steps"][0]["mask_count"] == 3
    assert d["steps"][0]["redacted_png"]  # base64 image present by default
    assert d["steps"][1]["events"][0]["kind"] == "resolution_ok"
    assert d["approvals"][0]["decision"] == "deny"
    assert d["reviews"][0]["action"] == "continue"
    assert d["computes"][0]["operation"] == "sort"


def test_view_is_value_free_unless_reveal(
    client: TestClient, state: RunState, runner: types.ModuleType
) -> None:
    assert client.post("/api/run", json=GOOD_BODY).status_code == 200

    hidden = client.get("/api/state").text
    assert SYNTHETIC_EMAIL not in hidden
    assert SYNTHETIC_KEY not in hidden
    vault = json.loads(hidden)["vault"]
    assert vault["«EMAIL_1_ab12»"] == {
        "class": "EMAIL",
        "level": "hide_use",
        "resolved": 1,
        "value": None,
        "stored": True,
    }
    assert vault["«PASSWORD_1_ef56»"]["stored"] is False
    assert vault["«PASSWORD_1_ef56»"]["value"] is None

    explicit_zero = client.get("/api/state", params={"reveal": 0}).text
    assert SYNTHETIC_EMAIL not in explicit_zero

    revealed = client.get("/api/state", params={"reveal": 1}).json()
    assert revealed["vault"]["«EMAIL_1_ab12»"]["value"] == SYNTHETIC_EMAIL
    assert revealed["vault"]["«API_KEY_1_cd34»"]["value"] == SYNTHETIC_KEY
    assert revealed["vault"]["«PASSWORD_1_ef56»"]["value"] is None


def test_images_can_be_omitted(client: TestClient, runner: types.ModuleType) -> None:
    assert client.post("/api/run", json=GOOD_BODY).status_code == 200
    d = client.get("/api/state", params={"images": 0}).json()
    assert all(s["redacted_png"] == "" and s["raw_png"] == "" for s in d["steps"])
    assert d["steps"][0]["frame_sha256"] == "a" * 64


def test_409_while_running_then_stop(
    client: TestClient, state: RunState, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = fake_runner(finish=False)
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, mod)
    assert client.post("/api/run", json=GOOD_BODY).status_code == 200
    assert state.status == "running"

    r = client.post("/api/run", json=GOOD_BODY)
    assert r.status_code == 409
    assert "error" in r.json()
    assert len([c for c in mod.calls if c[0] == "start"]) == 1
    assert len(state.steps) == 2  # the second request did not reset the state

    r = client.post("/api/stop")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "halted"}
    assert state.stop_requested is True

    # a new run is accepted again once the previous one is no longer running
    assert client.post("/api/run", json=GOOD_BODY).status_code == 200


def test_run_resets_previous_state(
    client: TestClient, state: RunState, runner: types.ModuleType
) -> None:
    assert client.post("/api/run", json=GOOD_BODY).status_code == 200
    first = client.get("/api/state").json()
    assert client.post("/api/run", json={**GOOD_BODY, "max_steps": 7}).status_code == 200
    second = client.get("/api/state").json()
    assert second["config"]["max_steps"] == 7
    assert len(second["steps"]) == len(first["steps"]) == 2
    assert second["outbound_requests"] == 2  # counters restarted, not accumulated


def test_runner_start_failure_marks_run_failed(
    client: TestClient, state: RunState, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = types.ModuleType(RUNNER_MODULE)

    def start_run(state: RunState, config: RunConfig) -> None:
        raise RuntimeError("playwright missing (synthetic)")

    mod.start_run = start_run  # type: ignore[attr-defined]
    mod.stop_run = lambda state: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, mod)
    r = client.post("/api/run", json=GOOD_BODY)
    assert r.status_code == 500
    assert state.status == "failed"
    assert "playwright" not in r.text  # exception text is not echoed to the browser


# -- cli ------------------------------------------------------------------------


def test_main_rejects_non_loopback_host() -> None:
    with pytest.raises(SystemExit) as exc:
        ui.main(["--host", "0.0.0.0", "--port", "18600"])
    assert exc.value.code == 2


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_is_loopback_host(host: str) -> None:
    assert ui.is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "example.invalid", ""])
def test_is_not_loopback_host(host: str) -> None:
    assert not ui.is_loopback_host(host)
