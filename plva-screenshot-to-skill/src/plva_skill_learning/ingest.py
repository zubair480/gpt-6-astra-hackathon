"""Bounded local evidence import, with an explicit external approval list.

Approval means that the caller trusts the producer's sanitized bundle. It does
not sanitize text or certify image redaction. A manifest flag is never approval.
"""
from __future__ import annotations

import io
import json
import re
import warnings
from pathlib import Path, PurePosixPath, PureWindowsPath

from PIL import Image

from .common import PACKAGE, SkillforgeError, canonical, check_schema, digest, read_json, write_json

MAX_MANIFEST_BYTES = 1_000_000
MAX_EVENTS_BYTES = 16_000_000
MAX_EVENT_BYTES = 64_000
MAX_EVENTS = 10_000
MAX_FRAMES = 1000
MAX_FRAME_BYTES = 10_000_000
MAX_BUNDLE_BYTES = 100_000_000
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_SIDE = 8192


def _fail(code, message):
    raise SkillforgeError(code, message)


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _root(path):
    try:
        source = Path(path).absolute()
        if _linked(source) or any(_linked(p) for p in source.parents):
            _fail("unsafe_path", "Bundle paths must not contain symbolic links or junctions.")
        resolved = source.resolve(strict=True)
        if not resolved.is_dir():
            _fail("invalid_bundle", "Bundle must be an existing local directory.")
        return resolved
    except SkillforgeError:
        raise
    except (OSError, ValueError, TypeError):
        _fail("invalid_bundle", "Bundle must be an existing local directory.")


