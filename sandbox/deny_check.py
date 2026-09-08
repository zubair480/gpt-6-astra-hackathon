#!/usr/bin/env python3
"""Empirical outbound-denial probe. Runs INSIDE the isolation boundary. Stdlib only.

Each probe tries one egress path and records a sanitized result: a fixed probe name, the
exception class, the errno name, a fixed detail code, and the duration. No hostnames,
addresses, exception messages, or environment values are written to the evidence file.
The probe targets are constants of this script (documented in docs/SECURITY.md).

A failed request is not evidence by itself. ``classify`` maps each raw result to one of

* ``denied``        the failure matches the enforcement mechanism of ``--backend``
* ``succeeded``     the destination was reached (egress is open)
* ``inconclusive``  timeout, TLS error, resolver ambiguity, unexpected errno, ...

``--negative-control`` runs the same probes in a disposable, unrestricted environment and
expects every probe to SUCCEED, which proves the probes themselves are valid. A
negative-control evidence file can never be accepted by ``verify_isolation.py``.

Exit status: 0 every probe matched the expected outcome; 2 at least one probe was
inconclusive; 3 at least one probe produced the opposite of the expected outcome.
"""

from __future__ import annotations

import argparse
import errno as errno_module
import hashlib
import json
import os
import platform
import re
import secrets
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

EVIDENCE_VERSION: Final = 1
EVIDENCE_KIND: Final = "deny-check"
IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Fixed probe targets. They are the only remote names this script knows; they never appear
# in the evidence file, only the probe names below do.
_HTTPS_URL: Final = "https://example.com/"
_DNS_NAME: Final = "example.com"
_DIRECT_IP: Final = "1.1.1.1"
_DIRECT_HTTPS_IP_URL: Final = "https://1.1.1.1/"
_BOGUS_LOOPBACK_PROXY: Final = "http://127.0.0.1:1"
_PROXY_ENV_NAMES: Final = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)

PROBE_HTTPS: Final = "https_well_known"
PROBE_TCP: Final = "tcp_direct_ip"
PROBE_DNS: Final = "dns_resolve"
PROBE_UDP: Final = "udp_dns_query"
PROBE_PROXY_BOGUS: Final = "proxy_env_bogus_loopback"
PROBE_PROXY_CLEARED: Final = "proxy_env_cleared_direct_ip"
REQUIRED_PROBES: Final = (
    PROBE_HTTPS,
    PROBE_TCP,
    PROBE_DNS,
    PROBE_UDP,
    PROBE_PROXY_BOGUS,
    PROBE_PROXY_CLEARED,
)
_CONNECT_PROBES: Final = frozenset({PROBE_HTTPS, PROBE_TCP, PROBE_PROXY_CLEARED})

OUTCOME_DENIED: Final = "denied"
OUTCOME_SUCCEEDED: Final = "succeeded"
OUTCOME_INCONCLUSIVE: Final = "inconclusive"

KIND_RESPONSE: Final = "response"
KIND_CONNECTED: Final = "connected"
KIND_RESOLVED: Final = "resolved"
KIND_REPLY: Final = "reply"
KIND_ERROR: Final = "error"
KIND_TIMEOUT: Final = "timeout"
_REACHED_KINDS: Final = frozenset({KIND_RESPONSE, KIND_CONNECTED, KIND_RESOLVED, KIND_REPLY})


@dataclass(frozen=True, slots=True)
class Signature:
    """How a given enforcement backend is expected to fail a denied connection."""

    name: str
    # errno names that a policy-denied connect()/sendto() produces
    connect_denied: frozenset[str]
    # errno names that a policy-denied loopback connect produces
    loopback_denied: frozenset[str]
    # a denied connect must fail within this budget; slow failures are ambiguous
    fast_ms: int
    # a blocked resolver fails within this budget; slow gaierror is ambiguous
    dns_fast_ms: int
    # HTTP CONNECT answered with 403 by the runtime's proxy counts as policy denial
    tunnel_403_is_denial: bool
    # ECONNREFUSED on loopback counts as denial (private network namespace, no listener)
    loopback_refused_is_denial: bool
    tested_here: bool


