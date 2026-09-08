"""Client fail-closed behaviour (spec acceptance 7 and 8) against a scripted HTTP server."""

from __future__ import annotations

import http.client
import itertools
import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from plva_private_reasoning.client import (
    MODEL_UNAVAILABLE,
    NOT_READY,
    ClientError,
    PrivateReasoningClient,
    load_credential,
)
from plva_private_reasoning.client import client as client_module

CREDENTIAL = "test-credential-not-a-real-secret-0123456789"
SYNTHETIC_VALUES = ("Alice Example", "Charlie Example", "alice@example.invalid")


def approve_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": "sess-1",
        "request_id": "approval-001",
        "token": "API_KEY_1_a3f9",
        "pii_class": "API_KEY",
        "tool_name": "type",
        "argument_path": "text",
        "destination": {
            "origin": "https://service.example",
            "field_id": "api-key-input",
            "verified_by_runtime": True,
        },
        "task_context": "Configure the authorized integration.",
        "policy": {
            "policy_id": "integration-policy-v1",
            "rules": [],
            "allowed_origins": ["https://service.example"],
            "allowed_fields": ["api-key-input"],
            "max_ttl_seconds": 60,
            "max_uses": 1,
        },
    }


def compute_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": "sess-1",
        "request_id": "compute-001",
        "operation": "sort",
        "instruction": "Alphabetical order by full name.",
        "items": [
            {"token": "NAME_1_a3f9", "value": "Charlie Example"},
            {"token": "NAME_2_a3f9", "value": "Alice Example"},
        ],
    }


def trace_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": "sess-1",
        "request_id": "trace-001",
        "events": [{"step": 1, "kind": "action", "tool_name": "type"}],
    }


def readiness_payload(ready: bool) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "local" if ready else "mock",
        "ready_for_private_values": ready,
        "model_loaded": ready,
        "isolation": "verified" if ready else "unverified",
        "capabilities": ["approve", "compute", "review-trace"],
        "instance_id": "0f3c2d9e4b8a4c1d9e7f6a5b4c3d2e1f",
        "service_version": "0.1.0",
        "verified_at": None,
    }


def genuine_response(path: str, request: dict[str, Any]) -> dict[str, Any]:
    envelope = {key: request[key] for key in ("schema_version", "session_id", "request_id")}
    if path.endswith("/approve"):
        return {
            **envelope,
            "decision": "approve",
            "reason_code": "POLICY_MATCH",
            "scope": {
                "token": request["token"],
                "tool_name": request["tool_name"],
                "argument_path": request["argument_path"],
                "origin": request["destination"]["origin"],
                "field_id": request["destination"]["field_id"],
                "ttl_seconds": 30,
                "max_uses": 1,
            },
        }
    if path.endswith("/compute"):
        tokens = [item["token"] for item in request["items"]]
        return {**envelope, "status": "ok", "tokens": tokens, "reason_code": "COMPLETED"}
    return {**envelope, "action": "continue", "reason_code": "NOMINAL"}


