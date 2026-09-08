"""Export the frozen v1 contract files from the runtime models.

Run ``uv run python scripts/export_contracts.py`` after an intentional contract change and
commit the output. ``tests/test_contracts.py`` fails when the files drift from the models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from plva_private_reasoning import __version__, reason_codes
from plva_private_reasoning.contracts import (
    ApproveRequest,
    ApproveResponse,
    ComputeRequest,
    ComputeResponse,
    ErrorBody,
    ReadinessResponse,
    ReviewTraceRequest,
    ReviewTraceResponse,
)

ROOT = Path(__file__).resolve().parents[1] / "contracts" / "v1"

MODELS = {
    "readiness-response": ReadinessResponse,
    "approve-request": ApproveRequest,
    "approve-response": ApproveResponse,
    "compute-request": ComputeRequest,
    "compute-response": ComputeResponse,
    "review-trace-request": ReviewTraceRequest,
    "review-trace-response": ReviewTraceResponse,
    "error-body": ErrorBody,
}


def schema_for(name: str, model: Any) -> dict[str, Any]:
    schema = model.model_json_schema(mode="serialization" if name.endswith("response") else "validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://plva.local/contracts/v1/{name}.schema.json"
    return schema


def openapi() -> dict[str, Any]:
    def ref(name: str) -> dict[str, str]:
        return {"$ref": f"./{name}.schema.json"}

    def op(name: str, summary: str) -> dict[str, Any]:
        return {
            "summary": summary,
            "security": [{"bearer": []}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": ref(f"{name}-request")}},
            },
            "responses": {
                "200": {
                    "description": "Typed recommendation; denials and errors are ordinary results.",
                    "content": {"application/json": {"schema": ref(f"{name}-response")}},
                },
                **{
                    code: {
                        "description": desc,
                        "content": {"application/json": {"schema": ref("error-body")}},
                    }
                    for code, desc in {
                        "400": "SCHEMA_INVALID: body rejected; input is never echoed",
                        "401": "UNAUTHORIZED",
                        "403": "FORBIDDEN_HOST or FORBIDDEN_ORIGIN",
                        "409": "DUPLICATE_REQUEST: (session_id, request_id) already seen",
                        "413": "PAYLOAD_TOO_LARGE",
                        "415": "UNSUPPORTED_MEDIA_TYPE",
                        "503": "NOT_READY",
                    }.items()
                },
            },
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "PLVA private reasoning service",
            "version": __version__,
            "description": "Loopback-only local recommendations for the PLVA core. "
            "schema_version 1.0. The core enforces every decision; this service only recommends.",
        },
        "servers": [{"url": "http://127.0.0.1:18555"}],
        "components": {
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Process liveness only. Unauthenticated.",
                    "responses": {"200": {"description": '{"status": "alive"}'}},
                }
            },
            "/v1/readiness": {
                "get": {
                    "summary": "Authenticated readiness, mode, isolation state, capabilities.",
                    "security": [{"bearer": []}],
                    "responses": {
                        "200": {
                            "description": "Readiness",
                            "content": {"application/json": {"schema": ref("readiness-response")}},
                        }
                    },
                }
            },
            "/v1/approve": {"post": op("approve", "Recommend approve/deny for one private action.")},
            "/v1/compute": {"post": op("compute", "Bounded sort/select; returns input tokens only.")},
            "/v1/review-trace": {
                "post": op("review-trace", "Recommend continue/warn/halt over a value-free trace.")
            },
        },
    }


def render() -> dict[str, str]:
    files = {f"{name}.schema.json": schema_for(name, model) for name, model in MODELS.items()}
    files["openapi.json"] = openapi()
    files["reason-codes.json"] = {
        "schema_version": "1.0",
        "approve": sorted(reason_codes.APPROVE_REASONS),
        "compute": sorted(reason_codes.COMPUTE_REASONS),
        "review_trace": sorted(reason_codes.TRACE_REASONS),
        "errors": sorted(reason_codes.ERROR_CODES),
    }
    return {name: json.dumps(body, indent=2, sort_keys=True) + "\n" for name, body in files.items()}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    drift = []
    for name, text in render().items():
        path = ROOT / name
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                drift.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if drift:
        print("contract drift:", ", ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