# sandbox-exec (macOS Seatbelt): a denied socket operation returns EPERM immediately, for
# every address family, including loopback ports the profile does not allow. Established
# empirically on this machine (see docs/SECURITY.md).
SIGNATURE_SANDBOX_EXEC: Final = Signature(
    name="sandbox-exec",
    connect_denied=frozenset({"EPERM"}),
    loopback_denied=frozenset({"EPERM"}),
    fast_ms=2000,
    dns_fast_ms=1500,
    tunnel_403_is_denial=False,
    loopback_refused_is_denial=False,
    tested_here=True,
)
# OpenShell (Docker driver): the sandbox process runs in a private network namespace
# (10.200.0.2/24) whose default route is the supervisor's deny-by-default proxy at
# 10.200.0.1:3128, injected via HTTP(S)_PROXY/ALL_PROXY; nftables REJECT rules fence every
# direct path. TESTED 2026-09-08 with openshell 0.0.116 on Colima/Docker (aarch64), policy
# `network_policies: {}`; observed per probe (all within 200 ms):
#   https_well_known            CONNECT via injected proxy -> "Tunnel connection failed: 403"
#   tcp_direct_ip               connect() -> ECONNREFUSED (nft reject with tcp-reset)
#   dns_resolve                 getaddrinfo -> EAI_AGAIN in ~1 ms (resolver 127.0.0.11 has no
#                               listener inside the namespace)
#   udp_dns_query               sendto() -> EPERM (nft reject on UDP)
#   proxy_env_bogus_loopback    ECONNREFUSED (namespaced loopback, nothing on :1)
#   proxy_env_cleared_direct_ip ECONNREFUSED
# Silent drops (timeout) stay inconclusive.
SIGNATURE_OPENSHELL: Final = Signature(
    name="openshell",
    connect_denied=frozenset({"ECONNREFUSED", "ENETUNREACH", "EHOSTUNREACH", "EPERM", "EACCES"}),
    loopback_denied=frozenset({"EPERM", "EACCES"}),
    fast_ms=2000,
    dns_fast_ms=1500,
    tunnel_403_is_denial=True,
    loopback_refused_is_denial=True,
    tested_here=True,
)
# Negative control: no enforcement; nothing is a denial signature.
SIGNATURE_NONE: Final = Signature(
    name="none",
    connect_denied=frozenset(),
    loopback_denied=frozenset(),
    fast_ms=2000,
    dns_fast_ms=1500,
    tunnel_403_is_denial=False,
    loopback_refused_is_denial=False,
    tested_here=True,
)
SIGNATURES: Final = {
    s.name: s for s in (SIGNATURE_SANDBOX_EXEC, SIGNATURE_OPENSHELL, SIGNATURE_NONE)
}


@dataclass(frozen=True, slots=True)
class RawResult:
    """Sanitized outcome of one probe attempt. Only fixed codes, never free text."""

    kind: str
    error_class: str | None = None
    errno_name: str | None = None
    detail: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    name: str
    outcome: str
    reason: str
    kind: str
    error_class: str | None
    errno_name: str | None
    detail: str | None
    duration_ms: int


# --- sanitization -----------------------------------------------------------------

_GAI_NAMES: Final = {
    getattr(socket, n): n
    for n in ("EAI_NONAME", "EAI_NODATA", "EAI_AGAIN", "EAI_FAIL", "EAI_SERVICE", "EAI_SYSTEM")
    if hasattr(socket, n)
}
_TUNNEL_RE: Final = re.compile(r"^Tunnel connection failed: (\d{3})")


def normalize_exception(exc: BaseException) -> RawResult:
    """Reduce an exception to class + errno name + fixed detail code (no message text)."""

    if isinstance(exc, urllib.error.HTTPError):
        return RawResult(KIND_RESPONSE, detail=f"http_{exc.code}")
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, BaseException):
            inner = normalize_exception(reason)
            return RawResult(
                inner.kind, "URLError", inner.errno_name, inner.detail or inner.error_class
            )
        return RawResult(KIND_ERROR, "URLError", None, None)
    if isinstance(exc, TimeoutError):
        return RawResult(KIND_TIMEOUT, type(exc).__name__)
    if isinstance(exc, ssl.SSLError):
        return RawResult(KIND_ERROR, "SSLError", None, "tls_error")
    if isinstance(exc, socket.gaierror):
        code = exc.errno
        name = _GAI_NAMES.get(code) if code is not None else None
        return RawResult(KIND_ERROR, "gaierror", name, "resolver_failure")
    if isinstance(exc, OSError):
        match = _TUNNEL_RE.match(str(exc)) if exc.errno is None else None
        if match:
            return RawResult(KIND_ERROR, "OSError", None, f"tunnel_{match.group(1)}")
        errno_name = errno_module.errorcode.get(exc.errno) if exc.errno is not None else None
        if errno_name == "ETIMEDOUT":
            return RawResult(KIND_TIMEOUT, type(exc).__name__, errno_name)
        return RawResult(KIND_ERROR, type(exc).__name__, errno_name, None)
    return RawResult(KIND_ERROR, type(exc).__name__, None, "unexpected_exception")


