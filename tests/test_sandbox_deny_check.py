"""Unit tests for sandbox/deny_check.py classification and evidence sanitization."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "sandbox" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dc = _load("deny_check")

SBX = dc.SIGNATURE_SANDBOX_EXEC
OSH = dc.SIGNATURE_OPENSHELL
NONE = dc.SIGNATURE_NONE


def raw(kind: str, cls: str | None = None, errno_name: str | None = None, detail=None, ms=5):
    return dc.RawResult(kind, cls, errno_name, detail, ms)


# --- sandbox-exec signature -----------------------------------------------------------


@pytest.mark.parametrize("probe", [dc.PROBE_TCP, dc.PROBE_HTTPS, dc.PROBE_PROXY_CLEARED])
def test_sandbox_exec_eperm_fast_is_denied(probe: str) -> None:
    v = dc.classify(probe, raw("error", "PermissionError", "EPERM"), SBX, negative_control=False)
    assert (v.outcome, v.reason) == ("denied", "POLICY_ERRNO")


def test_sandbox_exec_eperm_slow_is_inconclusive() -> None:
    v = dc.classify(
        dc.PROBE_TCP, raw("error", "PermissionError", "EPERM", ms=9000), SBX, negative_control=False
    )
    assert (v.outcome, v.reason) == ("inconclusive", "SLOW_FAILURE_AMBIGUOUS")


def test_sandbox_exec_refused_is_not_denial() -> None:
    v = dc.classify(
        dc.PROBE_TCP,
        raw("error", "ConnectionRefusedError", "ECONNREFUSED"),
        SBX,
        negative_control=False,
    )
    assert (v.outcome, v.reason) == ("inconclusive", "UNEXPECTED_ERRNO")


def test_timeout_is_inconclusive_everywhere() -> None:
    for sig in (SBX, OSH):
        v = dc.classify(dc.PROBE_TCP, raw("timeout", "TimeoutError"), sig, negative_control=False)
        assert (v.outcome, v.reason) == ("inconclusive", "TIMEOUT_DEAD_OR_UNAVAILABLE")


def test_tls_error_is_inconclusive() -> None:
    v = dc.classify(
        dc.PROBE_HTTPS, raw("error", "SSLError", None, "tls_error"), SBX, negative_control=False
    )
    assert (v.outcome, v.reason) == ("inconclusive", "TLS_ERROR")


def test_http_response_means_egress_open() -> None:
    v = dc.classify(dc.PROBE_HTTPS, raw("response", detail="http_200"), SBX, negative_control=False)
    assert (v.outcome, v.reason) == ("succeeded", "REACHED_DESTINATION")


def test_resolver_fast_fail_is_denied_and_slow_is_ambiguous() -> None:
    fast = raw("error", "gaierror", "EAI_NONAME", "resolver_failure", ms=1)
    slow = raw("error", "gaierror", "EAI_AGAIN", "resolver_failure", ms=8000)
    assert dc.classify(dc.PROBE_DNS, fast, SBX, negative_control=False).outcome == "denied"
    assert dc.classify(dc.PROBE_HTTPS, fast, SBX, negative_control=False).outcome == "denied"
    v = dc.classify(dc.PROBE_DNS, slow, SBX, negative_control=False)
    assert (v.outcome, v.reason) == ("inconclusive", "RESOLVER_FAILURE_AMBIGUOUS")


def test_resolver_failure_never_denied_without_enforcement() -> None:
    fast = raw("error", "gaierror", "EAI_NONAME", "resolver_failure", ms=1)
    assert dc.classify(dc.PROBE_DNS, fast, NONE, negative_control=True).outcome == "inconclusive"


def test_udp_eperm_denied_and_silent_drop_inconclusive() -> None:
    assert (
        dc.classify(
            dc.PROBE_UDP, raw("error", "PermissionError", "EPERM"), SBX, negative_control=False
        ).outcome
        == "denied"
    )
    v = dc.classify(
        dc.PROBE_UDP,
        raw("timeout", "TimeoutError", None, "sent_no_reply"),
        OSH,
        negative_control=False,
    )
    assert v.outcome == "inconclusive"


def test_bogus_proxy_probe_under_sandbox_exec() -> None:
    denied = dc.classify(
        dc.PROBE_PROXY_BOGUS,
        raw("error", "URLError", "EPERM", "PermissionError"),
        SBX,
        negative_control=False,
    )
    assert (denied.outcome, denied.reason) == ("denied", "LOOPBACK_OUTBOUND_DENIED")
    refused = dc.classify(
        dc.PROBE_PROXY_BOGUS, raw("error", "URLError", "ECONNREFUSED"), SBX, negative_control=False
    )
    assert (refused.outcome, refused.reason) == ("inconclusive", "LOOPBACK_REACHABLE_NOT_DENIED")
    forwarded = dc.classify(
        dc.PROBE_PROXY_BOGUS, raw("response", detail="http_200"), SBX, negative_control=False
    )
    assert (forwarded.outcome, forwarded.reason) == ("succeeded", "LOOPBACK_PROXY_FORWARDED_EGRESS")


# --- openshell signature (documented, untested here) -----------------------------------


def test_openshell_tunnel_403_is_denied_but_not_for_sandbox_exec() -> None:
    r = raw("error", "URLError", None, "tunnel_403")
    assert dc.classify(dc.PROBE_HTTPS, r, OSH, negative_control=False).reason == "L7_PROXY_403"
    assert dc.classify(dc.PROBE_HTTPS, r, SBX, negative_control=False).outcome == "inconclusive"
    other = raw("error", "URLError", None, "tunnel_502")
    assert dc.classify(dc.PROBE_HTTPS, other, OSH, negative_control=False).outcome == "inconclusive"


@pytest.mark.parametrize("errno_name", ["ENETUNREACH", "EHOSTUNREACH", "ECONNREFUSED", "EPERM"])
def test_openshell_no_route_errnos_are_denied(errno_name: str) -> None:
    v = dc.classify(dc.PROBE_TCP, raw("error", "OSError", errno_name), OSH, negative_control=False)
    assert v.outcome == "denied"


def test_openshell_loopback_refused_counts_as_namespaced() -> None:
    v = dc.classify(
        dc.PROBE_PROXY_BOGUS, raw("error", "URLError", "ECONNREFUSED"), OSH, negative_control=False
    )
    assert (v.outcome, v.reason) == ("denied", "LOOPBACK_NAMESPACED_NO_LISTENER")


# --- negative control semantics ----------------------------------------------------------


def test_negative_control_proxy_probe() -> None:
    honored = dc.classify(
        dc.PROBE_PROXY_BOGUS, raw("error", "URLError", "ECONNREFUSED"), NONE, negative_control=True
    )
    assert (honored.outcome, honored.reason) == ("succeeded", "PROXY_ENV_HONORED")
    ignored = dc.classify(
        dc.PROBE_PROXY_BOGUS, raw("response", detail="http_200"), NONE, negative_control=True
    )
    assert (ignored.outcome, ignored.reason) == ("inconclusive", "PROXY_ENV_NOT_HONORED")


def test_exit_codes() -> None:
    def rec(outcome: str):
        return dc.ProbeRecord("p", outcome, "R", "error", None, None, None, 1)

    assert dc.exit_code_for([rec("denied")], negative_control=False) == 0
    assert dc.exit_code_for([rec("denied"), rec("inconclusive")], negative_control=False) == 2
    assert dc.exit_code_for([rec("denied"), rec("succeeded")], negative_control=False) == 3
    assert dc.exit_code_for([rec("succeeded")], negative_control=True) == 0
    assert dc.exit_code_for([rec("denied")], negative_control=True) == 3
    assert dc.exit_code_for([], negative_control=False) == 2


# --- normalization and sanitization ------------------------------------------------------


def test_normalize_tunnel_error_keeps_only_code() -> None:
    r = dc.normalize_exception(
        OSError("Tunnel connection failed: 403 Forbidden by policy at proxy.example")
    )
    assert (r.kind, r.error_class, r.errno_name, r.detail) == (
        "error",
        "OSError",
        None,
        "tunnel_403",
    )


def test_normalize_oserror_uses_errno_name() -> None:
    import errno

    r = dc.normalize_exception(OSError(errno.EPERM, "Operation not permitted"))
    assert (r.error_class, r.errno_name) == ("PermissionError", "EPERM")
    t = dc.normalize_exception(OSError(errno.ETIMEDOUT, "timed out"))
    assert t.kind == "timeout"


def test_evidence_contains_no_targets_or_messages() -> None:
    records = dc.run_probes.__globals__["ProbeRecord"]
    recs = [
        records(name, "denied", "POLICY_ERRNO", "error", "PermissionError", "EPERM", None, 3)
        for name in dc.REQUIRED_PROBES
    ]
    payload = dc.build_evidence(
        recs,
        backend="sandbox-exec",
        negative_control=False,
        instance_id="inst-1",
        policy_sha256="a" * 64,
        policy_name="macos-dev.sb",
        timeout=5.0,
        proxy_env_present=["HTTPS_PROXY"],
        now=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
    )
    text = json.dumps(payload)
    for forbidden in ("example.com", "1.1.1.1", "127.0.0.1", "Operation not permitted", "http://"):
        assert forbidden not in text
    assert payload["summary"] == {
        "expected_outcome": "denied",
        "denied": 6,
        "succeeded": 0,
        "inconclusive": 0,
        "all_expected": True,
    }
    assert payload["instance_id"] == "inst-1"
    assert payload["timestamp"] == "2026-09-08T12:00:00+00:00"
    assert payload["proxy_env_present_at_start"] == ["HTTPS_PROXY"]
