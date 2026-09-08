"""Unit tests for sandbox/verify_isolation.py decisions over synthetic evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "sandbox" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vi = _load("verify_isolation")

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
POLICY_SHA = "b" * 64
INSTANCE = "inst-abc"


def probe(name: str, outcome: str = "denied") -> dict[str, Any]:
    return {
        "name": name,
        "outcome": outcome,
        "reason": "POLICY_ERRNO",
        "kind": "error",
        "error_class": "PermissionError",
        "errno_name": "EPERM",
        "detail": None,
        "duration_ms": 2,
    }


def good_evidence(age_seconds: int = 30) -> dict[str, Any]:
    return {
        "evidence_version": 1,
        "kind": "deny-check",
        "negative_control": False,
        "backend": "sandbox-exec",
        "backend_signature_tested_here": True,
        "instance_id": INSTANCE,
        "policy_sha256": POLICY_SHA,
        "policy_name": "macos-dev.sb",
        "timestamp": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "platform": {"system": "Darwin", "release": "25.4.0", "machine": "arm64", "python": "3.12"},
        "timeout_seconds": 5.0,
        "proxy_env_present_at_start": [],
        "probes": [probe(n) for n in sorted(vi.REQUIRED_PROBES)],
        "summary": {
            "expected_outcome": "denied",
            "denied": 6,
            "succeeded": 0,
            "inconclusive": 0,
            "all_expected": True,
        },
    }


def good_control(age_seconds: int = 60) -> dict[str, Any]:
    control = good_evidence(age_seconds)
    control["negative_control"] = True
    control["backend"] = "none"
    control["instance_id"] = "negative-control"
    control["policy_sha256"] = "0" * 64
    control["probes"] = [probe(n, "succeeded") for n in sorted(vi.REQUIRED_PROBES)]
    control["summary"] = {
        "expected_outcome": "succeeded",
        "denied": 0,
        "succeeded": 6,
        "inconclusive": 0,
        "all_expected": True,
    }
    return control


def decide(evidence: Any, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {"policy_sha256": POLICY_SHA, "instance_id": INSTANCE, "now": NOW}
    kwargs.update(overrides)
    return vi.decide(evidence, **kwargs)


def test_fresh_all_denied_evidence_is_verified() -> None:
    d = decide(good_evidence())
    assert d.isolation == "verified"
    assert d.reasons == ("ALL_PROBES_DENIED",)
    assert d.backend == "sandbox-exec"


def test_stale_evidence_fails() -> None:
    d = decide(good_evidence(age_seconds=vi.DEFAULT_MAX_AGE_SECONDS + 1))
    assert d.isolation == "failed"
    assert "EVIDENCE_STALE" in d.reasons


def test_future_timestamp_fails() -> None:
    d = decide(good_evidence(age_seconds=-600))
    assert "TIMESTAMP_IN_FUTURE" in d.reasons


def test_naive_or_garbage_timestamp_fails() -> None:
    e = good_evidence()
    e["timestamp"] = "2026-09-08T12:00:00"  # no tz
    assert "TIMESTAMP_INVALID" in decide(e).reasons
    e["timestamp"] = "yesterday"
    assert "TIMESTAMP_INVALID" in decide(e).reasons


def test_mismatched_instance_fails() -> None:
    d = decide(good_evidence(), instance_id="inst-other")
    assert d.isolation == "failed"
    assert "INSTANCE_ID_MISMATCH" in d.reasons


def test_mismatched_policy_hash_fails() -> None:
    d = decide(good_evidence(), policy_sha256="c" * 64)
    assert "POLICY_SHA256_MISMATCH" in d.reasons
    assert "POLICY_SHA256_INVALID" in decide(good_evidence(), policy_sha256="nothex").reasons


def test_inconclusive_probe_fails() -> None:
    e = good_evidence()
    e["probes"][2]["outcome"] = "inconclusive"
    d = decide(e)
    assert d.isolation == "failed"
    assert any(r.startswith("PROBE_INCONCLUSIVE:") for r in d.reasons)


def test_succeeded_probe_fails_as_egress_observed() -> None:
    e = good_evidence()
    e["probes"][0]["outcome"] = "succeeded"
    d = decide(e)
    assert any(r.startswith("EGRESS_OBSERVED:") for r in d.reasons)


def test_summary_flag_alone_cannot_verify() -> None:
    e = good_evidence()
    e["probes"][0]["outcome"] = "succeeded"  # summary still claims all_expected
    assert decide(e).isolation == "failed"


def test_missing_or_duplicated_probe_fails() -> None:
    e = good_evidence()
    e["probes"].pop()
    assert "REQUIRED_PROBE_MISSING" in decide(e).reasons
    e = good_evidence()
    e["probes"].append(copy.deepcopy(e["probes"][0]))
    assert "PROBE_DUPLICATED" in decide(e).reasons
    e = good_evidence()
    e["probes"] = []
    assert "PROBES_MISSING" in decide(e).reasons


def test_negative_control_evidence_is_never_verified() -> None:
    e = good_evidence()
    e["negative_control"] = True
    assert "NEGATIVE_CONTROL_NOT_ACCEPTABLE" in decide(e).reasons


def test_unknown_backend_or_mismatch_fails() -> None:
    e = good_evidence()
    e["backend"] = "docker"
    assert "BACKEND_UNKNOWN" in decide(e).reasons
    assert "BACKEND_MISMATCH" in decide(good_evidence(), expected_backend="openshell").reasons


def test_wrong_kind_or_version_fails() -> None:
    e = good_evidence()
    e["evidence_version"] = 2
    e["kind"] = "something"
    r = decide(e).reasons
    assert "EVIDENCE_VERSION_UNSUPPORTED" in r
    assert "EVIDENCE_KIND_UNEXPECTED" in r


def test_non_object_evidence_fails() -> None:
    assert decide([]).reasons == ("EVIDENCE_NOT_OBJECT",)
    assert decide(None).isolation == "failed"


def test_negative_control_corroboration() -> None:
    assert decide(good_evidence(), negative_control=good_control()).isolation == "verified"
    stale = good_control(age_seconds=vi.DEFAULT_MAX_AGE_SECONDS + 5)
    assert "NEGATIVE_CONTROL_STALE" in decide(good_evidence(), negative_control=stale).reasons
    failed = good_control()
    failed["summary"]["all_expected"] = False
    assert (
        "NEGATIVE_CONTROL_NOT_ALL_SUCCEEDED"
        in decide(good_evidence(), negative_control=failed).reasons
    )
    not_marked = good_control()
    not_marked["negative_control"] = False
    assert (
        "NEGATIVE_CONTROL_NOT_MARKED"
        in decide(good_evidence(), negative_control=not_marked).reasons
    )
    other_platform = good_control()
    other_platform["platform"]["machine"] = "x86_64"
    assert (
        "NEGATIVE_CONTROL_PLATFORM_MISMATCH"
        in decide(good_evidence(), negative_control=other_platform).reasons
    )
    assert "NEGATIVE_CONTROL_UNREADABLE" in decide(good_evidence(), negative_control=None).reasons


def test_result_document_shape() -> None:
    ok = vi.result_document(
        decide(good_evidence()), instance_id=INSTANCE, policy_sha256=POLICY_SHA, now=NOW
    )
    assert ok["isolation"] == "verified"
    assert ok["verified_at"] == NOW.isoformat()
    assert ok["instance_id"] == INSTANCE
    assert ok["policy_sha256"] == POLICY_SHA
    bad = vi.result_document(
        decide(good_evidence(), instance_id="x"), instance_id="x", policy_sha256=POLICY_SHA, now=NOW
    )
    assert bad["isolation"] == "failed"
    assert bad["verified_at"] is None


def test_cli_end_to_end_with_files(tmp_path: Path) -> None:
    policy = tmp_path / "policy.sb"
    policy.write_bytes(b"(version 1)\n(deny network*)\n")
    sha = vi.sha256_file(policy)
    now = datetime.now(UTC)
    evidence = good_evidence()
    evidence["policy_sha256"] = sha
    evidence["timestamp"] = now.isoformat()
    ev_path = tmp_path / "deny-check.json"
    ev_path.write_text(json.dumps(evidence))
    out = tmp_path / "isolation-evidence.json"
    rc = vi.main(
        [
            "--evidence",
            str(ev_path),
            "--policy",
            str(policy),
            "--output",
            str(out),
            "--instance-id",
            INSTANCE,
            "--expected-backend",
            "sandbox-exec",
        ]
    )
    assert rc == 0
    doc = json.loads(out.read_text())
    assert doc["isolation"] == "verified"
    assert (out.stat().st_mode & 0o777) == 0o600

    # Same evidence, different running instance -> failed, exit 1.
    rc = vi.main(
        [
            "--evidence",
            str(ev_path),
            "--policy",
            str(policy),
            "--output",
            str(out),
            "--instance-id",
            "other",
        ]
    )
    assert rc == 1
    assert json.loads(out.read_text())["isolation"] == "failed"

    # Unreachable readiness endpoint -> failed, never verified.
    rc = vi.main(
        [
            "--evidence",
            str(ev_path),
            "--policy",
            str(policy),
            "--output",
            str(out),
            "--readiness-url",
            "http://127.0.0.1:9/v1/readiness",
            "--credential-file",
            str(tmp_path / "missing"),
            "--timeout",
            "1",
        ]
    )
    assert rc == 1
    assert "READINESS_UNREACHABLE" in json.loads(out.read_text())["reasons"]


@pytest.mark.parametrize("field", ["instance_id", "policy_sha256", "probes", "summary"])
def test_removing_required_field_fails(field: str) -> None:
    e = good_evidence()
    del e[field]
    assert decide(e).isolation == "failed"
