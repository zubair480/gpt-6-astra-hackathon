"""Loopback HTTP transport for the private reasoning service.

Every error is a fixed body. Framework validation details are never returned because they
would echo submitted values.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..contracts import (
    MAX_REQUEST_BODY_BYTES,
    ApproveRequest,
    ComputeRequest,
    ErrorBody,
    ReadinessResponse,
    ReviewTraceRequest,
)
from ..operations import approve, compute, review_trace
from .auth import bearer_matches
from .replay import ReplayGuard


@dataclass(frozen=True, slots=True)
class Backends:
    approve: approve.Backend
    compute: compute.Backend
    review_trace: review_trace.Backend


def mock_backends() -> Backends:
    return Backends(approve.mock_backend, compute.mock_backend, review_trace.mock_backend)


@dataclass(slots=True)
class ServiceState:
    mode: str
    credential: str
    port: int
    backends: Backends
    model_loaded: bool = False
    isolation: str = "unverified"
    verified_at: str | None = None
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    replay: ReplayGuard = field(default_factory=ReplayGuard)
    # Isolation evidence is re-read on every readiness check so a verification performed
    # AFTER launch (it must be, since it is bound to instance_id) can flip the state, and a
    # deleted or stale file flips it back. Absent file: unverified. Bad file: failed.
    evidence_path: Path | None = None
    evidence_max_age_seconds: int = 900
    policy_sha256: str | None = None

    @property
    def ready_for_private_values(self) -> bool:
        return self.mode == "local" and self.model_loaded and self.isolation == "verified"

    def refresh_isolation(self, now: datetime | None = None) -> None:
        if self.evidence_path is None:
            return
        self.isolation, self.verified_at = evaluate_evidence(
            self.evidence_path,
            instance_id=self.instance_id,
            policy_sha256=self.policy_sha256,
            max_age_seconds=self.evidence_max_age_seconds,
            now=now or datetime.now(UTC),
        )

    def readiness(self) -> ReadinessResponse:
        self.refresh_isolation()
        return ReadinessResponse(
            mode=self.mode,  # type: ignore[arg-type]
            ready_for_private_values=self.ready_for_private_values,
            model_loaded=self.model_loaded,
            isolation=self.isolation,  # type: ignore[arg-type]
            capabilities=["approve", "compute", "review-trace"],
            instance_id=self.instance_id,
            service_version=__version__,
            verified_at=self.verified_at,
        )


def evaluate_evidence(
    path: Path,
    *,
    instance_id: str,
    policy_sha256: str | None,
    max_age_seconds: int,
    now: datetime,
) -> tuple[str, str | None]:
    """Return (isolation, verified_at). Only a fresh, instance-bound 'verified' file verifies."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "unverified", None
    except OSError:
        return "failed", None
    try:
        data = json.loads(raw)
    except ValueError:
        return "failed", None
    if not isinstance(data, dict) or data.get("isolation") != "verified":
        return "failed", None
    if data.get("instance_id") != instance_id:
        return "failed", None
    if policy_sha256 is not None and data.get("policy_sha256") != policy_sha256:
        return "failed", None
    stamp = data.get("verified_at")
    if not isinstance(stamp, str):
        return "failed", None
    try:
        verified_at = datetime.fromisoformat(stamp)
    except ValueError:
        return "failed", None
    if verified_at.tzinfo is None:
        return "failed", None
    if verified_at > now + timedelta(seconds=60):
        return "failed", None
    if now - verified_at > timedelta(seconds=max_age_seconds):
        return "failed", None
    return "verified", verified_at.isoformat()


def error_response(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorBody(error_code=code).model_dump(),
        headers={"Cache-Control": "no-store"},
    )


_STATUS_TO_CODE = {
    401: "UNAUTHORIZED",
    404: "SCHEMA_INVALID",
    405: "SCHEMA_INVALID",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
}


def create_app(state: ServiceState) -> FastAPI:
    app = FastAPI(
        title="PLVA private reasoning",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    allowed_hosts = {f"127.0.0.1:{state.port}", f"localhost:{state.port}", f"[::1]:{state.port}"}

    @app.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host") not in allowed_hosts:
            return error_response(403, "FORBIDDEN_HOST")
        if "origin" in request.headers:
            return error_response(403, "FORBIDDEN_ORIGIN")
        if request.url.path != "/health":
            if not bearer_matches(request.headers.get("authorization"), state.credential):
                return error_response(401, "UNAUTHORIZED")
            if request.method == "POST":
                length = request.headers.get("content-length")
                if length is None or not length.isdigit() or int(length) > MAX_REQUEST_BODY_BYTES:
                    return error_response(413, "PAYLOAD_TOO_LARGE")
                if (
                    request.headers.get("content-type", "").split(";")[0].strip()
                    != "application/json"
                ):
                    return error_response(415, "UNSUPPORTED_MEDIA_TYPE")
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(400, "SCHEMA_INVALID")

    @app.exception_handler(ValidationError)
    async def _pydantic(_: Request, __: ValidationError) -> JSONResponse:
        return error_response(400, "SCHEMA_INVALID")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(
            exc.status_code, _STATUS_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
        )

    @app.exception_handler(Exception)
    async def _any(_: Request, __: Exception) -> JSONResponse:
        return error_response(500, "INTERNAL_ERROR")

    async def parse(request: Request, model: type[Any]) -> Any:
        raw = await request.body()
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            raise StarletteHTTPException(413)
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise RequestValidationError([]) from exc
        try:
            parsed = model.model_validate(payload)
        except ValidationError as exc:
            raise RequestValidationError([]) from exc
        finally:
            del raw, payload
        if not state.replay.register(parsed.session_id, parsed.request_id):
            raise DuplicateRequestError
        return parsed

    class DuplicateRequestError(Exception):
        pass

    class NotReadyError(Exception):
        pass

    @app.exception_handler(NotReadyError)
    async def _not_ready(_: Request, __: NotReadyError) -> JSONResponse:
        return error_response(503, "NOT_READY")

    @app.exception_handler(DuplicateRequestError)
    async def _dup(_: Request, __: DuplicateRequestError) -> JSONResponse:
        return error_response(409, "DUPLICATE_REQUEST")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/v1/readiness")
    async def readiness() -> dict[str, Any]:
        return state.readiness().model_dump()

    @app.post("/v1/approve")
    async def approve_endpoint(request: Request) -> dict[str, Any]:
        parsed = await parse(request, ApproveRequest)
        return approve.run(parsed, state.backends.approve).model_dump()

    @app.post("/v1/compute")
    async def compute_endpoint(request: Request) -> dict[str, Any]:
        if state.mode != "mock":
            state.refresh_isolation()
            if not state.ready_for_private_values:
                raise NotReadyError
        parsed = await parse(request, ComputeRequest)
        return compute.run(parsed, state.backends.compute).model_dump()

    @app.post("/v1/review-trace")
    async def review_trace_endpoint(request: Request) -> dict[str, Any]:
        parsed = await parse(request, ReviewTraceRequest)
        return review_trace.run(parsed, state.backends.review_trace).model_dump()

    return app


def create_mock_app(credential: str, port: int) -> FastAPI:
    return create_app(
        ServiceState(mode="mock", credential=credential, port=port, backends=mock_backends())
    )
