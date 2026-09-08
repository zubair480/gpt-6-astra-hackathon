"""``plva-pr-local``: the real local-inference service, loopback only.

Mirrors the mock CLI: same bind rules, same per-launch credential, same runtime dir. Before
serving it verifies the GGUF's sha256 against the pinned manifest and refuses to start on a
mismatch. Readiness for private values is decided by ``ServiceState``, which re-reads the
isolation-evidence file on every readiness and compute check: the evidence is written by the
isolation launcher *after* launch (it is bound to this instance's ``instance_id``), so the
service starts unready and flips only when a fresh, instance-bound ``verified`` file appears.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import uvicorn

from ..service.app import ServiceState, create_app
from ..service.auth import generate_credential, write_credential
from .adapter import local_backends
from .backend import DEFAULT_N_CTX, MAX_N_CTX, InferenceError, LlamaCppBackend

_LOOPBACK: Final = {"127.0.0.1", "::1", "localhost"}
MANIFEST_PATH: Final = Path(__file__).with_name("manifest.json")
MANIFEST_KEYS: Final = (
    "model_name",
    "source_repo",
    "source_revision",
    "filename",
    "sha256",
    "license",
    "runtime",
)
# Matches sandbox/verify_isolation.py and ServiceState: evidence older than this is stale.
DEFAULT_EVIDENCE_MAX_AGE_SECONDS: Final = 900
# Where sandbox/start.sh writes the evidence, relative to the runtime dir it launched us with.
EVIDENCE_FILENAME: Final = "isolation-evidence.json"


class ProvisioningError(RuntimeError):
    """The model on disk does not match the manifest. Refuse to serve."""


@dataclass(frozen=True, slots=True)
class Manifest:
    model_name: str
    source_repo: str
    source_revision: str
    filename: str
    sha256: str
    license: str
    runtime: str

    @classmethod
    def load(cls, path: Path = MANIFEST_PATH) -> Manifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in MANIFEST_KEYS if not isinstance(data.get(key), str)]
        if missing:
            raise ProvisioningError("manifest is missing required fields")
        manifest = cls(**{key: data[key] for key in MANIFEST_KEYS})
        if len(manifest.sha256) != 64 or any(c not in "0123456789abcdef" for c in manifest.sha256):
            raise ProvisioningError("manifest sha256 is not a lowercase hex digest")
        return manifest


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_file(path: Path, manifest: Manifest) -> None:
    """Raise unless ``path`` exists and hashes to the manifest's pinned sha256."""
    if not path.is_file():
        raise ProvisioningError("model file not found; run scripts/provision_model.sh")
    if sha256_of(path) != manifest.sha256:
        raise ProvisioningError("model file sha256 does not match the pinned manifest")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plva-pr-local",
        description=(
            "PLVA private reasoning LOCAL service. Offline llama.cpp inference over a pinned "
            "GGUF, loopback only. Accepts private values only once isolation is verified."
        ),
    )
    parser.add_argument("--host", default=os.environ.get("PLVA_PR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PLVA_PR_PORT", "18555")))
    parser.add_argument(
        "--runtime-dir", type=Path, default=Path(os.environ.get("PLVA_PR_RUNTIME_DIR", ".plva-pr"))
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=_env_path("PLVA_PR_MODEL_PATH"),
        help="GGUF file (default: $PLVA_PR_MODEL_PATH, else models/<manifest filename>)",
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument(
        "--isolation-evidence",
        type=Path,
        default=_env_path("PLVA_PR_ISOLATION_EVIDENCE"),
        help=(
            "JSON evidence file from sandbox/verify_isolation.py, re-read on every readiness "
            f"check (default: $PLVA_PR_ISOLATION_EVIDENCE, else <runtime-dir>/{EVIDENCE_FILENAME})"
        ),
    )
    parser.add_argument(
        "--evidence-max-age-seconds", type=int, default=DEFAULT_EVIDENCE_MAX_AGE_SECONDS
    )
    parser.add_argument(
        "--policy-sha256",
        default=os.environ.get("PLVA_PR_POLICY_SHA256") or None,
        help="if given, evidence must name this effective sandbox policy digest",
    )
    parser.add_argument("--n-ctx", type=int, default=DEFAULT_N_CTX)
    parser.add_argument(
        "--n-gpu-layers", type=int, default=-1, help="-1 offloads everything (Metal); 0 = CPU"
    )
    parser.add_argument("--n-threads", type=int, default=None)
    return parser


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def main_local(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.host not in _LOOPBACK:
        parser.error("refusing to bind a non-loopback address")
    if not 512 <= args.n_ctx <= MAX_N_CTX:
        parser.error(f"--n-ctx must be between 512 and {MAX_N_CTX}")
    if args.evidence_max_age_seconds < 1:
        parser.error("--evidence-max-age-seconds must be positive")
    policy_sha256: str | None = args.policy_sha256
    if policy_sha256 is not None and (
        len(policy_sha256) != 64 or any(c not in "0123456789abcdef" for c in policy_sha256)
    ):
        parser.error("--policy-sha256 must be a lowercase hex digest")

    # Belt and braces: nothing in this process may reach a model hub at runtime.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    try:
        manifest = Manifest.load(args.manifest)
    except (OSError, ValueError, ProvisioningError) as exc:
        print(f"[plva-pr] refusing to start: {exc}", file=sys.stderr, flush=True)
        return 2
    model_path: Path = args.model_path or Path("models") / manifest.filename
    try:
        verify_model_file(model_path, manifest)
    except ProvisioningError as exc:
        print(f"[plva-pr] refusing to start: {exc}", file=sys.stderr, flush=True)
        return 2
    print(
        f"[plva-pr] model={manifest.model_name} file={model_path.name} "
        f"sha256=verified runtime={manifest.runtime}",
        flush=True,
    )

    try:
        backend = LlamaCppBackend(
            model_path,
            n_ctx=args.n_ctx,
            n_gpu_layers=args.n_gpu_layers,
            n_threads=args.n_threads,
        )
    except InferenceError as exc:
        print(f"[plva-pr] refusing to start: {exc}", file=sys.stderr, flush=True)
        return 2

    runtime_dir: Path = args.runtime_dir
    evidence_path: Path = args.isolation_evidence or runtime_dir / EVIDENCE_FILENAME
    credential = generate_credential()
    path = write_credential(runtime_dir, credential)
    state = ServiceState(
        mode="local",
        credential=credential,
        port=args.port,
        backends=local_backends(backend),
        model_loaded=True,
        evidence_path=evidence_path,
        evidence_max_age_seconds=args.evidence_max_age_seconds,
        policy_sha256=policy_sha256,
    )
    state.refresh_isolation()
    print(
        f"[plva-pr] MODE=local  bind={args.host}:{args.port}  credential_file={path}  "
        f"instance_id={state.instance_id}  evidence_file={evidence_path}  "
        f"isolation={state.isolation}  ready_for_private_values={state.ready_for_private_values}",
        flush=True,
    )
    if not state.ready_for_private_values:
        print(
            "[plva-pr] NOT ready for private values: isolation is not verified. The evidence "
            "file is re-read on every readiness check; run sandbox/verify_isolation.py against "
            "this instance to flip it. Synthetic fixtures only until then.",
            flush=True,
        )

    app = create_app(state)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        limit_concurrency=4,
        timeout_keep_alive=5,
        server_header=False,
        date_header=False,
    )
    return 0


logging.getLogger("uvicorn.access").disabled = True
