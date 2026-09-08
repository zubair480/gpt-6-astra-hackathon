"""Separate package correctness, source outcome, review, and real rerun evidence."""
from __future__ import annotations

import re
from pathlib import Path

from .common import SkillforgeError, check_schema, read_json
from .safety import findings

PACKAGE_FILES = {"SKILL.md", "workflow.json", "evidence-map.json", "validation.json"}
VARIABLE = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


def validate_data(workflow: dict, evidence_map: dict) -> dict:
    errors = []
    privacy_errors = findings(workflow) + findings(evidence_map)
    valid_schema = True
    for value, name in [(workflow, "workflow"), (evidence_map, "evidence-map")]:
        try:
            check_schema(value, name)
        except SkillforgeError:
            errors.append(f"{name}_schema_invalid")
            valid_schema = False
    review = {"status": "candidate", "accepted_revision": None}
    outcome = {"status": "unknown", "supporting_check_ids": [], "source": "none"}
    warnings = ["Text scanning does not verify image redaction.", "Actual changed-layout execution through the main runtime is pending."]
    if valid_schema:
        review = workflow["review"]
        params = workflow["parameters"]
        names = [p["name"] for p in params]
        if len(names) != len(set(names)):
            errors.append("duplicate_parameter")
        for p in params:
            if (p["visibility"] == "private") != (p["type"] == "private_token"):
                errors.append("parameter_privacy_type_mismatch")
            if p["visibility"] == "private" and not p["source_token_hashes"]:
                errors.append("private_parameter_missing_provenance")
            if p["visibility"] == "private" and not p["token_class"]:
                warnings.append("A private token class requires explicit review before replay.")
            if p["binding_role"] is None:
                warnings.append("A parameter role requires explicit review before replay.")
        reusable = str({k: workflow[k] for k in ["objective", "steps", "checks", "preconditions"]})
        if set(VARIABLE.findall(reusable)) - set(names):
            errors.append("undeclared_variable")
        if re.search(r"\{\{(?![a-z][a-z0-9_]*\}\})", reusable):
            errors.append("malformed_variable")
        steps = workflow["steps"]
        checks = workflow["checks"]
        targets = [s["step_id"] for s in steps] + [c["check_id"] for c in checks]
        if not steps:
            errors.append("empty_procedure")
        if len(targets) != len(set(targets)):
            errors.append("duplicate_step_or_check")
        event_ids = set(evidence_map["event_ids"])
        frame_ids = set(evidence_map["frame_ids"])
        check_ids = {c["check_id"] for c in checks}
        links = evidence_map["links"]
        link_ids = [link["target_id"] for link in links]
        if len(link_ids) != len(set(link_ids)) or set(link_ids) != set(targets):
            errors.append("evidence_mapping_targets_mismatch")
        link_by_id = {link["target_id"]: link for link in links}
        for node in steps + checks:
            if set(node["evidence_ids"]) - event_ids:
                errors.append("missing_evidence_reference")
            if not node["evidence_ids"] and node["basis"] == "observed":
                errors.append("observed_without_evidence")
            node_id = node.get("step_id", node.get("check_id"))
            link = link_by_id.get(node_id)
            if link and (set(link["event_ids"]) != set(node["evidence_ids"]) or link["basis"] != node["basis"]):
                errors.append("evidence_mapping_mismatch")
        for link in links:
            if set(link["event_ids"]) - event_ids or set(link["frame_ids"]) - frame_ids:
                errors.append("missing_evidence_reference")
        for step in steps:
            if set(step["check_ids"]) - check_ids:
                errors.append("missing_check_reference")
            for recovery in step["recovery"]:
                if set(recovery["evidence_ids"]) - event_ids:
                    errors.append("missing_recovery_reference")
                if not recovery["evidence_ids"] and recovery["basis"] != "inferred":
                    errors.append("recovery_without_evidence")
            if re.search(r"(?i)(?:click|move|tap)\s+(?:at\s+)?\(?\d+\s*,\s*\d+", step["instruction"]):
                errors.append("coordinate_primary_instruction")
        if workflow["generation"]["bundle_digest"] != evidence_map["bundle_digest"]:
            errors.append("source_digest_mismatch")
        if workflow["source_recording_ids"] != [evidence_map["recording_id"]]:
            errors.append("source_recording_mismatch")
        if review["status"] == "reviewed" and review["accepted_revision"] != workflow["revision"]:
            errors.append("acceptance_revision_mismatch")
        if review["status"] == "candidate" and review["accepted_revision"] is not None:
            errors.append("candidate_has_acceptance")
        if workflow["validation_status"] != review["status"]:
            errors.append("unsupported_validation_claim")
        claimed = evidence_map["outcome"]
        if set(claimed["check_ids"]) - check_ids:
            errors.append("missing_outcome_check")
        supported = [c["check_id"] for c in checks if c["check_id"] in claimed["check_ids"] and c["result"] == "passed" and c["source"] in {"core_verifier", "user_confirmation"} and c["evidence_ids"] and c["basis"] != "inferred"]
        if claimed["status"] == "passed" and claimed["check_ids"] and set(supported) == set(claimed["check_ids"]):
            outcome = {"status": "passed", "supporting_check_ids": supported, "source": "synthetic_fixture" if evidence_map["data_class"] == "synthetic" else "trusted_recording"}
        elif claimed["status"] in {"failed", "cancelled"}:
            outcome = {"status": claimed["status"], "supporting_check_ids": [], "source": "synthetic_fixture" if evidence_map["data_class"] == "synthetic" else "trusted_recording"}
        elif claimed["status"] == "passed":
            warnings.append("The recorded success claim lacks independent supporting checks; outcome remains unknown.")
        if workflow["unresolved_questions"] or any(s["open_questions"] for s in steps):
            warnings.append("Open questions remain for review.")
        if any(s["basis"] == "inferred" for s in steps):
            warnings.append("Some procedure steps are inferred, not observed actions.")
        if workflow["generation"]["mode"] == "mock":
            warnings.append("Candidate was generated by the deterministic mock, not Astra.")
    errors = list(dict.fromkeys(errors))
    privacy_errors = list(dict.fromkeys(privacy_errors))
    status = "invalid" if errors or privacy_errors else review["status"]
    return {"schema_version": "1.0", "status": status,
            "structure": {"passed": not errors, "errors": errors},
            "privacy": {"passed": not privacy_errors, "errors": privacy_errors, "image_redaction_verified": False},
            "outcome": outcome, "review": review,
            "reruns": [{"kind": "live_runner", "status": "pending", "revision": workflow.get("revision", 1) if valid_schema else 1, "details": "Main PLVA runtime integration required; no actual changed-layout execution recorded."}],
            "warnings": list(dict.fromkeys(warnings))}


