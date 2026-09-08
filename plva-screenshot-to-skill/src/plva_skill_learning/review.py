"""Local review operations. Each accepted or edited package has a fresh directory."""
from __future__ import annotations

import copy
from pathlib import Path

from .common import SkillforgeError, check_schema, read_json, write_json
from .exporter import write_package
from .validation import validate_skill


EDITABLE_FIELDS = {
    "title", "objective", "parameters", "preconditions", "required_capabilities",
    "steps", "unresolved_questions",
}
STEP_FACTS = {"step_id", "evidence_ids", "basis", "check_ids"}
PARAMETER_FACTS = {"name", "type", "visibility", "token_class", "source_token_hashes"}


def _load(skill_path):
    folder = Path(skill_path)
    report = validate_skill(folder)
    if report["status"] == "invalid":
        raise SkillforgeError("invalid_package", "Review requires a valid skill package.")
    workflow = read_json(folder / "workflow.json")
    evidence = read_json(folder / "evidence-map.json")
    check_schema(workflow, "workflow")
    check_schema(evidence, "evidence-map")
    return workflow, evidence, report


def _display(value):
    """Keep untrusted local text from inserting terminal control sequences."""
    return "".join(character if character in "\n\t" or ord(character) >= 32
                   and ord(character) != 127 else "?" for character in str(value))


def preview(skill_path, recording=None) -> str:
    workflow, evidence, report = _load(skill_path)
    lines = [
        f"{workflow['title']} ({workflow['skill_id']}, revision {workflow['revision']})",
        f"Objective: {workflow['objective']}",
        f"Review: {workflow['review']['status']} | Package: {report['status']}",
        f"Recorded outcome: {report['outcome']['status']}",
        "Inputs:",
    ]
    for parameter in workflow["parameters"]:
        lines.append(
            f"  {parameter['name']}: {parameter['type']}; "
            f"{'required' if parameter['required'] else 'optional'}; "
            f"role={parameter['binding_role'] or 'UNRESOLVED'}"
        )
    lines.append("Timeline:")
    if recording is not None and recording.get("manifest", {}).get("recording_id") == evidence["recording_id"]:
        for event in sorted(recording["events"], key=lambda item: item["sequence"]):
            detail = event.get("status") or event.get("result") or event.get("frame_id", "")
            lines.append(f"  {event['sequence']}: {event['event_id']} {event['type']} {detail}")
    else:
        lines.append("  Local recording not attached; evidence IDs remain available.")
        lines.append("  Source event order: " + ", ".join(evidence["event_ids"]))
    lines.append("Steps:")
    for step in workflow["steps"]:
        lines.extend([
            f"  {step['step_id']} [{step['basis']}]: {step['goal']}",
            f"    Do: {step['instruction']}",
            f"    Target hints: {', '.join(step['target_hints']) or '(none)'}",
            f"    Check: {step['postcondition']}",
            f"    Evidence: {', '.join(step['evidence_ids']) or '(no direct evidence)'}",
        ])
        for recovery in step["recovery"]:
            lines.append(f"    Recovery [{recovery['basis']}]: {recovery['instruction']}")
        for question in step["open_questions"]:
            lines.append(f"    Open question: {question}")
    lines.append("Outcome checks (previous recording only):")
    for check in workflow["checks"]:
        lines.append(f"  {check['check_id']}: {check['criterion']} [{check['source']}: {check['result']}]")
    for question in workflow["unresolved_questions"]:
        lines.append(f"Open question: {question}")
    lines.append("Reruns:")
    for rerun in report["reruns"]:
        lines.append(f"  {rerun['kind']}: {rerun['status']} (revision {rerun['revision']})")
    lines.append("Accepting a skill records local review; it grants no execution permission.")
    return _display("\n".join(lines))


def _check_edit_facts(old, new, evidence):
    if "parameters" in new:
        if not isinstance(new["parameters"], list) or len(new["parameters"]) != len(old["parameters"]):
            raise SkillforgeError("protected_edit", "Preserve the declared parameters; edit their roles or required flags.")
        for before, after in zip(old["parameters"], new["parameters"]):
            if not isinstance(after, dict) or any(after.get(key) != before[key] for key in PARAMETER_FACTS):
                raise SkillforgeError("protected_edit", "A parameter edit cannot change its identity or recorded token facts.")
    if "steps" in new:
        if not isinstance(new["steps"], list) or len(new["steps"]) != len(old["steps"]):
            raise SkillforgeError("protected_edit", "Preserve the step identities when editing this revision.")
        for before, after in zip(old["steps"], new["steps"]):
            if not isinstance(after, dict) or any(after.get(key) != before[key] for key in STEP_FACTS):
                raise SkillforgeError("protected_edit", "A step edit cannot change recorded evidence or check links.")
            if after.get("recovery") != before["recovery"]:
                raise SkillforgeError("protected_edit", "Recorded recovery evidence cannot be rewritten by a shallow patch.")
            if before != after:
                after["basis"] = "user_confirmed"
                for link in evidence["links"]:
                    if link["target_id"] == before["step_id"]:
                        link["basis"] = "user_confirmed"


def edit(skill_path, patch: dict, output_path) -> dict:
    """Apply editable workflow fields, preserving source facts and invalidating reruns."""
    workflow, evidence, previous_report = _load(skill_path)
    if not isinstance(patch, dict) or not patch or set(patch) - EDITABLE_FIELDS:
        raise SkillforgeError("protected_edit", "Patch only editable workflow fields; identity, evidence, and status are protected.")
    patch = copy.deepcopy(patch)
    _check_edit_facts(workflow, patch, evidence)
    updated = copy.deepcopy(workflow)
    updated.update(patch)
    updated["revision"] += 1
    updated["review"] = {"status": "candidate", "accepted_revision": None}
    updated["validation_status"] = "candidate"
    check_schema(updated, "workflow")
    result = write_package(updated, evidence, output_path)
    report_path = Path(output_path) / "validation.json"
    report = read_json(report_path)
    history = [{
        "kind": rerun["kind"], "status": "invalidated", "revision": rerun["revision"],
        "details": "Invalidated by review edit; the new revision needs its own rerun.",
    } for rerun in previous_report["reruns"] if rerun["status"] != "pending"]
    report["reruns"] = (history + report["reruns"])[-256:]
    check_schema(report, "validation")
    write_json(report_path, report)
    result["validation"] = report
    return result


def accept(skill_path, output_path) -> dict:
    """Export a reviewed copy at the same content revision; do not install or run it."""
    workflow, evidence, previous_report = _load(skill_path)
    updated = copy.deepcopy(workflow)
    updated["review"] = {"status": "reviewed", "accepted_revision": updated["revision"]}
    updated["validation_status"] = "reviewed"
    result = write_package(updated, evidence, output_path)
    report = result["validation"]
    report["reruns"] = previous_report["reruns"]
    check_schema(report, "validation")
    write_json(Path(output_path) / "validation.json", report)
    return result