# --- classification ---------------------------------------------------------------


def classify(probe: str, raw: RawResult, sig: Signature, *, negative_control: bool) -> Verdict:
    """Map a raw probe result to denied / succeeded / inconclusive plus a fixed reason."""

    if raw.kind in _REACHED_KINDS:
        if probe == PROBE_PROXY_BOGUS:
            # A response through a proxy on 127.0.0.1:1 means either urllib ignored the
            # env (probe invalid) or something on loopback forwarded us out (egress open).
            if negative_control:
                return Verdict(OUTCOME_INCONCLUSIVE, "PROXY_ENV_NOT_HONORED")
            return Verdict(OUTCOME_SUCCEEDED, "LOOPBACK_PROXY_FORWARDED_EGRESS")
        return Verdict(OUTCOME_SUCCEEDED, "REACHED_DESTINATION")

    if raw.kind == KIND_TIMEOUT:
        return Verdict(OUTCOME_INCONCLUSIVE, "TIMEOUT_DEAD_OR_UNAVAILABLE")

    if raw.error_class == "URLError" and raw.detail == "URLError":
        return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_ERROR")

    if raw.detail == "tls_error" or raw.error_class == "SSLError":
        return Verdict(OUTCOME_INCONCLUSIVE, "TLS_ERROR")

    if raw.detail == "resolver_failure":
        # A blocked resolver fails immediately; a dead upstream resolver fails after its
        # own retry budget. Fast failure is the weaker of our signatures because an
        # offline host also fails fast, which is why the launcher corroborates it with a
        # same-host negative control (see verify_isolation.py --negative-control).
        if raw.duration_ms <= sig.dns_fast_ms and sig.name != "none":
            return Verdict(OUTCOME_DENIED, "RESOLVER_BLOCKED_FAST_FAIL")
        return Verdict(OUTCOME_INCONCLUSIVE, "RESOLVER_FAILURE_AMBIGUOUS")

    if raw.detail and raw.detail.startswith("tunnel_"):
        if raw.detail == "tunnel_403" and sig.tunnel_403_is_denial:
            return Verdict(OUTCOME_DENIED, "L7_PROXY_403")
        return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_PROXY_RESPONSE")

    errno_name = raw.errno_name
    if errno_name is None:
        return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_ERROR")

    if probe == PROBE_PROXY_BOGUS:
        if errno_name in sig.loopback_denied:
            return Verdict(OUTCOME_DENIED, "LOOPBACK_OUTBOUND_DENIED")
        if errno_name == "ECONNREFUSED":
            if negative_control:
                # urllib went to the bogus proxy instead of the destination: env honored.
                return Verdict(OUTCOME_SUCCEEDED, "PROXY_ENV_HONORED")
            if sig.loopback_refused_is_denial:
                return Verdict(OUTCOME_DENIED, "LOOPBACK_NAMESPACED_NO_LISTENER")
            return Verdict(OUTCOME_INCONCLUSIVE, "LOOPBACK_REACHABLE_NOT_DENIED")
        return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_ERRNO")

    if probe == PROBE_UDP:
        if errno_name in sig.connect_denied:
            return Verdict(OUTCOME_DENIED, "POLICY_ERRNO")
        return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_ERRNO")

    if probe in _CONNECT_PROBES:
        if errno_name in sig.connect_denied:
            if raw.duration_ms <= sig.fast_ms:
                return Verdict(OUTCOME_DENIED, "POLICY_ERRNO")
            return Verdict(OUTCOME_INCONCLUSIVE, "SLOW_FAILURE_AMBIGUOUS")
        return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_ERRNO")

    return Verdict(OUTCOME_INCONCLUSIVE, "UNEXPECTED_ERRNO")


# --- probes ------------------------------------------------------------------------


def _timed(fn: Callable[[], RawResult]) -> RawResult:
    started = time.monotonic()
    try:
        result = fn()
    except BaseException as exc:  # every failure is data here
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            raise
        result = normalize_exception(exc)
    duration = int((time.monotonic() - started) * 1000)
    return RawResult(result.kind, result.error_class, result.errno_name, result.detail, duration)


