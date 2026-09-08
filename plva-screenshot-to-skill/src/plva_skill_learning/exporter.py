"""Portable four-file skill export. Exporting grants no runtime authority."""
from __future__ import annotations

import json
from pathlib import Path

from .common import SkillforgeError, write_json


def _recovered_check(workflow, check):
    if check["result"] != "failed":
        return False
    position = workflow["checks"].index(check)
    later_pass = any(other["result"] == "passed" and other["source"] != "model_interpretation" and other["criterion"] == check["criterion"]
                     and other["basis"] != "inferred" and other["evidence_ids"]
                     for other in workflow["checks"][position + 1:])
    linked_recovery = any(set(recovery["evidence_ids"]) & set(check["evidence_ids"]) for step in workflow["steps"] for recovery in step["recovery"])
    return later_pass and linked_recovery


def render_skill(workflow):
    description = "Use this workflow to " + workflow["objective"].rstrip(".")[:650] + ". Review unresolved questions and bind inputs from the current workspace."
    lines = ["---", "name: " + workflow["skill_id"], "description: " + json.dumps(description, ensure_ascii=True), "---", "", "# " + workflow["title"], "", workflow["objective"], "", "## Inputs", ""]
    if not any(param["required"] for param in workflow["parameters"]):
        lines.append("No required parameter bindings were identified in the recording.")
    for param in workflow["parameters"]:
        if not param["required"]:
            continue
        role = param["binding_role"] or "unresolved role; ask before reuse"
        lines.append(f"- `{{{{{param['name']}}}}}`: {param['type']}; {'required' if param['required'] else 'optional'}; {role}.")
    lines.extend(["", "## Before starting", ""])
    lines.extend("- " + condition for condition in workflow["preconditions"])
    if workflow["unresolved_questions"]:
        lines.append("- Resolve the questions below before preparing this skill for another run.")
    lines.extend(["", "## Procedure", ""])
    for number, step in enumerate(workflow["steps"], 1):
        lines.append(f"{number}. **{step['goal']}**")
        lines.append("")
        for precondition in step["preconditions"]:
            lines.append(f"   Before: {precondition}")
        lines.append(f"   Do: {step['instruction']}")
        if step["target_hints"]:
            lines.append("   Locate: " + "; ".join(step["target_hints"]))
        lines.append(f"   Verify: {step['postcondition']}")
        lines.append(f"   Evidence: {step['basis']}; {', '.join(step['evidence_ids']) or 'missing'}.")
        for recovery in step["recovery"]:
            lines.append(f"   Recovery ({recovery['basis']}): {recovery['instruction']}")
        for question in step["open_questions"]:
            lines.append(f"   Review: {question}")
        lines.append("")
    lines.extend(["", "## Outcome checks", ""])
    if not workflow["checks"]:
        lines.append("No independent outcome checks were recorded; establish a current-run success check before relying on the result.")
    for check in workflow["checks"]:
        label = "Historical recovery evidence" if _recovered_check(workflow, check) else "Verify in the new run"
        lines.append(f"- {label}: {check['criterion']} (recording: {check['result']}; source: {check['source']}; {check['check_id']})")
    if workflow["unresolved_questions"]:
        lines.extend(["", "## Questions before reuse", ""])
        lines.extend("- " + question for question in workflow["unresolved_questions"])
    lines.extend(["", "## Execution boundary", "", "Bind private inputs to fresh opaque references supplied by PLVA. The current runtime owns permissions, approvals, and execution. This package grants none. Inspect semantic targets in the current visual state; historical coordinates are not replay instructions.", "", "The recording is evidence of one demonstration. Review acceptance is not a successful rerun. Consult `validation.json` for the specific checks performed and pending live execution.", "", "Detailed step references are in `evidence-map.json`; the local source recording may be unavailable in another workspace.", ""])
    return "\n".join(lines)


