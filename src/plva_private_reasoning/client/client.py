"""Thin, fail-closed client for the PLVA private reasoning service.

Standard library transport only (``http.client``), so the core does not need to adopt any
HTTP framework. Design rules, all enforced here rather than left to the caller:

* Every failure (unreachable, timeout, non-200, malformed body, identifier mismatch) collapses
  to the typed fail-closed result: approve -> ``deny``, compute -> ``error`` with no tokens,
  review-trace -> ``halt``; reason code ``MODEL_UNAVAILABLE``.
* Nothing is ever retried. A retried approval could mint a second grant.
* A response that arrives after the call's deadline is discarded even if it is valid.
* Responses are validated against the frozen contract models and the echoed
  ``schema_version`` / ``session_id`` / ``request_id`` must match the request.
* ``compute`` refuses to send values unless readiness reports ``ready_for_private_values``
  or the caller explicitly opted into mock mode for synthetic values.
* Request bodies never appear in log lines or exception messages. ``last_failure`` is a fixed
  value-free code that is safe to log.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from pydantic import ValidationError

from ..contracts import (
    ApproveRequest,
    ApproveResponse,
    ComputeRequest,
    ComputeResponse,
    Envelope,
    ReadinessResponse,
    ReviewTraceRequest,
    ReviewTraceResponse,
)

MODEL_UNAVAILABLE: Final = "MODEL_UNAVAILABLE"
NOT_READY: Final = "NOT_READY"

DEFAULT_TIMEOUT_SECONDS: Final = 10.0
DEFAULT_READINESS_TTL_SECONDS: Final = 5.0
MAX_RESPONSE_BYTES: Final = 65536

# Fixed diagnostics describing the most recent failed call. They carry no request content.
FAILURE_DISABLED: Final = "disabled"
FAILURE_UNREACHABLE: Final = "unreachable"
FAILURE_TIMEOUT: Final = "timeout"
FAILURE_LATE: Final = "late"
FAILURE_MALFORMED: Final = "malformed"
FAILURE_MISMATCH: Final = "mismatch"
FAILURE_OVERSIZED: Final = "oversized"
FAILURE_NOT_READY: Final = "not_ready"

_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})


class ClientError(Exception):
    """Raised only for caller mistakes (bad base URL, request violating the contract).

    Messages are fixed strings; they never include the offending request.
    """


def load_credential(path: str | Path) -> str:
    """Read the per-launch bearer credential written by the service at startup."""
    credential = Path(path).read_text(encoding="utf-8").strip()
    if not credential:
        raise ClientError("credential file is empty")
    return credential


def closed_approve(envelope: Envelope, reason_code: str = MODEL_UNAVAILABLE) -> ApproveResponse:
    """The fail-closed approval result for a request envelope."""
    return ApproveResponse(
        schema_version=envelope.schema_version,
        session_id=envelope.session_id,
        request_id=envelope.request_id,
        decision="deny",
        reason_code=reason_code,
        scope=None,
    )


def closed_compute(envelope: Envelope, reason_code: str = MODEL_UNAVAILABLE) -> ComputeResponse:
    """The fail-closed computation result: error, no tokens."""
    return ComputeResponse(
        schema_version=envelope.schema_version,
        session_id=envelope.session_id,
        request_id=envelope.request_id,
        status="error",
        tokens=[],
        reason_code=reason_code,
    )


def closed_review(envelope: Envelope, reason_code: str = MODEL_UNAVAILABLE) -> ReviewTraceResponse:
    """The fail-closed trace review result: halt."""
    return ReviewTraceResponse(
        schema_version=envelope.schema_version,
        session_id=envelope.session_id,
        request_id=envelope.request_id,
        action="halt",
        reason_code=reason_code,
    )


@dataclass(frozen=True, slots=True)
class _RawResponse:
    status: int
    body: bytes


@dataclass(frozen=True, slots=True)
class _Endpoint:
    scheme: str
    host: str
    port: int
    path_prefix: str


def _parse_base_url(base_url: str) -> _Endpoint:
    parts = urlsplit(base_url)
    if parts.scheme not in _ALLOWED_SCHEMES or not parts.hostname:
        raise ClientError("base_url must be an http(s) URL with a host")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ClientError("base_url must not carry query, fragment, or userinfo")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return _Endpoint(parts.scheme, parts.hostname, port, parts.path.rstrip("/"))


class PrivateReasoningClient:
    """Fail-closed client for ``/v1/readiness``, ``/v1/approve``, ``/v1/compute``,
    ``/v1/review-trace``."""

    def __init__(
        self,
        base_url: str,
        credential: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        enabled: bool = True,
        allow_mock_for_private_values: bool = False,
        readiness_ttl_seconds: float = DEFAULT_READINESS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0:
            raise ClientError("timeout_seconds must be positive")
        if not credential:
            raise ClientError("credential must not be empty")
        self._endpoint = _parse_base_url(base_url)
        self._credential = credential
        self._timeout = float(timeout_seconds)
        self._enabled = bool(enabled)
        self._allow_mock = bool(allow_mock_for_private_values)
        self._readiness_ttl = float(readiness_ttl_seconds)
        self._clock = clock
        self._last_failure: str | None = None
        self._readiness_cache: tuple[float, ReadinessResponse] | None = None

    # --- public surface -------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def allow_mock_for_private_values(self) -> bool:
        return self._allow_mock

    @property
    def last_failure(self) -> str | None:
        """Fixed code for the most recent failed call (``None`` after a success). Loggable."""
        return self._last_failure

    def readiness(self) -> ReadinessResponse | None:
        """Fresh readiness probe. ``None`` when disabled or the service cannot be trusted."""
        if not self._enabled:
            self._last_failure = FAILURE_DISABLED
            return None
        payload = self._exchange("GET", "/v1/readiness", None)
        if payload is None:
            return None
        try:
            readiness = ReadinessResponse.model_validate(payload)
        except ValidationError:
            self._last_failure = FAILURE_MALFORMED
            return None
        self._last_failure = None
        self._readiness_cache = (self._clock(), readiness)
        return readiness

    def approve(self, request: Mapping[str, Any]) -> ApproveResponse:
        parsed = self._validate_request(ApproveRequest, request)
        if not self._enabled:
            self._last_failure = FAILURE_DISABLED
            return closed_approve(parsed)
        result = self._post("/v1/approve", parsed, ApproveResponse)
        return result if result is not None else closed_approve(parsed)

    def compute(self, request: Mapping[str, Any]) -> ComputeResponse:
        parsed = self._validate_request(ComputeRequest, request)
        if not self._enabled:
            self._last_failure = FAILURE_DISABLED
            return closed_compute(parsed)
        if not self._private_values_allowed():
            self._last_failure = FAILURE_NOT_READY
            return closed_compute(parsed, NOT_READY)
        result = self._post("/v1/compute", parsed, ComputeResponse)
        return result if result is not None else closed_compute(parsed)

    def review_trace(self, request: Mapping[str, Any]) -> ReviewTraceResponse:
        parsed = self._validate_request(ReviewTraceRequest, request)
        if not self._enabled:
            self._last_failure = FAILURE_DISABLED
            return closed_review(parsed)
        result = self._post("/v1/review-trace", parsed, ReviewTraceResponse)
        return result if result is not None else closed_review(parsed)

    # --- readiness gate ---------------------------------------------------------

    def _private_values_allowed(self) -> bool:
        if self._allow_mock:
            return True
        readiness = self._cached_readiness()
        return readiness is not None and readiness.ready_for_private_values

    def _cached_readiness(self) -> ReadinessResponse | None:
        cached = self._readiness_cache
        if cached is not None:
            fetched_at, readiness = cached
            if 0 <= self._clock() - fetched_at < self._readiness_ttl:
                return readiness
        return self.readiness()

    # --- request/response handling ---------------------------------------------

    @staticmethod
    def _validate_request[E: Envelope](model: type[E], request: Mapping[str, Any]) -> E:
        parsed: E | None = None
        # The pydantic error repeats submitted values; suppress it fully so it can never become
        # the ClientError's __cause__ or __context__.
        with contextlib.suppress(ValidationError, TypeError, ValueError):
            parsed = model.model_validate(dict(request))
        if parsed is None:
            raise ClientError(f"request does not satisfy the {model.__name__} contract")
        return parsed

    def _post[E: Envelope](self, path: str, request: Envelope, model: type[E]) -> E | None:
        body = json.dumps(request.model_dump(mode="json"), separators=(",", ":")).encode()
        try:
            payload = self._exchange("POST", path, body)
        finally:
            del body
        if payload is None:
            return None
        try:
            parsed = model.model_validate(payload)
        except ValidationError:
            self._last_failure = FAILURE_MALFORMED
            return None
        if (
            parsed.schema_version != request.schema_version
            or parsed.session_id != request.session_id
            or parsed.request_id != request.request_id
        ):
            self._last_failure = FAILURE_MISMATCH
            return None
        self._last_failure = None
        return parsed

    def _exchange(self, method: str, path: str, body: bytes | None) -> dict[str, Any] | None:
        deadline = self._clock() + self._timeout
        try:
            raw = self._send(method, path, body)
        except TimeoutError:
            self._last_failure = FAILURE_TIMEOUT
            return None
        except (OSError, http.client.HTTPException):
            self._last_failure = FAILURE_UNREACHABLE
            return None
        if self._clock() > deadline:
            # Arrived after the deadline: the caller may already have acted on a fallback.
            self._last_failure = FAILURE_LATE
            return None
        if raw.status != 200:
            self._last_failure = f"http_{raw.status}"
            return None
        if len(raw.body) > MAX_RESPONSE_BYTES:
            self._last_failure = FAILURE_OVERSIZED
            return None
        try:
            payload = json.loads(raw.body)
        except ValueError:
            self._last_failure = FAILURE_MALFORMED
            return None
        if not isinstance(payload, dict):
            self._last_failure = FAILURE_MALFORMED
            return None
        return payload

    def _send(self, method: str, path: str, body: bytes | None) -> _RawResponse:
        """One request on a fresh connection. Only ``Authorization`` and ``Content-Type`` are
        added; there is never an ``Origin`` header."""
        headers = {
            "Authorization": f"Bearer {self._credential}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = self._connect()
        try:
            connection.request(
                method, f"{self._endpoint.path_prefix}{path}", body=body, headers=headers
            )
            response = connection.getresponse()
            return _RawResponse(response.status, response.read(MAX_RESPONSE_BYTES + 1))
        finally:
            connection.close()

    def _connect(self) -> http.client.HTTPConnection:
        endpoint = self._endpoint
        if endpoint.scheme == "https":
            return http.client.HTTPSConnection(endpoint.host, endpoint.port, timeout=self._timeout)
        return http.client.HTTPConnection(endpoint.host, endpoint.port, timeout=self._timeout)