@dataclass
class Script:
    """What the scripted server does. ``post_mode`` selects the POST behaviour."""

    post_mode: str = "ok"
    ready: bool = True
    delay_seconds: float = 0.0
    calls: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)

    def respond(self, method: str, path: str, body: bytes) -> tuple[int, bytes]:
        if method == "GET" and path == "/v1/readiness":
            return 200, json.dumps(readiness_payload(self.ready)).encode()
        request = json.loads(body)
        if self.post_mode == "ok":
            return 200, json.dumps(genuine_response(path, request)).encode()
        if self.post_mode == "malformed":
            return 200, b'{"schema_version": "1.0", "decision": '
        if self.post_mode == "not-json-object":
            return 200, b'["approve"]'
        if self.post_mode == "wrong-request-id":
            return 200, json.dumps(
                {**genuine_response(path, request), "request_id": "other"}
            ).encode()
        if self.post_mode == "wrong-session-id":
            return 200, json.dumps(
                {**genuine_response(path, request), "session_id": "other"}
            ).encode()
        if self.post_mode == "wrong-schema-version":
            return 200, json.dumps(
                {**genuine_response(path, request), "schema_version": "2.0"}
            ).encode()
        if self.post_mode == "extra-field":
            return 200, json.dumps(
                {**genuine_response(path, request), "rationale": "free text"}
            ).encode()
        if self.post_mode == "wrong-shape":
            return 200, json.dumps(
                {**genuine_response(path, request), "decision": "maybe"}
            ).encode()
        if self.post_mode == "server-error":
            return 500, b'{"schema_version": "1.0", "error_code": "INTERNAL_ERROR"}'
        if self.post_mode == "unauthorized":
            return 401, b'{"schema_version": "1.0", "error_code": "UNAUTHORIZED"}'
        if self.post_mode == "oversized":
            return 200, b'{"padding": "' + b"x" * 70000 + b'"}'
        raise AssertionError(f"unknown post_mode {self.post_mode}")


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def server(script: Script) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:  # silence
            pass

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            script.calls.append((self.command, self.path, dict(self.headers.items())))
            if script.delay_seconds:
                time.sleep(script.delay_seconds)
            status, payload = script.respond(self.command, self.path, body)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError:
                pass  # client already gave up (timeout tests)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_client(base_url: str, **kwargs: Any) -> PrivateReasoningClient:
    kwargs.setdefault("timeout_seconds", 2.0)
    kwargs.setdefault("allow_mock_for_private_values", True)
    return PrivateReasoningClient(base_url, CREDENTIAL, **kwargs)


def assert_all_closed(client: PrivateReasoningClient, reason: str = MODEL_UNAVAILABLE) -> None:
    approval = client.approve(approve_request())
    assert (approval.decision, approval.reason_code, approval.scope) == ("deny", reason, None)
    assert (approval.session_id, approval.request_id) == ("sess-1", "approval-001")
    computed = client.compute(compute_request())
    assert (computed.status, computed.tokens, computed.reason_code) == ("error", [], reason)
    assert (computed.session_id, computed.request_id) == ("sess-1", "compute-001")
    review = client.review_trace(trace_request())
    assert (review.action, review.reason_code) == ("halt", reason)
    assert (review.session_id, review.request_id) == ("sess-1", "trace-001")


# --- happy path -----------------------------------------------------------------


def test_genuine_responses_are_returned_typed(server: str, script: Script) -> None:
    client = make_client(server)
    readiness = client.readiness()
    assert readiness is not None and readiness.ready_for_private_values is True
    approval = client.approve(approve_request())
    assert approval.decision == "approve" and approval.scope is not None
    computed = client.compute(compute_request())
    assert computed.tokens == ["NAME_1_a3f9", "NAME_2_a3f9"]
    review = client.review_trace(trace_request())
    assert review.action == "continue"
    assert client.last_failure is None


def test_request_headers_are_exactly_bearer_and_json(server: str, script: Script) -> None:
    client = make_client(server)
    client.approve(approve_request())
    method, path, headers = script.calls[-1]
    lowered = {key.lower(): value for key, value in headers.items()}
    assert (method, path) == ("POST", "/v1/approve")
    assert lowered["authorization"] == f"Bearer {CREDENTIAL}"
    assert lowered["content-type"] == "application/json"
    assert "origin" not in lowered
    assert lowered["host"] == server.removeprefix("http://")


def test_base_url_path_prefix_is_honoured(server: str, script: Script) -> None:
    client = make_client(f"{server}/prefix/")
    client.approve(approve_request())
    assert script.calls[-1][1] == "/prefix/v1/approve"


# --- unavailable / malformed / mismatched (acceptance 7) ----------------------------


