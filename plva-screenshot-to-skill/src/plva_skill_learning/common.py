"""Shared bounded errors and schema helpers. Never echo untrusted payloads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

PACKAGE = Path(__file__).resolve().parent
TOKEN_PATTERN = r"\b[A-Z][A-Z0-9]*_[0-9]+_[a-f0-9]{4,32}\b"


class SkillforgeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def as_dict(self):
        return {"status": "error", "code": self.code, "message": self.message}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def check_schema(value, name: str):
    schema = json.loads((PACKAGE / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise SkillforgeError("schema_invalid", f"Invalid {name} structure; check required fields, types, and supported values.")


def read_json(path: Path, max_bytes: int = 2_000_000):
    try:
        if path.is_symlink() or path.stat().st_size > max_bytes:
            raise SkillforgeError("invalid_file", "JSON file is linked or exceeds the size limit.")
        return json.loads(path.read_text(encoding="utf-8"))
    except SkillforgeError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise SkillforgeError("invalid_json", "JSON file is missing, unreadable, or malformed.") from None


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
