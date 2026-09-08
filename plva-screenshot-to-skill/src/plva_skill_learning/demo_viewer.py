"""A self-contained local walkthrough of the synthetic demo's actual outputs."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from .common import PACKAGE, SkillforgeError, digest, read_json
from .ingest import import_bundle
from .safety import check_outbound
from .validation import validate_skill


def _json_for_html(value):
    # Evidence is data, never markup or script, even in an offline demo file.
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _image(path, expected_hash=None):
    data = path.read_bytes()
    if expected_hash and digest(data) != expected_hash:
        raise SkillforgeError("recording_changed", "A demo frame changed after evidence import.")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _quality_audit():
    """Display the measured learning suite only for the exact tested source files."""
    path = PACKAGE / "data/quality-audit.json"
    if not path.exists():
        return None
    audit = read_json(path)
    # Python normalizes source newlines too; keep the measurement portable across
    # Git checkouts that convert LF to CRLF on Windows.
    actual = {p.name: digest(p.read_text(encoding="utf-8").encode("utf-8")) for p in sorted(PACKAGE.glob("*.py"))}
    return audit if audit.get("source_hashes") == actual else None


def write_demo_viewer(demo_dir, fixtures_dir):
    root, fixtures = Path(demo_dir), Path(fixtures_dir)
    report = validate_skill(root / "candidate")
    if report["status"] == "invalid":
        raise SkillforgeError("invalid_candidate", "The visual walkthrough requires a valid generated candidate.")
    recording = import_bundle(fixtures / "shipment-demo")
    if recording["manifest"]["provenance"]["data_class"] != "synthetic":
        raise SkillforgeError("synthetic_required", "The visual demo embeds only the approved synthetic fixture.")
    workflow = read_json(root / "candidate/workflow.json")
    if workflow["generation"]["bundle_digest"] != recording["bundle_digest"]:
        raise SkillforgeError("recording_mismatch", "The candidate and displayed source recording must match.")
    frames = [{**frame, "image": _image(Path(recording["bundle_path"]) / frame["path"], frame["sha256"])} for frame in recording["manifest"]["frames"]]
    from .rehearsal import run_rehearsal, package_digest
    rehearsal_path = root / "rehearsal.json"
    rehearsal = read_json(rehearsal_path) if rehearsal_path.exists() else run_rehearsal(root / "candidate")
    if rehearsal.get("package_digest") != package_digest(root / "candidate"):
        raise SkillforgeError("stale_rehearsal", "Re-run rehearsal after changing the candidate; its report no longer matches.")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rehearsal": rehearsal,
        "quality_audit": _quality_audit(),
        "recording": {"manifest": recording["manifest"], "events": recording["events"]},
        "frames": frames,
        "workflow": workflow,
        "evidence": read_json(root / "candidate/evidence-map.json"),
        "validation": report,
        "evaluation": read_json(root / "evaluation.json"),
        "prepared": read_json(root / "prepared-context.json"),
        "markdown": (root / "candidate/SKILL.md").read_text(encoding="utf-8"),
        "scenario": read_json(fixtures / "changed-layout/scenario.json"),
        "changed_image": _image(fixtures / "changed-layout/screen.png"),
    }
    # Local viewer intentionally shows synthetic source tokens and fresh tokens.
    # It stays outside the portable skill folder and cannot operate applications.
    check_outbound({k: v for k, v in payload.items() if k not in {"frames", "changed_image"}}, allow_tokens=True)
    template = (PACKAGE / "data/viewer.html").read_text(encoding="utf-8")
    output = root / "demo.html"
    output.write_text(template.replace("__DEMO_PAYLOAD__", _json_for_html(payload)), encoding="utf-8")
    return output.resolve()