def test_dead_port_fails_closed() -> None:
    client = make_client(f"http://127.0.0.1:{free_port()}", timeout_seconds=1.0)
    assert client.readiness() is None
    assert client.last_failure == client_module.FAILURE_UNREACHABLE
    assert_all_closed(client)


@pytest.mark.parametrize(
    ("post_mode", "failure"),
    [
        ("malformed", client_module.FAILURE_MALFORMED),
        ("not-json-object", client_module.FAILURE_MALFORMED),
        ("wrong-shape", client_module.FAILURE_MALFORMED),
        ("extra-field", client_module.FAILURE_MALFORMED),
        ("oversized", client_module.FAILURE_OVERSIZED),
        ("wrong-request-id", client_module.FAILURE_MISMATCH),
        ("wrong-session-id", client_module.FAILURE_MISMATCH),
        ("wrong-schema-version", client_module.FAILURE_MALFORMED),  # Literal["1.0"] rejects it
        ("server-error", "http_500"),
        ("unauthorized", "http_401"),
    ],
)
def test_bad_service_responses_fail_closed(
    server: str, script: Script, post_mode: str, failure: str
) -> None:
    script.post_mode = post_mode
    client = make_client(server)
    assert_all_closed(client)
    assert client.last_failure == failure


def test_malformed_readiness_is_not_trusted(server: str, script: Script, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        script,
        "respond",
        lambda method, path, body: (200, b'{"schema_version": "1.0", "mode": "local"}'),
    )
    client = make_client(server, allow_mock_for_private_values=False)
    assert client.readiness() is None
    assert client.last_failure == client_module.FAILURE_MALFORMED
    computed = client.compute(compute_request())
    assert (computed.status, computed.reason_code) == ("error", NOT_READY)


# --- timeouts and late responses -----------------------------------------------------


def test_slow_server_times_out_and_fails_closed(server: str, script: Script) -> None:
    script.delay_seconds = 0.6
    client = make_client(server, timeout_seconds=0.15)
    start = time.monotonic()
    approval = client.approve(approve_request())
    assert time.monotonic() - start < 0.5
    assert (approval.decision, approval.reason_code) == ("deny", MODEL_UNAVAILABLE)
    assert client.last_failure == client_module.FAILURE_TIMEOUT


def test_response_after_deadline_is_ignored_even_if_valid(server: str, script: Script) -> None:
    # Each exchange reads the clock twice: once for the deadline, once when the reply lands.
    ticks = itertools.count(0.0, 100.0)
    client = make_client(server, timeout_seconds=1.0, clock=lambda: next(ticks))
    assert_all_closed(client)
    assert client.last_failure == client_module.FAILURE_LATE
    # The service did answer; the client simply refused to honour it.
    assert [call[1] for call in script.calls] == ["/v1/approve", "/v1/compute", "/v1/review-trace"]


def test_approvals_are_never_retried(server: str, script: Script) -> None:
    script.post_mode = "server-error"
    client = make_client(server)
    client.approve(approve_request())
    assert [call[:2] for call in script.calls] == [("POST", "/v1/approve")]
    script.post_mode = "malformed"
    client.approve(approve_request())
    assert len(script.calls) == 2


# --- disabled mode ---------------------------------------------------------------------


def test_disabled_client_makes_no_network_call(monkeypatch: Any) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("network call attempted while disabled")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", refuse)
    monkeypatch.setattr(http.client.HTTPConnection, "request", refuse)
    client = make_client("http://127.0.0.1:18555", enabled=False)
    assert client.enabled is False
    assert client.readiness() is None
    assert client.last_failure == client_module.FAILURE_DISABLED
    assert_all_closed(client)
    assert client.last_failure == client_module.FAILURE_DISABLED


def test_enabled_flag_is_exposed(server: str) -> None:
    assert make_client(server).enabled is True
    assert make_client(server, enabled=False).enabled is False


# --- readiness gate for compute -------------------------------------------------------