def _urlopen(url: str, timeout: float, opener: urllib.request.OpenerDirector) -> RawResult:
    with opener.open(url, timeout=timeout) as response:
        return RawResult(KIND_RESPONSE, detail=f"http_{response.status}")


def probe_https(timeout: float) -> RawResult:
    # Uses whatever proxy env the runtime injected (OpenShell) or nothing (sandbox-exec).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler())
    return _timed(lambda: _urlopen(_HTTPS_URL, timeout, opener))


def probe_tcp(timeout: float) -> RawResult:
    def run() -> RawResult:
        with socket.create_connection((_DIRECT_IP, 443), timeout=timeout):
            return RawResult(KIND_CONNECTED)

    return _timed(run)


def probe_dns(timeout: float) -> RawResult:
    del timeout  # getaddrinfo has no per-call timeout; the resolver's own applies

    def run() -> RawResult:
        socket.getaddrinfo(_DNS_NAME, 443, type=socket.SOCK_STREAM)
        return RawResult(KIND_RESOLVED)

    return _timed(run)


def _dns_query(name: str) -> tuple[int, bytes]:
    txn = secrets.randbelow(65536)
    header = struct.pack(">HHHHHH", txn, 0x0100, 1, 0, 0, 0)
    question = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return txn, header + question + struct.pack(">HH", 1, 1)


def probe_udp(timeout: float) -> RawResult:
    def run() -> RawResult:
        txn, packet = _dns_query(_DNS_NAME)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.connect((_DIRECT_IP, 53))  # route lookup: ENETUNREACH / EPERM here
            sock.send(packet)
            try:
                reply = sock.recv(512)
            except TimeoutError:
                return RawResult(KIND_TIMEOUT, "TimeoutError", None, "sent_no_reply")
        if len(reply) >= 12 and struct.unpack(">H", reply[:2])[0] == txn and reply[2] & 0x80:
            return RawResult(KIND_REPLY, detail="dns_reply")
        return RawResult(KIND_ERROR, "ValueError", None, "malformed_reply")

    return _timed(run)


def _with_proxy_env(values: dict[str, str], fn: Callable[[], RawResult]) -> RawResult:
    saved = {name: os.environ.pop(name) for name in _PROXY_ENV_NAMES if name in os.environ}
    os.environ.update(values)
    try:
        return fn()
    finally:
        for name in values:
            os.environ.pop(name, None)
        os.environ.update(saved)


def probe_proxy_bogus(timeout: float) -> RawResult:
    values = {
        name: _BOGUS_LOOPBACK_PROXY
        for name in _PROXY_ENV_NAMES
        if not name.lower().startswith("no_proxy")
    }

    def run() -> RawResult:
        # ProxyHandler() with no argument reads the proxy env at construction time.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler())
        return _urlopen(_HTTPS_URL, timeout, opener)

    return _with_proxy_env(values, lambda: _timed(run))


def probe_proxy_cleared(timeout: float) -> RawResult:
    def run() -> RawResult:
        # No proxy env, explicit empty proxy map, IP-literal target: no resolver involved.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return _urlopen(_DIRECT_HTTPS_IP_URL, timeout, opener)

    return _with_proxy_env({}, lambda: _timed(run))


PROBES: Final[dict[str, Callable[[float], RawResult]]] = {
    PROBE_HTTPS: probe_https,
    PROBE_TCP: probe_tcp,
    PROBE_DNS: probe_dns,
    PROBE_UDP: probe_udp,
    PROBE_PROXY_BOGUS: probe_proxy_bogus,
    PROBE_PROXY_CLEARED: probe_proxy_cleared,
}


# --- evidence ----------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_probes(
    sig: Signature,
    *,
    negative_control: bool,
    timeout: float,
    names: Iterable[str] = REQUIRED_PROBES,
) -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    for name in names:
        raw = PROBES[name](timeout)
        verdict = classify(name, raw, sig, negative_control=negative_control)
        records.append(
            ProbeRecord(
                name=name,
                outcome=verdict.outcome,
                reason=verdict.reason,
                kind=raw.kind,
                error_class=raw.error_class,
                errno_name=raw.errno_name,
                detail=raw.detail,
                duration_ms=raw.duration_ms,
            )
        )
    return records