def _render_legacy_skill_v1(workflow):
    """Frozen renderer shipped with v1, retained only to validate existing packages."""
    description = "Use this workflow to " + workflow["objective"].rstrip(".")[:650] + ". Review unresolved questions and bind inputs from the current workspace."
    lines = ["---", "name: " + workflow["skill_id"], "description: " + json.dumps(description, ensure_ascii=True), "---", "", "# " + workflow["title"], "", workflow["objective"], "", "## Inputs", ""]
    if not workflow["parameters"]:
        lines.append("No parameter bindings were identified in the recording.")
    for param in workflow["parameters"]:
        role = param["binding_role"] or "unresolved role; ask before reuse"
        lines.append(f"- `{{{{{param['name']}}}}}`: {param['type']}; {'required' if param['required'] else 'optional'}; {role}.")
    lines.extend(["", "## Procedure", ""])
    for number, step in enumerate(workflow["steps"], 1):
        lines.append(f"{number}. {step['instruction']} ({step['basis']}; evidence: {', '.join(step['evidence_ids']) or 'missing'})")
        lines.append(f"   Checkpoint: {step['postcondition']}")
        for recovery in step["recovery"]:
            lines.append(f"   Recovery ({recovery['basis']}): {recovery['instruction']}")
        for question in step["open_questions"]:
            lines.append(f"   Review: {question}")
    lines.extend(["", "## Outcome checks", ""])
    if not workflow["checks"]:
        lines.append("No independent outcome checks were recorded; establish a current-run success check before relying on the result.")
    for check in workflow["checks"]:
        lines.append(f"- {check['criterion']} (recording: {check['result']}; source: {check['source']}; {check['check_id']})")
    if workflow["unresolved_questions"]:
        lines.extend(["", "## Questions before reuse", ""])
        lines.extend("- " + question for question in workflow["unresolved_questions"])
    lines.extend(["", "## Execution boundary", "", "Bind private inputs to fresh opaque references supplied by PLVA. The current runtime owns permissions, approvals, and execution. This package grants none. Inspect semantic targets in the current visual state; historical coordinates are not replay instructions.", "", "The recording is evidence of one demonstration. Review acceptance is not a successful rerun. Consult `validation.json` for the specific checks performed and pending live execution.", "", "Detailed step references are in `evidence-map.json`; the local source recording may be unavailable in another workspace.", ""])
    return "\n".join(lines)


def renders_matching_workflow(markdown, workflow):
    """Accept exact known v1 renders; arbitrary Markdown edits still require review."""
    return markdown == render_skill(workflow) or markdown == _render_legacy_skill_v1(workflow)


def write_package(workflow, evidence_map, output_path):
    from .safety import check_outbound
    from .validation import validate_data
    report = validate_data(workflow, evidence_map)
    if report["status"] == "invalid":
        raise SkillforgeError("invalid_candidate", "Candidate failed structural or outbound validation; inspect the validation report.")
    markdown = render_skill(workflow)
    check_outbound({"workflow": workflow, "evidence": evidence_map, "markdown": markdown, "validation": report})
    target = Path(output_path).absolute()
    check_outbound(str(target))
    if target.exists() or target.is_symlink():
        raise SkillforgeError("output_exists", "Export requires a fresh output directory; use a new revision directory.")
    if any(parent.is_symlink() for parent in target.parents):
        raise SkillforgeError("invalid_output", "Export directory cannot traverse a symbolic link.")
    try:
        target.mkdir(parents=True, exist_ok=False)
        (target / "SKILL.md").write_text(markdown, encoding="utf-8")
        write_json(target / "workflow.json", workflow)
        write_json(target / "evidence-map.json", evidence_map)
        write_json(target / "validation.json", report)
    except OSError:
        raise SkillforgeError("export_failed", "The local package could not be written; select another fresh directory.") from None
    return {"skill_id": workflow["skill_id"], "revision": workflow["revision"], "path": str(target),
            "files": ["SKILL.md", "workflow.json", "evidence-map.json", "validation.json"], "validation": report}
