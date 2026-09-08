"""Entry points. ``plva-pr-mock`` runs the deterministic mock service on loopback."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .service.app import create_mock_app
from .service.auth import generate_credential, write_credential

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def main_mock(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plva-pr-mock",
        description=(
            "PLVA private reasoning MOCK service. Deterministic, model-free, loopback only. "
            "Never send real private values to this mode."
        ),
    )
    parser.add_argument("--host", default=os.environ.get("PLVA_PR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PLVA_PR_PORT", "18555")))
    parser.add_argument(
        "--runtime-dir", type=Path, default=Path(os.environ.get("PLVA_PR_RUNTIME_DIR", ".plva-pr"))
    )
    args = parser.parse_args(argv)
    if args.host not in _LOOPBACK:
        parser.error("refusing to bind a non-loopback address")

    credential = generate_credential()
    path = write_credential(args.runtime_dir, credential)
    print(f"[plva-pr] MODE=mock  bind={args.host}:{args.port}  credential_file={path}", flush=True)
    print(
        "[plva-pr] mock mode is NOT ready for private values; synthetic fixtures only.", flush=True
    )

    app = create_mock_app(credential, args.port)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,  # no per-request log lines at all
        limit_concurrency=8,
        timeout_keep_alive=5,
        server_header=False,
        date_header=False,
    )
    return 0


logging.getLogger("uvicorn.access").disabled = True
