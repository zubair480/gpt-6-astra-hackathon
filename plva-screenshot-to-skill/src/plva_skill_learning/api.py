"""Small local JSON facade for the PLVA core; no server or execution engine."""
from __future__ import annotations

from pathlib import Path

from .common import SkillforgeError, canonical, digest, read_json, write_json
from .ingest import import_bundle
from .synthesis import draft
from .timeline import evidence_map
from .exporter import write_package
from .validation import validate_skill
from .runner_adapter import prepare_run


class SkillForge:
    def __init__(self, state_dir=".skillforge", approval_store=None):
        self.state = Path(state_dir).resolve()
        self.approval_store = Path(approval_store).resolve() if approval_store else self.state / "approvals.json"

    def _catalog(self):
        path = self.state / "catalog.json"
        return read_json(path) if path.exists() else {"recordings": {}, "candidates": {}}

    def _save(self, value):
        write_json(self.state / "catalog.json", value)

    def import_recording(self, bundle_path):
        recording = import_bundle(bundle_path, self.approval_store if self.approval_store.exists() else None)
        manifest = recording["manifest"]
        catalog = self._catalog()
        record_id = manifest["recording_id"]
        if record_id in catalog["recordings"] and catalog["recordings"][record_id]["bundle_digest"] != recording["bundle_digest"]:
            raise SkillforgeError("recording_id_conflict", "Recording ID already belongs to different evidence. Use a new recording ID.")
        catalog["recordings"][record_id] = {"path": recording["bundle_path"], "bundle_digest": recording["bundle_digest"]}
        self._save(catalog)
        return {"recording_id": record_id, "schema_version": "1.0", "capture_mode": manifest["capture_mode"],
                "data_class": manifest["provenance"]["data_class"], "event_count": len(recording["events"]),
                "frame_count": len(manifest["frames"]), "bundle_digest": recording["bundle_digest"],
                "outcome_claim": manifest["outcome"]["status"], "warnings": recording["warnings"]}

    def draft_skill(self, recording_id, options=None):
        options = options or {}
        catalog = self._catalog()
        source = catalog["recordings"].get(recording_id)
        if not source:
            raise SkillforgeError("recording_not_found", "Import this recording before drafting a skill.")
        recording = import_bundle(source["path"], self.approval_store if self.approval_store.exists() else None)
        if source["bundle_digest"] != recording["bundle_digest"]:
            raise SkillforgeError("recording_changed", "Recording changed since import. Use new approved evidence.")
        workflow = draft(recording, mode=options.get("mode", "mock"), options=options)
        candidate_id = workflow["skill_id"] + "-r" + str(workflow["revision"]) + "-" + digest(canonical(workflow))[:8]
        target = Path(options.get("out") or self.state / "candidates" / candidate_id).resolve()
        package = write_package(workflow, evidence_map(recording, workflow), target)
        catalog["candidates"][candidate_id] = {"path": str(target)}
        self._save(catalog)
        return {"candidate_id": candidate_id, "skill_id": workflow["skill_id"], "revision": workflow["revision"],
                "path": str(target), "mode": workflow["generation"]["mode"], "status": "candidate", "package": package}

    def validate_skill(self, skill_path):
        return validate_skill(skill_path)

    def export_skill(self, candidate_id, output_dir):
        candidate = self._catalog()["candidates"].get(candidate_id)
        source = Path(candidate["path"]) if candidate else Path(candidate_id)
        if not source.is_dir():
            raise SkillforgeError("candidate_not_found", "Candidate ID or folder is not available.")
        validation = validate_skill(source)
        if validation["status"] == "invalid":
            raise SkillforgeError("invalid_candidate", "Candidate must pass validation before export.")
        workflow = read_json(source / "workflow.json")
        evidence = read_json(source / "evidence-map.json")
        # Portable exports refer to recording IDs; no frames or absolute source paths are copied.
        evidence["local_recording_available"] = False
        target = Path(output_dir) / workflow["skill_id"]
        return write_package(workflow, evidence, target)

    def prepare_run(self, skill_path, bindings, capabilities):
        return prepare_run(skill_path, bindings, capabilities)


def import_recording(bundle_path):
    return SkillForge().import_recording(bundle_path)


def draft_skill(recording_id, options=None):
    return SkillForge().draft_skill(recording_id, options)


def export_skill(candidate_id, output_dir):
    return SkillForge().export_skill(candidate_id, output_dir)
