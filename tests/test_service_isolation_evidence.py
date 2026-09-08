"""Isolation evidence is re-read lazily, bound to the instance, and gates private values."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from plva_private_reasoning.service.app import (
    ServiceState,
    create_app,
    evaluate_evidence,
    mock_backends,
)

CRED = "test-credential"
PORT = 18555
POLICY_SHA = "a" * 64


def write(path: Path, **overrides: Any) -> None:
    body: dict[str, Any] = {
        "isolation": "verified",
        "verified_at": datetime.now(UTC).isoformat(),
        "instance_id": "instance-x",
        "policy_sha256": POLICY_SHA,
    }
    body.update(overrides)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_missing_file_is_unverified(tmp_path: Path) -> None:
    result = evaluate_evidence(
        tmp_path / "none.json",
        instance_id="instance-x",
        policy_sha256=None,
        max_age_seconds=900,
        now=datetime.now(UTC),
    )
    assert result == ("unverified", None)


def test_fresh_bound_evidence_verifies(tmp_path: Path) -> None:
    path = tmp_path / "ev.json"
    write(path)
    isolation, stamp = evaluate_evidence(
        path,
        instance_id="instance-x",
        policy_sha256=POLICY_SHA,
        max_age_seconds=900,
        now=datetime.now(UTC),
    )
    assert isolation == "verified" and stamp is not None


def _failed(tmp_path: Path, **overrides: Any) -> None:
    path = tmp_path / "ev.json"
    write(path, **overrides)
    isolation, _ = evaluate_evidence(
        path,
        instance_id="instance-x",
        policy_sha256=POLICY_SHA,
        max_age_seconds=900,
        now=datetime.now(UTC),
    )
    assert isolation == "failed"


def test_wrong_instance_fails(tmp_path: Path) -> None:
    _failed(tmp_path, instance_id="someone-else")


def test_wrong_policy_hash_fails(tmp_path: Path) -> None:
    _failed(tmp_path, policy_sha256="b" * 64)


def test_not_verified_state_fails(tmp_path: Path) -> None:
    _failed(tmp_path, isolation="failed")


def test_stale_fails(tmp_path: Path) -> None:
    old = (datetime.now(UTC) - timedelta(seconds=901)).isoformat()
    _failed(tmp_path, verified_at=old)


def test_naive_timestamp_fails(tmp_path: Path) -> None:
    _failed(tmp_path, verified_at=datetime.now().replace(tzinfo=None).isoformat())


def test_future_timestamp_fails(tmp_path: Path) -> None:
    _failed(tmp_path, verified_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())


def test_garbage_file_fails(tmp_path: Path) -> None:
    path = tmp_path / "ev.json"
    path.write_text("{not json", encoding="utf-8")
    isolation, _ = evaluate_evidence(
        path, instance_id="x", policy_sha256=None, max_age_seconds=900, now=datetime.now(UTC)
    )
    assert isolation == "failed"


def local_state(tmp_path: Path) -> ServiceState:
    return ServiceState(
        mode="local",
        credential=CRED,
        port=PORT,
        backends=mock_backends(),
        model_loaded=True,
        evidence_path=tmp_path / "ev.json",
        policy_sha256=POLICY_SHA,
    )


def compute_body() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": "s",
        "request_id": "c1",
        "operation": "sort",
        "instruction": "Alphabetical.",
        "items": [
            {"token": "NAME_1_a3f9", "value": "Bob Example"},
            {"token": "NAME_2_a3f9", "value": "Alice Example"},
        ],
    }


def test_readiness_flips_after_launch_and_back(tmp_path: Path) -> None:
    state = local_state(tmp_path)
    client = TestClient(create_app(state), base_url=f"http://127.0.0.1:{PORT}")
    headers = {"Authorization": f"Bearer {CRED}"}

    first = client.get("/v1/readiness", headers=headers).json()
    assert first["isolation"] == "unverified" and first["ready_for_private_values"] is False

    write(state.evidence_path or tmp_path, instance_id=first["instance_id"])  # type: ignore[arg-type]
    second = client.get("/v1/readiness", headers=headers).json()
    assert second["isolation"] == "verified" and second["ready_for_private_values"] is True

    (tmp_path / "ev.json").unlink()
    third = client.get("/v1/readiness", headers=headers).json()
    assert third["isolation"] == "unverified" and third["ready_for_private_values"] is False


def test_local_compute_refused_until_verified(tmp_path: Path) -> None:
    state = local_state(tmp_path)
    client = TestClient(create_app(state), base_url=f"http://127.0.0.1:{PORT}")
    headers = {"Authorization": f"Bearer {CRED}", "Content-Type": "application/json"}

    refused = client.post("/v1/compute", headers=headers, json=compute_body())
    assert refused.status_code == 503
    assert refused.json() == {"schema_version": "1.0", "error_code": "NOT_READY"}
    assert "Example" not in refused.text

    write(tmp_path / "ev.json", instance_id=state.instance_id)
    ok = client.post("/v1/compute", headers=headers, json=compute_body())
    assert ok.status_code == 200 and ok.json()["status"] == "ok"


def test_mock_mode_ignores_evidence_and_serves_synthetic(tmp_path: Path) -> None:
    state = ServiceState(mode="mock", credential=CRED, port=PORT, backends=mock_backends())
    client = TestClient(create_app(state), base_url=f"http://127.0.0.1:{PORT}")
    headers = {"Authorization": f"Bearer {CRED}", "Content-Type": "application/json"}
    ok = client.post("/v1/compute", headers=headers, json=compute_body())
    assert ok.status_code == 200
    ready = client.get("/v1/readiness", headers=headers).json()
    assert ready["ready_for_private_values"] is False
