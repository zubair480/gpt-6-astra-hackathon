#!/usr/bin/env python3
"""Turn deny-check evidence into an isolation decision the service can consume. Stdlib only.

Runs on the HOST (outside the boundary). It re-hashes the effective policy file, fetches
``/v1/readiness`` from the running service to learn its ``instance_id``, and checks that the
evidence written by ``deny_check.py`` inside the boundary is fresh, bound to that instance and
that policy, not a negative control, and that every required probe reports ``denied``.

Output ``isolation-evidence.json``::

    {"isolation": "verified" | "failed", "verified_at": iso8601 | null,
     "instance_id": ..., "policy_sha256": ..., "checked_at": iso8601, "reasons": [...]}

Anything stale, mismatched, inconclusive, or unreadable is ``failed``. Exit 0 only on
``verified``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

EVIDENCE_VERSION: Final = 1
EVIDENCE_KIND: Final = "deny-check"
REQUIRED_PROBES: Final = frozenset(
    {
        "https_well_known",
        "tcp_direct_ip",
        "dns_resolve",
        "udp_dns_query",
        "proxy_env_bogus_loopback",
        "proxy_env_cleared_direct_ip",
    }
)
KNOWN_BACKENDS: Final = frozenset({"sandbox-exec", "openshell"})
DEFAULT_MAX_AGE_SECONDS: Final = 900
CLOCK_SKEW_SECONDS: Final = 60
IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Decision:
    isolation: str  # "verified" | "failed"
    reasons: tuple[str, ...]
    backend: str | None = None

    @property
    def verified(self) -> bool:
        return self.isolation == "verified"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


_NO_NEGATIVE_CONTROL: Final = object()


def _check_negative_control(
    control: object, evidence: dict[str, Any], now: datetime, max_age_seconds: int
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(control, dict):
        return ["NEGATIVE_CONTROL_UNREADABLE"]
    if control.get("kind") != EVIDENCE_KIND or control.get("evidence_version") != EVIDENCE_VERSION:
        reasons.append("NEGATIVE_CONTROL_KIND_UNEXPECTED")
    if control.get("negative_control") is not True:
        reasons.append("NEGATIVE_CONTROL_NOT_MARKED")
    stamp = _parse_timestamp(control.get("timestamp"))
    if stamp is None or now - stamp > timedelta(seconds=max_age_seconds):
        reasons.append("NEGATIVE_CONTROL_STALE")
    summary = control.get("summary")
    if not isinstance(summary, dict) or summary.get("all_expected") is not True:
        reasons.append("NEGATIVE_CONTROL_NOT_ALL_SUCCEEDED")
    probes = control.get("probes")
    names = (
        {p.get("name") for p in probes if isinstance(p, dict)}
        if isinstance(probes, list)
        else set()
    )
    if not names >= REQUIRED_PROBES:
        reasons.append("NEGATIVE_CONTROL_PROBE_MISSING")
    a, b = control.get("platform"), evidence.get("platform")
    if not (isinstance(a, dict) and isinstance(b, dict)) or any(
        a.get(k) != b.get(k) for k in ("system", "machine")
    ):
        reasons.append("NEGATIVE_CONTROL_PLATFORM_MISMATCH")
    return reasons


def decide(
    evidence: object,
    *,
    policy_sha256: str,
    instance_id: str,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    expected_backend: str | None = None,
    negative_control: object = _NO_NEGATIVE_CONTROL,
) -> Decision:
    """Pure decision over a parsed evidence document. Every failure is a fixed reason code.

    ``negative_control`` is an optional second evidence document produced by
    ``deny_check.py --negative-control`` on the same host shortly before. It corroborates
    the resolver-based denials (a fast resolver failure alone cannot distinguish a blocked
    resolver from an offline host). When supplied it must be a fresh, all-succeeded
    negative control from the same platform; otherwise the decision is ``failed``.
    """

    reasons: list[str] = []
    if not isinstance(evidence, dict):
        return Decision("failed", ("EVIDENCE_NOT_OBJECT",))
    if negative_control is not _NO_NEGATIVE_CONTROL:
        reasons.extend(_check_negative_control(negative_control, evidence, now, max_age_seconds))

    if evidence.get("evidence_version") != EVIDENCE_VERSION:
        reasons.append("EVIDENCE_VERSION_UNSUPPORTED")
    if evidence.get("kind") != EVIDENCE_KIND:
        reasons.append("EVIDENCE_KIND_UNEXPECTED")
    if evidence.get("negative_control") is not False:
        reasons.append("NEGATIVE_CONTROL_NOT_ACCEPTABLE")

    backend = evidence.get("backend")
    if backend not in KNOWN_BACKENDS:
        reasons.append("BACKEND_UNKNOWN")
        backend = None
    elif expected_backend is not None and backend != expected_backend:
        reasons.append("BACKEND_MISMATCH")

    if not SHA256_RE.match(policy_sha256):
        reasons.append("POLICY_SHA256_INVALID")
    if evidence.get("policy_sha256") != policy_sha256:
        reasons.append("POLICY_SHA256_MISMATCH")

    if not IDENTIFIER_RE.match(instance_id):
        reasons.append("INSTANCE_ID_INVALID")
    if evidence.get("instance_id") != instance_id:
        reasons.append("INSTANCE_ID_MISMATCH")

    stamp = _parse_timestamp(evidence.get("timestamp"))
    if stamp is None:
        reasons.append("TIMESTAMP_INVALID")
    else:
        if stamp > now + timedelta(seconds=CLOCK_SKEW_SECONDS):
            reasons.append("TIMESTAMP_IN_FUTURE")
        if now - stamp > timedelta(seconds=max_age_seconds):
            reasons.append("EVIDENCE_STALE")

    probes = evidence.get("probes")
    if not isinstance(probes, list) or not probes:
        reasons.append("PROBES_MISSING")
    else:
        seen: dict[str, str] = {}
        for entry in probes:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                reasons.append("PROBE_ENTRY_MALFORMED")
                continue
            name = entry["name"]
            if name in seen:
                reasons.append("PROBE_DUPLICATED")
            seen[name] = str(entry.get("outcome"))
        missing = REQUIRED_PROBES - seen.keys()
        if missing:
            reasons.append("REQUIRED_PROBE_MISSING")
        for name in sorted(REQUIRED_PROBES & seen.keys()):
            outcome = seen[name]
            if outcome == "inconclusive":
                reasons.append(f"PROBE_INCONCLUSIVE:{name}")
            elif outcome == "succeeded":
                reasons.append(f"EGRESS_OBSERVED:{name}")
            elif outcome != "denied":
                reasons.append(f"PROBE_OUTCOME_UNKNOWN:{name}")

    summary = evidence.get("summary")
    if not isinstance(summary, dict) or summary.get("all_expected") is not True:
        reasons.append("SUMMARY_NOT_ALL_EXPECTED")

    if reasons:
        return Decision("failed", tuple(dict.fromkeys(reasons)), backend)
    return Decision("verified", ("ALL_PROBES_DENIED",), backend)


def fetch_instance_id(url: str, credential: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = json.loads(response.read(65536))
    instance_id = body.get("instance_id") if isinstance(body, dict) else None
    if not isinstance(instance_id, str) or not IDENTIFIER_RE.match(instance_id):
        raise ValueError("readiness response lacks a valid instance_id")
    return instance_id


def result_document(
    decision: Decision, *, instance_id: str, policy_sha256: str, now: datetime
) -> dict[str, Any]:
    return {
        "isolation": decision.isolation,
        "verified_at": now.isoformat() if decision.verified else None,
        "instance_id": instance_id,
        "policy_sha256": policy_sha256,
        "backend": decision.backend,
        "checked_at": now.isoformat(),
        "reasons": list(decision.reasons),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--evidence", type=Path, required=True, help="deny_check.py output")
    parser.add_argument("--policy", type=Path, required=True, help="effective policy file")
    parser.add_argument("--output", type=Path, required=True, help="isolation-evidence.json path")
    parser.add_argument("--readiness-url", default="http://127.0.0.1:18555/v1/readiness")
    parser.add_argument("--credential-file", type=Path, default=Path(".plva-pr/credential"))
    parser.add_argument("--instance-id", help="skip the readiness fetch and use this id")
    parser.add_argument("--expected-backend", choices=sorted(KNOWN_BACKENDS))
    parser.add_argument(
        "--negative-control",
        type=Path,
        help="evidence from `deny_check.py --negative-control` run unsandboxed on this host; "
        "when given it must be fresh and all-succeeded (corroborates resolver denials)",
    )
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    reasons: list[str] = []
    policy_sha256 = "0" * 64
    instance_id = "unknown"
    evidence: object = None

    try:
        policy_sha256 = sha256_file(args.policy)
    except OSError:
        reasons.append("POLICY_UNREADABLE")

    if args.instance_id:
        instance_id = args.instance_id
    else:
        try:
            credential = args.credential_file.read_text(encoding="utf-8").strip()
            instance_id = fetch_instance_id(args.readiness_url, credential, args.timeout)
        except (OSError, ValueError, urllib.error.URLError):
            reasons.append("READINESS_UNREACHABLE")

    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reasons.append("EVIDENCE_UNREADABLE")

    control: object = _NO_NEGATIVE_CONTROL
    if args.negative_control is not None:
        try:
            control = json.loads(args.negative_control.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            control = None  # unreadable -> NEGATIVE_CONTROL_UNREADABLE inside decide()

    if reasons:
        decision = Decision("failed", tuple(reasons))
    else:
        decision = decide(
            evidence,
            policy_sha256=policy_sha256,
            instance_id=instance_id,
            now=now,
            max_age_seconds=args.max_age_seconds,
            expected_backend=args.expected_backend,
            negative_control=control,
        )

    document = result_document(
        decision, instance_id=instance_id, policy_sha256=policy_sha256, now=now
    )
    write_json(args.output, document)
    print(f"[verify-isolation] isolation={decision.isolation} reasons={','.join(decision.reasons)}")
    print(f"[verify-isolation] wrote {args.output}")
    return 0 if decision.verified else 1


if __name__ == "__main__":
    sys.exit(main())