def _file(root, relative):
    """Only simple POSIX relative paths are valid, on Windows and POSIX hosts."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or "\x00" in relative:
        _fail("unsafe_path", "Bundle file path is unsafe.")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    parts = relative.split("/")
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(p in ("", ".", "..") for p in parts):
        _fail("unsafe_path", "Bundle file path must remain inside the bundle.")
    try:
        candidate = root.joinpath(*parts)
        for p in (candidate, *candidate.parents):
            if p == root:
                break
            if _linked(p):
                _fail("unsafe_path", "Linked bundle files are not supported.")
        result = candidate.resolve(strict=True)
        if not result.is_relative_to(root) or not result.is_file():
            _fail("unsafe_path", "Bundle file path must refer to a regular in-bundle file.")
        return result
    except SkillforgeError:
        raise
    except (OSError, ValueError):
        _fail("missing_file", "A required bundle file is missing or unreadable.")


def _read(path, limit):
    try:
        if path.stat().st_size > limit:
            _fail("size_limit", "A bundle file exceeds its size limit.")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            _fail("size_limit", "A bundle file exceeds its size limit.")
        return data
    except SkillforgeError:
        raise
    except OSError:
        _fail("missing_file", "A required bundle file is missing or unreadable.")


def _json(data):
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        _fail("invalid_json", "Bundle JSON is malformed or is not UTF-8.")


def _validate_image(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    _fail("invalid_image", "Evidence images must be PNG, JPEG, or WebP.")
                if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
                    _fail("size_limit", "An evidence image exceeds its dimension limit.")
                if getattr(image, "n_frames", 1) != 1:
                    _fail("invalid_image", "Evidence must contain single-frame images.")
                image.verify()
    except SkillforgeError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        _fail("invalid_image", "An evidence image is invalid or exceeds its dimension limit.")


def _references(manifest, events):
    by_id = {event["event_id"]: event for event in events}
    if len(by_id) != len(events) or len({e["sequence"] for e in events}) != len(events):
        _fail("duplicate_event", "Event IDs and sequence numbers must be unique.")
    frame_ids = {frame["frame_id"] for frame in manifest["frames"]}
    checks = {}
    action_statuses = set()
    for event in events:
        kind = event["type"]
        if kind == "observation" and event["frame_id"] not in frame_ids:
            _fail("missing_reference", "An observation refers to an unknown frame.")
        if kind == "action":
            key = (event["action_id"], event["status"])
            if key in action_statuses:
                _fail("duplicate_action_status", "An action status has been recorded more than once.")
            action_statuses.add(key)
            for side in ("before", "after"):
                ref = event.get(f"{side}_event_id")
                if ref is None:
                    continue
                target = by_id.get(ref)
                if target is None or target["type"] != "observation":
                    _fail("missing_reference", "Action frame links must refer to observation events.")
                if (side == "before" and target["sequence"] >= event["sequence"]) or (side == "after" and target["sequence"] <= event["sequence"]):
                    _fail("reference_order", "Action before/after links conflict with event order.")
        for ref in event.get("evidence_ids", []):
            if ref not in by_id or ref == event["event_id"]:
                _fail("missing_reference", "Evidence refers to an unknown event or to itself.")
            if kind == "check" and by_id[ref]["type"] not in {"observation", "action"}:
                _fail("invalid_evidence_type", "Checks must cite observation or action evidence.")
        if kind == "check":
            if event["check_id"] in checks:
                _fail("duplicate_check", "Check IDs must be unique.")
            checks[event["check_id"]] = event
    if any(ref not in checks for ref in manifest["outcome"]["check_ids"]):
        _fail("missing_reference", "Outcome refers to an unknown check.")


def _load_bundle(bundle_path):
    root = _root(bundle_path)
    manifest_bytes = _read(_file(root, "manifest.json"), MAX_MANIFEST_BYTES)
    manifest = _json(manifest_bytes)
    check_schema(manifest, "manifest")
    if not manifest["frames"]:
        _fail("missing_frames", "A recording must contain at least one evidence frame.")
    if len(manifest["frames"]) > MAX_FRAMES:
        _fail("size_limit", "The recording exceeds the frame limit.")
    frame_ids = [f["frame_id"] for f in manifest["frames"]]
    file_paths = ["manifest.json", manifest["events_file"]] + [f["path"] for f in manifest["frames"]]
    # Windows is case-insensitive; reject aliases portably rather than hash twice.
    if len(set(frame_ids)) != len(frame_ids) or len({p.casefold() for p in file_paths}) != len(file_paths):
        _fail("duplicate_frame", "Frame IDs and bundle file paths must be unique.")
    events_bytes = _read(_file(root, manifest["events_file"]), MAX_EVENTS_BYTES)
    events = []
    for line in events_bytes.splitlines():
        if not line.strip():
            continue
        if len(line) > MAX_EVENT_BYTES or len(events) >= MAX_EVENTS:
            _fail("size_limit", "The recording exceeds an event size or count limit.")
        event = _json(line)
        check_schema(event, "event")
        events.append(event)
    if not events:
        _fail("missing_events", "A recording must contain ordered observation events.")
    _references(manifest, events)
    events.sort(key=lambda event: event["sequence"])
    parts = {"manifest.json": digest(manifest_bytes), manifest["events_file"]: digest(events_bytes)}
    total = len(manifest_bytes) + len(events_bytes)
    for frame in manifest["frames"]:
        content = _read(_file(root, frame["path"]), MAX_FRAME_BYTES)
        total += len(content)
        if total > MAX_BUNDLE_BYTES:
            _fail("size_limit", "The recording exceeds the total bundle size limit.")
        actual_hash = digest(content)
        if actual_hash != frame["sha256"]:
            _fail("hash_mismatch", "An evidence frame does not match its declared hash.")
        _validate_image(content)
        parts[frame["path"]] = actual_hash
    notices = []
    if manifest["capture_mode"] == "screenshots_only":
        if any(e["type"] != "observation" for e in events):
            _fail("capture_mode_mismatch", "Screenshot-only recordings may contain only observation events.")
        notices.append("Screenshots show states; transitions and hidden actions remain inferred.")
    if any(b["time_ms"] < a["time_ms"] for a, b in zip(events, events[1:])):
        notices.append("Timestamps conflict with sequence order; sequence order is authoritative.")
    if any(b["sequence"] != a["sequence"] + 1 for a, b in zip(events, events[1:])):
        notices.append("Sequence gaps are present; omitted events are unknown.")
    outcome_checks = [e for e in events if e["type"] == "check" and e["check_id"] in manifest["outcome"]["check_ids"]]
    if manifest["outcome"]["status"] == "passed" and not any(e["result"] == "passed" and e["source"] in {"core_verifier", "user_confirmation"} and e["evidence_ids"] for e in outcome_checks):
        notices.append("Claimed success has no independent outcome evidence; success remains unverified.")
    return {"manifest": manifest, "events": events, "bundle_path": str(root), "bundle_digest": digest(canonical(parts)), "warnings": notices}


def _store_path(approval_store, root):
    try:
        path = Path(approval_store).absolute()
        if _linked(path) or any(_linked(p) for p in path.parents):
            _fail("unsafe_approval_store", "Approval storage must not use symbolic links or junctions.")
        path = path.resolve()
        if path == root or path.is_relative_to(root):
            _fail("unsafe_approval_store", "Approval storage must be outside the recording bundle.")
        return path
    except SkillforgeError:
        raise
    except (OSError, ValueError, TypeError):
        _fail("unsafe_approval_store", "Approval storage must be an external local JSON file.")


def _registry(path, missing_ok=False):
    if missing_ok and not path.exists():
        return {"schema_version": "1.0", "approvals": []}
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != "1.0" or not isinstance(value.get("approvals"), list):
        _fail("invalid_approval_store", "Approval storage has an unsupported structure.")
    if len(value["approvals"]) > MAX_EVENTS:
        _fail("invalid_approval_store", "Approval storage exceeds its entry limit.")
    for entry in value["approvals"]:
        if not isinstance(entry, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("bundle_digest", ""))) or not isinstance(entry.get("producer"), str) or entry.get("data_class") not in {"synthetic", "sanitized"} or type(entry.get("allow_cloud")) is not bool or type(entry.get("role_hints_trusted")) is not bool:
            _fail("invalid_approval_store", "An approval entry has an unsupported structure.")
    return value


def _matching(registry, recording):
    provenance = recording["manifest"]["provenance"]
    entries = [entry for entry in registry["approvals"] if entry["bundle_digest"] == recording["bundle_digest"] and entry["producer"] == provenance["producer"] and entry["data_class"] == provenance["data_class"]]
    if len(entries) > 1:
        _fail("invalid_approval_store", "The bundle has conflicting duplicate approval entries.")
    return entries[0] if entries else None


def import_bundle(bundle_path, approval_store=None):
    """Import a pinned synthetic fixture or a bundle explicitly approved externally."""
    recording = _load_bundle(bundle_path)
    root = Path(recording["bundle_path"])
    external_path = _store_path(approval_store, root) if approval_store is not None else None
    approval = _matching(_registry(external_path), recording) if external_path else None
    if approval is None and recording["manifest"]["provenance"]["data_class"] == "synthetic":
        approval = _matching(_registry(PACKAGE / "data" / "trusted-synthetic.json"), recording)
    if approval is None:
        _fail("unapproved_bundle", "This bundle has no matching local approval. Approve this exact bundle through the core or local review first.")
    recording["approval"] = {"allow_cloud": approval["allow_cloud"], "role_hints_trusted": approval["role_hints_trusted"]}
    recording["approval_store"] = str(external_path) if external_path else None
    if not approval["role_hints_trusted"]:
        recording["warnings"].append("Role hints have not been trusted by the caller; ambiguous bindings require review.")
    return recording


def approve_bundle(bundle_path, approval_store, allow_cloud=False, role_hints_trusted=False):
    """Record an explicit caller decision for these exact bytes; never a sanitizer."""
    if type(allow_cloud) is not bool or type(role_hints_trusted) is not bool:
        _fail("invalid_approval", "Approval options must be explicit boolean values.")
    recording = _load_bundle(bundle_path)
    path = _store_path(approval_store, Path(recording["bundle_path"]))
    registry = _registry(path, missing_ok=True)
    provenance = recording["manifest"]["provenance"]
    entry = {"bundle_digest": recording["bundle_digest"], "producer": provenance["producer"], "data_class": provenance["data_class"], "allow_cloud": allow_cloud, "role_hints_trusted": role_hints_trusted}
    registry["approvals"] = [old for old in registry["approvals"] if old["bundle_digest"] != entry["bundle_digest"]] + [entry]
    try:
        write_json(path, registry)
    except OSError:
        _fail("approval_write_failed", "The external approval store could not be written.")
    return {"bundle_digest": recording["bundle_digest"], "approval_store": str(path), "allow_cloud": allow_cloud, "role_hints_trusted": role_hints_trusted}
