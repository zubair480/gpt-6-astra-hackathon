"""Per-launch local bearer credential."""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

CREDENTIAL_FILENAME = "credential"


def generate_credential() -> str:
    return secrets.token_urlsafe(32)


def write_credential(runtime_dir: Path, credential: str) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime_dir, 0o700)
    path = runtime_dir / CREDENTIAL_FILENAME
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(credential)
    return path


def read_credential(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def bearer_matches(header_value: str | None, credential: str) -> bool:
    if not header_value or not header_value.startswith("Bearer "):
        return False
    presented = header_value[len("Bearer ") :].strip()
    return bool(presented) and hmac.compare_digest(presented.encode(), credential.encode())