def test_compute_refuses_values_when_not_ready(server: str, script: Script) -> None:
    script.ready = False
    client = make_client(server, allow_mock_for_private_values=False)
    computed = client.compute(compute_request())
    assert (computed.status, computed.tokens, computed.reason_code) == ("error", [], NOT_READY)
    assert client.last_failure == client_module.FAILURE_NOT_READY
    assert [call[:2] for call in script.calls] == [("GET", "/v1/readiness")]
    for value in SYNTHETIC_VALUES:
        assert not any(value in json.dumps(call) for call in script.calls)


def test_compute_refuses_values_when_readiness_unreachable() -> None:
    client = make_client(
        f"http://127.0.0.1:{free_port()}", allow_mock_for_private_values=False, timeout_seconds=1.0
    )
    computed = client.compute(compute_request())
    assert (computed.status, computed.reason_code) == ("error", NOT_READY)


def test_compute_sends_values_when_ready_and_caches_readiness(server: str, script: Script) -> None:
    now = [1000.0]
    client = make_client(
        server,
        allow_mock_for_private_values=False,
        readiness_ttl_seconds=5.0,
        clock=lambda: now[0],
    )
    assert client.compute(compute_request()).status == "ok"
    assert client.compute(compute_request()).status == "ok"
    paths = [call[:2] for call in script.calls]
    assert paths == [("GET", "/v1/readiness"), ("POST", "/v1/compute"), ("POST", "/v1/compute")]
    now[0] += 6.0  # cache expired
    assert client.compute(compute_request()).status == "ok"
    assert script.calls[-2][:2] == ("GET", "/v1/readiness")


def test_explicit_mock_opt_in_skips_readiness_gate(server: str, script: Script) -> None:
    script.ready = False
    client = make_client(server, allow_mock_for_private_values=True)
    assert client.allow_mock_for_private_values is True
    assert client.compute(compute_request()).status == "ok"
    assert [call[:2] for call in script.calls] == [("POST", "/v1/compute")]


def test_readiness_gate_reacts_to_service_going_unready(server: str, script: Script) -> None:
    now = [0.0]
    client = make_client(server, allow_mock_for_private_values=False, clock=lambda: now[0])
    assert client.compute(compute_request()).status == "ok"
    script.ready = False
    now[0] += 10.0
    assert client.compute(compute_request()).reason_code == NOT_READY


# --- caller errors never carry bodies -------------------------------------------------


def test_invalid_request_raises_without_echo(server: str, script: Script) -> None:
    client = make_client(server)
    bad = compute_request() | {"items": [{"token": "bad token", "value": "Alice Example"}]}
    with pytest.raises(ClientError) as info:
        client.compute(bad)
    assert "Alice Example" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert script.calls == []  # nothing left the process
    with pytest.raises(ClientError):
        client.approve({"session_id": "x", "secret": "Alice Example"})
    with pytest.raises(ClientError):
        client.review_trace({"schema_version": "1.0"})


@pytest.mark.parametrize(
    "base_url",
    ["ftp://127.0.0.1:18555", "127.0.0.1:18555", "http://", "http://127.0.0.1:18555/?x=1"],
)
def test_bad_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(ClientError):
        PrivateReasoningClient(base_url, CREDENTIAL)


def test_empty_credential_and_timeout_are_rejected() -> None:
    with pytest.raises(ClientError):
        PrivateReasoningClient("http://127.0.0.1:18555", "")
    with pytest.raises(ClientError):
        PrivateReasoningClient("http://127.0.0.1:18555", CREDENTIAL, timeout_seconds=0)


def test_load_credential_strips_and_rejects_empty(tmp_path: Any) -> None:
    path = tmp_path / "credential"
    path.write_text(f"  {CREDENTIAL}\n", encoding="utf-8")
    assert load_credential(path) == CREDENTIAL
    assert load_credential(str(path)) == CREDENTIAL
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ClientError):
        load_credential(path)
    with pytest.raises(OSError):
        load_credential(tmp_path / "missing")
