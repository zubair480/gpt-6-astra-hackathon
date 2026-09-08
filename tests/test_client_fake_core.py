"""End-to-end: the fake core drives the real client against the mock service over uvicorn
(spec acceptance 10). Mode is configuration only: base URL plus credential file."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from plva_private_reasoning.client import PrivateReasoningClient, fake_core
from plva_private_reasoning.service.app import create_mock_app
from plva_private_reasoning.service.auth import write_credential

CREDENTIAL = "test-credential-not-a-real-secret-0123456789"
SYNTHETIC_VALUES = (
    "Charlie Example",
    "Alice Example",
    "Bob Example",
    "charlie@example.invalid",
    "alice@example.invalid",
    "bob@example.invalid",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def mock_server() -> Iterator[str]:
    port = free_port()
    config = uvicorn.Config(
        create_mock_app(CREDENTIAL, port),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while not server.started:
        if time.monotonic() > deadline:  # pragma: no cover - environment failure
            raise RuntimeError("mock server did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


@pytest.fixture
def credential_file(tmp_path: Path) -> Path:
    return write_credential(tmp_path / ".plva-pr", CREDENTIAL)


def test_fake_core_succeeds_against_mock_without_printing_values(
    mock_server: str, credential_file: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("PLVA_PR_BASE_URL", mock_server)
    monkeypatch.setenv("PLVA_PR_CREDENTIAL_FILE", str(credential_file))
    assert fake_core.main([]) == 0
    out = capsys.readouterr().out
    assert "mode=mock" in out and "MOCK MODE" in out
    assert "approve decision=approve reason=POLICY_MATCH ttl_seconds=30 max_uses=1" in out
    sorted_tokens = "['NAME_2_a3f9', 'NAME_3_a3f9', 'NAME_1_a3f9']"
    assert f"compute/sort status=ok reason=COMPLETED tokens={sorted_tokens}" in out
    assert (
        "compute/select status=ok reason=COMPLETED tokens=['EMAIL_2_b7c2', 'EMAIL_3_b7c2']" in out
    )
    assert "review-trace action=continue reason=NOMINAL" in out
    assert "failures=0" in out
    for value in SYNTHETIC_VALUES:
        assert value not in out
    assert CREDENTIAL not in out


def test_fake_core_reports_failure_when_service_is_down(
    credential_file: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("PLVA_PR_BASE_URL", f"http://127.0.0.1:{free_port()}")
    monkeypatch.setenv("PLVA_PR_CREDENTIAL_FILE", str(credential_file))
    assert fake_core.main([]) == 1
    out = capsys.readouterr().out
    assert "readiness unavailable failure=unreachable" in out
    for value in SYNTHETIC_VALUES:
        assert value not in out


def test_fake_core_reports_missing_credential(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("PLVA_PR_CREDENTIAL_FILE", str(tmp_path / "missing"))
    assert fake_core.main([]) == 2
    assert "credential file unreadable" in capsys.readouterr().out


def test_client_against_real_mock_transport(mock_server: str) -> None:
    """The stdlib transport satisfies the service's Host/Origin/auth/content-type checks."""
    client = PrivateReasoningClient(mock_server, CREDENTIAL, timeout_seconds=5.0)
    readiness = client.readiness()
    assert readiness is not None and readiness.mode == "mock"
    # Real values are refused for mock mode unless explicitly allowed.
    computed = client.compute(
        {
            "schema_version": "1.0",
            "session_id": "transport",
            "request_id": "compute-gate",
            "operation": "sort",
            "instruction": "Alphabetical.",
            "items": [
                {"token": "NAME_1_a3f9", "value": "Charlie Example"},
                {"token": "NAME_2_a3f9", "value": "Alice Example"},
            ],
        }
    )
    assert (computed.status, computed.reason_code) == ("error", "NOT_READY")
    review = client.review_trace(
        {
            "schema_version": "1.0",
            "session_id": "transport",
            "request_id": "trace-1",
            "events": [{"step": 1, "kind": "blocked_class_attempt", "pii_class": "SSN"}],
        }
    )
    assert (review.action, review.reason_code) == ("halt", "BLOCKED_CLASS_ATTEMPT")
    # Replaying the identifier pair is a 409 at the service and a deny/halt at the client.
    replay = client.review_trace(
        {
            "schema_version": "1.0",
            "session_id": "transport",
            "request_id": "trace-1",
            "events": [{"step": 1, "kind": "action"}],
        }
    )
    assert (replay.action, replay.reason_code) == ("halt", "MODEL_UNAVAILABLE")
    assert client.last_failure == "http_409"


def test_wrong_credential_against_real_mock_fails_closed(mock_server: str) -> None:
    client = PrivateReasoningClient(mock_server, "wrong-credential", timeout_seconds=5.0)
    assert client.readiness() is None
    assert client.last_failure == "http_401"