def build_evidence(
    records: list[ProbeRecord],
    *,
    backend: str,
    negative_control: bool,
    instance_id: str,
    policy_sha256: str,
    policy_name: str,
    timeout: float,
    proxy_env_present: list[str],
    now: datetime | None = None,
) -> dict[str, object]:
    expected = OUTCOME_SUCCEEDED if negative_control else OUTCOME_DENIED
    counts = {
        OUTCOME_DENIED: 0,
        OUTCOME_SUCCEEDED: 0,
        OUTCOME_INCONCLUSIVE: 0,
    }
    for record in records:
        counts[record.outcome] += 1
    return {
        "evidence_version": EVIDENCE_VERSION,
        "kind": EVIDENCE_KIND,
        "negative_control": negative_control,
        "backend": backend,
        "backend_signature_tested_here": SIGNATURES[backend].tested_here,
        "instance_id": instance_id,
        "policy_sha256": policy_sha256,
        "policy_name": policy_name,
        "timestamp": (now or datetime.now(UTC)).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "timeout_seconds": timeout,
        "proxy_env_present_at_start": sorted(proxy_env_present),
        "probes": [asdict(record) for record in records],
        "summary": {
            "expected_outcome": expected,
            **counts,
            "all_expected": all(record.outcome == expected for record in records),
        },
    }


def exit_code_for(records: Iterable[ProbeRecord], *, negative_control: bool) -> int:
    expected = OUTCOME_SUCCEEDED if negative_control else OUTCOME_DENIED
    outcomes = [record.outcome for record in records]
    if not outcomes:
        return 2
    if any(o not in (expected, OUTCOME_INCONCLUSIVE) for o in outcomes):
        return 3
    if any(o == OUTCOME_INCONCLUSIVE for o in outcomes):
        return 2
    return 0


def write_evidence(payload: dict[str, object], output: str) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output == "-":
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--backend",
        choices=sorted(SIGNATURES),
        help="enforcement mechanism whose denial signature is expected (required unless "
        "--negative-control)",
    )
    parser.add_argument("--instance-id", help="running service instance_id (from /v1/readiness)")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--policy", type=Path, help="effective policy file to hash")
    policy.add_argument("--policy-sha256", help="precomputed sha256 of the effective policy")
    parser.add_argument("--policy-name", help="fixed label for the policy (default: file name)")
    parser.add_argument("--output", default="-", help="evidence path, or - for stdout")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--negative-control",
        action="store_true",
        help="expect every probe to SUCCEED (disposable unrestricted environment only)",
    )
    args = parser.parse_args(argv)

    negative = bool(args.negative_control)
    backend = args.backend or ("none" if negative else None)
    if backend is None:
        parser.error("--backend is required unless --negative-control is given")
    if negative and backend != "none":
        parser.error("--negative-control implies --backend none")

    instance_id = args.instance_id or ("negative-control" if negative else None)
    if instance_id is None:
        parser.error("--instance-id is required unless --negative-control is given")
    if not IDENTIFIER_RE.match(instance_id):
        parser.error("--instance-id must match [A-Za-z0-9._-]{1,64}")

    if args.policy is not None:
        policy_sha = sha256_file(args.policy)
        policy_name = args.policy_name or args.policy.name
    elif args.policy_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", args.policy_sha256):
            parser.error("--policy-sha256 must be 64 lowercase hex characters")
        policy_sha = args.policy_sha256
        policy_name = args.policy_name or "unnamed"
    elif negative:
        policy_sha = "0" * 64
        policy_name = "none"
    else:
        parser.error("--policy or --policy-sha256 is required unless --negative-control")

    proxy_env_present = [name for name in _PROXY_ENV_NAMES if name in os.environ]
    records = run_probes(SIGNATURES[backend], negative_control=negative, timeout=args.timeout)
    payload = build_evidence(
        records,
        backend=backend,
        negative_control=negative,
        instance_id=instance_id,
        policy_sha256=policy_sha,
        policy_name=policy_name,
        timeout=args.timeout,
        proxy_env_present=proxy_env_present,
    )
    write_evidence(payload, args.output)
    code = exit_code_for(records, negative_control=negative)
    if args.output != "-":
        expected = payload["summary"]["expected_outcome"]  # type: ignore[index]
        for record in records:
            flag = "ok " if record.outcome == expected else "!! "
            print(f"[deny-check] {flag}{record.name}: {record.outcome} ({record.reason})")
        print(f"[deny-check] exit={code} evidence={args.output}")
    return code


if __name__ == "__main__":
    sys.exit(main())
