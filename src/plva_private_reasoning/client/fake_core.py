"""Standalone fake core: exercises the client end to end with unmistakably synthetic values.

Run against the mock (``plva-pr-mock``) or the local service; only ``PLVA_PR_BASE_URL`` and
``PLVA_PR_CREDENTIAL_FILE`` change. Prints decisions, reason codes, tokens, and latency only.
Never prints a value. Exit code 0 when every call produced a genuine service result.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from .client import ClientError, PrivateReasoningClient, load_credential

DEFAULT_BASE_URL: Final = "http://127.0.0.1:18555"
DEFAULT_CREDENTIAL_FILE: Final = ".plva-pr/credential"

# Synthetic fixtures only. ``.invalid`` is reserved and can never resolve.
_ITEMS: Final = (
    {"token": "NAME_1_a3f9", "value": "Charlie Example"},
    {"token": "NAME_2_a3f9", "value": "Alice Example"},
    {"token": "NAME_3_a3f9", "value": "Bob Example"},
)
_EMAIL_ITEMS: Final = (
    {"token": "EMAIL_1_b7c2", "value": "charlie@example.invalid"},
    {"token": "EMAIL_2_b7c2", "value": "alice@example.invalid"},
    {"token": "EMAIL_3_b7c2", "value": "bob@example.invalid"},
)


def _timed[T](call: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - start) * 1000.0


def _emit(line: str) -> None:
    print(f"[fake-core] {line}", flush=True)


def _approve_request(session_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": session_id,
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
            "rules": ["Use this key only in the integration credential field."],
            "allowed_origins": ["https://service.example"],
            "allowed_fields": ["api-key-input"],
            "max_ttl_seconds": 60,
            "max_uses": 1,
        },
    }


def _sort_request(session_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "request_id": "compute-001",
        "operation": "sort",
        "instruction": "Alphabetical order by full name.",
        "items": [dict(item) for item in _ITEMS],
        "select_count": None,
    }


def _select_request(session_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "request_id": "compute-002",
        "operation": "select",
        "instruction": "Pick the two addresses that sort first alphabetically.",
        "items": [dict(item) for item in _EMAIL_ITEMS],
        "select_count": 2,
    }


def _trace_request(session_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "request_id": "trace-001",
        "events": [
            {"step": 1, "kind": "action", "tool_name": "type"},
            {"step": 2, "kind": "resolution_ok", "token": "NAME_1_a3f9", "pii_class": "NAME"},
            {"step": 3, "kind": "observation"},
        ],
        "task_context": "Update the account display name.",
        "policy": {
            "denied_resolution_threshold": 3,
            "window_steps": 8,
            "halt_on_blocked_class_attempt": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    del argv  # configuration is environment-only so the command line stays value-free
    base_url = os.environ.get("PLVA_PR_BASE_URL", DEFAULT_BASE_URL)
    credential_file = Path(os.environ.get("PLVA_PR_CREDENTIAL_FILE", DEFAULT_CREDENTIAL_FILE))
    _emit(f"base_url={base_url} credential_file={credential_file}")
    try:
        credential = load_credential(credential_file)
    except (OSError, ClientError):
        _emit("credential file unreadable; start the service first (plva-pr-mock)")
        return 2

    # This fake core only ever sends synthetic fixtures, so it may talk to mock mode.
    # A real core must leave allow_mock_for_private_values at its default (False).
    client = PrivateReasoningClient(
        base_url, credential, timeout_seconds=30.0, allow_mock_for_private_values=True
    )

    readiness, ms = _timed(client.readiness)
    if readiness is None:
        _emit(f"readiness unavailable failure={client.last_failure} latency_ms={ms:.1f}")
        return 1
    _emit(
        f"readiness mode={readiness.mode} ready_for_private_values="
        f"{readiness.ready_for_private_values} model_loaded={readiness.model_loaded} "
        f"isolation={readiness.isolation} instance_id={readiness.instance_id} "
        f"latency_ms={ms:.1f}"
    )
    if readiness.mode == "mock":
        _emit("MOCK MODE: synthetic fixtures only; never route real private values here")

    session_id = f"fake-core-{uuid.uuid4().hex[:12]}"
    failures = 0

    approval, ms = _timed(lambda: client.approve(_approve_request(session_id)))
    scope = approval.scope
    scope_text = (
        f"ttl_seconds={scope.ttl_seconds} max_uses={scope.max_uses}" if scope else "scope=null"
    )
    _emit(
        f"approve decision={approval.decision} reason={approval.reason_code} {scope_text} "
        f"latency_ms={ms:.1f}"
    )
    failures += client.last_failure is not None

    sorted_result, ms = _timed(lambda: client.compute(_sort_request(session_id)))
    permutation = sorted(sorted_result.tokens) == sorted(item["token"] for item in _ITEMS)
    _emit(
        f"compute/sort status={sorted_result.status} reason={sorted_result.reason_code} "
        f"tokens={sorted_result.tokens} permutation={permutation} latency_ms={ms:.1f}"
    )
    failures += client.last_failure is not None or not permutation

    selected, ms = _timed(lambda: client.compute(_select_request(session_id)))
    _emit(
        f"compute/select status={selected.status} reason={selected.reason_code} "
        f"tokens={selected.tokens} latency_ms={ms:.1f}"
    )
    failures += client.last_failure is not None

    review, ms = _timed(lambda: client.review_trace(_trace_request(session_id)))
    _emit(f"review-trace action={review.action} reason={review.reason_code} latency_ms={ms:.1f}")
    failures += client.last_failure is not None

    _emit(f"done mode={readiness.mode} failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