def validate_skill(skill_path) -> dict:
    root = Path(skill_path)
    if root.is_symlink() or not root.is_dir():
        raise SkillforgeError("invalid_package", "Skill folder is missing or linked.")
    workflow = read_json(root / "workflow.json")
    evidence = read_json(root / "evidence-map.json")
    report = validate_data(workflow, evidence)
    if {p.name for p in root.iterdir()} != PACKAGE_FILES or any(p.is_symlink() or not p.is_file() for p in root.iterdir()):
        report["structure"]["errors"].append("unexpected_or_missing_package_files")
    try:
        path = root / "SKILL.md"
        if path.is_symlink() or path.stat().st_size > 100000:
            raise ValueError()
        markdown = path.read_text(encoding="utf-8")
        report["privacy"]["errors"].extend(findings(markdown))
        if report["structure"]["passed"]:
            from .exporter import renders_matching_workflow
            if not renders_matching_workflow(markdown, workflow):
                report["structure"]["errors"].append("markdown_workflow_mismatch_use_review_edit")
        saved = read_json(root / "validation.json")
        check_schema(saved, "validation")
        report["privacy"]["errors"].extend(findings(saved))
        # Keep only independently recorded rerun records on the current revision.
        # This file is local review data, never permission to execute.
        if isinstance(workflow, dict):
            report["reruns"] = [r for r in saved["reruns"] if r["revision"] == workflow.get("revision") or r["status"] == "invalidated"]
            if not any(r["kind"] == "live_runner" and r["status"] == "pending" for r in report["reruns"]):
                report["reruns"].append({"kind": "live_runner", "status": "pending", "revision": workflow.get("revision", 1), "details": "Rerun reports are local assertions; the live integration result must be supplied by the core."})
    except (OSError, ValueError, UnicodeError, SkillforgeError):
        report["structure"]["errors"].append("invalid_markdown_or_validation_file")
    report["privacy"]["errors"].extend(findings(root.name))
    for name in (p.name for p in root.iterdir()):
        report["privacy"]["errors"].extend(findings(name))
    report["structure"]["errors"] = list(dict.fromkeys(report["structure"]["errors"]))
    report["privacy"]["errors"] = list(dict.fromkeys(report["privacy"]["errors"]))
    report["structure"]["passed"] = not report["structure"]["errors"]
    report["privacy"]["passed"] = not report["privacy"]["errors"]
    if not report["structure"]["passed"] or not report["privacy"]["passed"]:
        report["status"] = "invalid"
    return report
