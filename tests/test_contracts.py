"""Frozen contract checks: examples validate against the JSON Schemas and the pydantic
models, the reason-code export matches the runtime, and the export script reports no drift."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from plva_private_reasoning import reason_codes
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

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "v1"
EXAMPLES = CONTRACTS / "examples"

MODELS: dict[str, type[BaseModel]] = {
    "readiness-response": ReadinessResponse,
    "approve-request": ApproveRequest,
    "approve-response": ApproveResponse,
    "compute-request": ComputeRequest,
    "compute-response": ComputeResponse,
    "review-trace-request": ReviewTraceRequest,
    "review-trace-response": ReviewTraceResponse,
    "error-body": ErrorBody,
}
# Example file stems that do not name their schema directly.
EXAMPLE_TO_SCHEMA = {
    "approve-response-deny": "approve-response",
    "compute-response-error": "compute-response",
}


def schema_name(example: Path) -> str:
    return EXAMPLE_TO_SCHEMA.get(example.stem, example.stem)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


EXAMPLE_FILES = sorted(EXAMPLES.glob("*.json"))


def test_every_schema_has_an_example_and_vice_versa() -> None:
    assert EXAMPLE_FILES, "no examples found"
    assert {schema_name(p) for p in EXAMPLE_FILES} == set(MODELS)
    assert {p.stem for p in CONTRACTS.glob("*.schema.json")} == {
        f"{name}.schema" for name in MODELS
    }


@pytest.mark.parametrize("example", EXAMPLE_FILES, ids=[p.stem for p in EXAMPLE_FILES])
def test_example_matches_schema_and_model(example: Path) -> None:
    name = schema_name(example)
    schema = load(CONTRACTS / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    data = load(example)
    Draft202012Validator(schema).validate(data)
    model = MODELS[name]
    parsed = model.model_validate(data)
    # Round trip: serialising the model must still satisfy the schema.
    Draft202012Validator(schema).validate(parsed.model_dump(mode="json"))


@pytest.mark.parametrize("name", sorted(MODELS))
def test_schemas_forbid_unknown_fields(name: str) -> None:
    schema = load(CONTRACTS / f"{name}.schema.json")
    assert schema.get("additionalProperties") is False
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for definition in schema.get("$defs", {}).values():
        assert definition.get("additionalProperties") is False


def test_response_examples_echo_identifiers() -> None:
    for request_name, response_name in (
        ("approve-request", "approve-response"),
        ("compute-request", "compute-response"),
        ("review-trace-request", "review-trace-response"),
    ):
        request = load(EXAMPLES / f"{request_name}.json")
        response = load(EXAMPLES / f"{response_name}.json")
        for key in ("schema_version", "session_id", "request_id"):
            assert request[key] == response[key]


def test_example_reason_codes_are_registered() -> None:
    approve = load(EXAMPLES / "approve-response.json")["reason_code"]
    deny = load(EXAMPLES / "approve-response-deny.json")["reason_code"]
    assert {approve, deny} <= reason_codes.APPROVE_REASONS
    ok = load(EXAMPLES / "compute-response.json")["reason_code"]
    error = load(EXAMPLES / "compute-response-error.json")["reason_code"]
    assert {ok, error} <= reason_codes.COMPUTE_REASONS
    trace = load(EXAMPLES / "review-trace-response.json")["reason_code"]
    assert trace in reason_codes.TRACE_REASONS
    assert load(EXAMPLES / "error-body.json")["error_code"] in reason_codes.ERROR_CODES


def test_reason_codes_file_matches_runtime() -> None:
    exported = load(CONTRACTS / "reason-codes.json")
    assert exported == {
        "schema_version": "1.0",
        "approve": sorted(reason_codes.APPROVE_REASONS),
        "compute": sorted(reason_codes.COMPUTE_REASONS),
        "review_trace": sorted(reason_codes.TRACE_REASONS),
        "errors": sorted(reason_codes.ERROR_CODES),
    }
    # Every fallback code the client emits must be registered for its endpoint.
    assert "MODEL_UNAVAILABLE" in reason_codes.APPROVE_REASONS
    assert {"MODEL_UNAVAILABLE", "NOT_READY"} <= reason_codes.COMPUTE_REASONS
    assert "MODEL_UNAVAILABLE" in reason_codes.TRACE_REASONS


def test_openapi_references_existing_schemas() -> None:
    document = load(CONTRACTS / "openapi.json")
    assert document["openapi"].startswith("3.1")
    assert set(document["paths"]) == {
        "/health",
        "/v1/readiness",
        "/v1/approve",
        "/v1/compute",
        "/v1/review-trace",
    }
    refs: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                refs.add(node["$ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    assert refs
    for ref in refs:
        assert ref.startswith("./") and (CONTRACTS / ref[2:]).is_file()


def test_export_script_reports_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_contracts.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
