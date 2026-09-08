"""Redaction feed, operator-token gating, and the public access-code gate."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plva_agent_demo import ui as ui_mod
from plva_agent_demo.state import RunConfig, RunState, StepRecord
from plva_agent_demo.types import StepEvent

SECRET = "sk-live-synthetic-77"


def populated_state() -> RunState:
    state = RunState()
    state.reset(RunConfig(url="http://127.0.0.1:1/x", task="t"))
    state.set_status("running")
    state.vault_put("API_KEY_1_ab12", "API_KEY", "approval", SECRET)
    state.vault_put("EMAIL_1_ab12", "EMAIL", "hide_use", "a@example.invalid")
    state.add_step(
        StepRecord(
            step=1,
            redacted_png=b"\x89PNG-redacted",
            raw_png=b"\x89PNG-raw",
            manifest=[{"token": "API_KEY_1_ab12", "class": "API_KEY", "level": "approval"}],
            frame_sha256="ab" * 32,
            mask_count=3,
        )
    )
    state.add_event(StepEvent(step=1, kind="resolution_ok", token="API_KEY_1_ab12"))
    return state


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PLVA_PR_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("PLVA_UI_PUBLIC", raising=False)
    monkeypatch.delenv("PLVA_UI_ACCESS_CODE", raising=False)
    return tmp_path


def test_redactions_are_value_free_by_default(runtime: Path) -> None:
    client = TestClient(ui_mod.create_ui_app(populated_state()))
    body = client.get("/api/redactions").json()
    assert body["count"] == 1
    record = body["records"][0]
    assert record["tokens"]["API_KEY_1_ab12"] == {
        "class": "API_KEY",
        "level": "approval",
        "stored": True,
    }
    assert SECRET not in client.get("/api/redactions").text
    assert "redacted_png" not in record
    with_images = client.get("/api/redactions?images=1").json()["records"][0]
    assert base64.b64decode(with_images["redacted_png"]) == b"\x89PNG-redacted"
    assert "raw_png" not in with_images


def test_values_require_operator_token(runtime: Path) -> None:
    client = TestClient(ui_mod.create_ui_app(populated_state()))
    denied = client.get("/api/redactions?values=1")
    assert denied.status_code == 403 and SECRET not in denied.text
    wrong = client.get("/api/redactions?values=1", headers={"X-PLVA-Operator": "nope"})
    assert wrong.status_code == 403
    token = (runtime / "ui-operator-token").read_text().strip()
    assert (runtime / "ui-operator-token").stat().st_mode & 0o777 == 0o600
    ok = client.get("/api/redactions?values=1", headers={"X-PLVA-Operator": token})
    assert ok.status_code == 200
    assert ok.json()["records"][0]["tokens"]["API_KEY_1_ab12"]["value"] == SECRET


def test_private_mode_has_no_gate(runtime: Path) -> None:
    client = TestClient(ui_mod.create_ui_app(RunState()))
    assert client.get("/api/state").status_code == 200
    assert client.get("/health").json() == {"status": "alive"}


def test_public_mode_gate(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLVA_UI_PUBLIC", "1")
    monkeypatch.setenv("PLVA_UI_ACCESS_CODE", "open-sesame")
    client = TestClient(ui_mod.create_ui_app(populated_state()), follow_redirects=False)
    assert client.get("/").status_code == 302
    assert client.get("/api/state").status_code == 401
    assert client.get("/health").status_code == 200
    bad = client.post("/login", data={"code": "wrong"})
    assert bad.status_code == 401
    good = client.post("/login", data={"code": "open-sesame"})
    assert good.status_code == 303 and "plva_access" in good.headers.get("set-cookie", "")
    assert client.get("/api/state").status_code == 200
    # the access code never unlocks values; that still needs the operator token
    assert client.get("/api/redactions?values=1").status_code == 403
