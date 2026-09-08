"""``plva-pr-local`` startup gates: checksum, isolation evidence wiring, loopback bind."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from plva_private_reasoning.model import cli
from plva_private_reasoning.model.cli import (
    MANIFEST_PATH,
    Manifest,
    ProvisioningError,
    build_parser,
    main_local,
    sha256_of,
    verify_model_file,
)
from plva_private_reasoning.service.app import ServiceState


def write_manifest(path: Path, **overrides: object) -> Path:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"synthetic weights " * 100000)
    assert sha256_of(blob) == hashlib.sha256(blob.read_bytes()).hexdigest()


def test_verify_model_file_accepts_matching_digest(tmp_path: Path) -> None:
    blob = tmp_path / "model.gguf"
    blob.write_bytes(b"synthetic weights")
    manifest = Manifest.load(write_manifest(tmp_path / "m.json", sha256=sha256_of(blob)))
    verify_model_file(blob, manifest)


def test_verify_model_file_rejects_mismatch_and_missing(tmp_path: Path) -> None:
    blob = tmp_path / "model.gguf"
    blob.write_bytes(b"tampered weights")
    manifest = Manifest.load(MANIFEST_PATH)
    with pytest.raises(ProvisioningError, match="does not match"):
        verify_model_file(blob, manifest)
    with pytest.raises(ProvisioningError, match="not found"):
        verify_model_file(tmp_path / "absent.gguf", manifest)


def test_manifest_rejects_missing_fields_and_bad_digests(tmp_path: Path) -> None:
    with pytest.raises(ProvisioningError):
        Manifest.load(write_manifest(tmp_path / "a.json", sha256=None))
    with pytest.raises(ProvisioningError):
        Manifest.load(write_manifest(tmp_path / "b.json", sha256="ABC"))


def test_parser_defaults_are_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PLVA_PR_HOST",
        "PLVA_PR_PORT",
        "PLVA_PR_MODEL_PATH",
        "PLVA_PR_ISOLATION_EVIDENCE",
        "PLVA_PR_POLICY_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    args = build_parser().parse_args([])
    assert (args.host, args.port) == ("127.0.0.1", 18555)
    assert args.model_path is None and args.isolation_evidence is None
    assert args.policy_sha256 is None
    assert args.evidence_max_age_seconds == 900  # same window as sandbox/verify_isolation.py
    assert args.n_gpu_layers == -1


def test_main_refuses_non_loopback_bind(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        main_local(["--host", "0.0.0.0", "--model-path", str(tmp_path / "x.gguf")])
    assert info.value.code == 2


def test_main_refuses_checksum_mismatch_before_loading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blob = tmp_path / "model.gguf"
    blob.write_bytes(b"tampered weights")
    code = main_local(["--model-path", str(blob), "--runtime-dir", str(tmp_path / "rt")])
    assert code == 2
    assert "refusing to start" in capsys.readouterr().err
    assert not (tmp_path / "rt").exists()  # no credential is minted for a refused launch


def test_main_refuses_missing_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main_local(["--model-path", str(tmp_path / "absent.gguf")])
    assert code == 2
    assert "provision_model.sh" in capsys.readouterr().err


def test_main_rejects_malformed_policy_digest(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main_local(["--policy-sha256", "XYZ", "--model-path", str(tmp_path / "x.gguf")])


class _FakeLlamaBackend:
    """Stands in for LlamaCppBackend so the wiring test never loads weights."""

    def __init__(self, model_path: Path, **kwargs: Any) -> None:
        self.model_path = model_path
        self.kwargs = kwargs

    def complete(self, **kwargs: Any) -> str:
        raise AssertionError("the wiring test never runs inference")


def _launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]) -> ServiceState:
    """Run main_local up to the point of serving and hand back the ServiceState it built."""
    blob = tmp_path / "model.gguf"
    blob.write_bytes(b"synthetic weights")
    manifest = write_manifest(tmp_path / "m.json", sha256=sha256_of(blob))
    captured: dict[str, ServiceState] = {}

    def fake_create_app(state: ServiceState) -> object:
        captured["state"] = state
        return object()

    monkeypatch.setattr(cli, "LlamaCppBackend", _FakeLlamaBackend)
    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)
    code = main_local(
        [
            "--model-path",
            str(blob),
            "--manifest",
            str(manifest),
            "--runtime-dir",
            str(tmp_path / "rt"),
            *extra,
        ]
    )
    assert code == 0
    return captured["state"]


def _evidence(instance_id: str, *, age: timedelta = timedelta(0), **extra: object) -> str:
    payload: dict[str, object] = {
        "isolation": "verified",
        "verified_at": (datetime.now(UTC) - age).isoformat(),
        "instance_id": instance_id,
    }
    payload.update(extra)
    return json.dumps(payload)


def test_main_starts_unready_and_re_reads_instance_bound_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _launch(monkeypatch, tmp_path, [])
    out = capsys.readouterr().out
    assert state.mode == "local" and state.model_loaded is True
    assert state.evidence_path == tmp_path / "rt" / "isolation-evidence.json"  # launcher path
    assert state.evidence_max_age_seconds == 900
    assert state.policy_sha256 is None
    assert (tmp_path / "rt" / "credential").is_file()
    assert state.isolation == "unverified" and not state.ready_for_private_values
    assert "NOT ready for private values" in out
    assert f"instance_id={state.instance_id}" in out

    # The isolation track writes evidence after launch, bound to this instance.
    evidence = state.evidence_path
    assert evidence is not None
    evidence.write_text(_evidence(state.instance_id), encoding="utf-8")
    assert state.readiness().ready_for_private_values is True

    # Evidence for another instance, or stale evidence, drops readiness to failed.
    evidence.write_text(_evidence("someone-else"), encoding="utf-8")
    assert state.readiness().ready_for_private_values is False
    assert state.isolation == "failed"
    evidence.write_text(_evidence(state.instance_id, age=timedelta(hours=1)), encoding="utf-8")
    assert state.readiness().ready_for_private_values is False
    evidence.unlink()
    assert state.readiness().isolation == "unverified"


def test_main_passes_explicit_evidence_path_and_policy_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    digest = "ab" * 32
    state = _launch(
        monkeypatch,
        tmp_path,
        ["--isolation-evidence", str(tmp_path / "ev.json"), "--policy-sha256", digest],
    )
    assert state.evidence_path == tmp_path / "ev.json"
    assert state.policy_sha256 == digest
    evidence = tmp_path / "ev.json"
    evidence.write_text(_evidence(state.instance_id, policy_sha256="cd" * 32), encoding="utf-8")
    assert state.readiness().isolation == "failed"  # a different effective policy
    evidence.write_text(_evidence(state.instance_id, policy_sha256=digest), encoding="utf-8")
    assert state.readiness().ready_for_private_values is True
