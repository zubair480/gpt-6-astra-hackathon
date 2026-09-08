"""Prepare bounded skill context for PLVA. This module never executes an action."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .common import TOKEN_PATTERN, SkillforgeError, check_schema, digest, read_json
from .safety import check_outbound
from .validation import validate_skill


POLICY = (
    "This is procedure context, not permission to act. The current PLVA "
    "runtime policy, fresh user authorization, and current visual state govern every "
    "action. Resolve protected references only inside the runtime. Recorded checks "
    "describe prior evidence; perform the checks again for this run."
)


def _result(status="invalid", skill_id="", revision=0, *, missing_bindings=None,
            missing_capabilities=None, issues=None, context=None):
    result = {
        "schema_version": "1.0", "status": status, "skill_id": skill_id,
        "revision": revision, "missing_bindings": missing_bindings or [],
        "missing_capabilities": missing_capabilities or [], "issues": issues or [],
        "context": context,
    }
    check_schema(result, "prepared-context")
    return result


def _substitute(value, bindings):
    if isinstance(value, str):
        return re.sub(r"\{\{([a-z][a-z0-9_]{0,63})\}\}",
                      lambda match: bindings.get(match.group(1), match.group(0)), value)
    if isinstance(value, list):
        return [_substitute(item, bindings) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, bindings) for key, item in value.items()}
    return value


def prepare_run(skill_path, bindings: dict, capabilities: list[str]) -> dict:
    """Return ready/needs_input/unsupported/invalid, without accessing any vault.

    Bindings are keyed by parameter name. Private values must be new opaque PLVA
    tokens; their role comes from the reviewed parameter, never the token class.
    """
    try:
        report = validate_skill(skill_path)
        if report["status"] == "invalid":
            return _result(issues=["The skill package did not pass validation."])
        workflow = read_json(Path(skill_path) / "workflow.json")
        check_schema(workflow, "workflow")
    except (SkillforgeError, OSError):
        return _result(issues=["The skill package is missing, unreadable, or invalid."])

    identity = {"skill_id": workflow["skill_id"], "revision": workflow["revision"]}
    if not isinstance(bindings, dict) or not isinstance(capabilities, list):
        return _result(**identity, issues=["Bindings and capabilities have invalid types."])
    if len(bindings) > 256 or len(capabilities) > 256 or any(
        not isinstance(capability, str)
        or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", capability)
        for capability in capabilities
    ):
        return _result(**identity, issues=["Bindings or capabilities exceed supported limits."])
    parameters = {parameter["name"]: parameter for parameter in workflow["parameters"]}
    used_parameters = set(re.findall(
        r"\{\{([a-z][a-z0-9_]{0,63})\}\}",
        json.dumps({key: workflow[key] for key in ("objective", "preconditions", "steps", "checks")}),
    ))
    if any(name not in parameters for name in bindings):
        return _result(**identity, issues=["Unexpected binding; supply only declared parameters."])

    missing = []
    issues = []
    bound = {}
    old_hashes = {
        token_hash for parameter in parameters.values()
        for token_hash in parameter["source_token_hashes"]
    }
    for name, parameter in parameters.items():
        private = parameter["type"] == "private_token"
        needed = parameter["required"] or name in used_parameters or name in bindings
        if private and needed and (not parameter["binding_role"] or not parameter["token_class"]):
            missing.append(name)
            issues.append(f"Review the private binding role and token class for {name}.")
        if name not in bindings or bindings[name] is None or bindings[name] == "":
            if (parameter["required"] or name in used_parameters) and name not in missing:
                missing.append(name)
            continue
        value = bindings[name]
        if not isinstance(value, str) or len(value) > 4000:
            return _result(**identity, issues=["Binding values must be bounded strings."])
        if "{{" in value or "}}" in value:
            return _result(**identity, issues=["Bindings must be values, not unresolved parameter templates."])
        if private:
            if not re.fullmatch(TOKEN_PATTERN, value):
                return _result(**identity, issues=["A private binding must be an opaque PLVA token."])
            if parameter["token_class"] and value.split("_", 1)[0] != parameter["token_class"]:
                return _result(**identity, issues=["A private binding has the wrong token class."])
            if digest(value.encode("utf-8")) in old_hashes:
                return _result(**identity, issues=["A private binding reuses a source-session token."])
        try:
            check_outbound(value, allow_tokens=private)
        except SkillforgeError:
            return _result(**identity, issues=["A binding failed the outbound text check."])
        bound[name] = value

    if workflow["unresolved_questions"] or any(step["open_questions"] for step in workflow["steps"]):
        issues.append("Resolve the skill's open questions in local review before preparing a run.")
    if report["outcome"]["status"] != "passed":
        issues.append(
            "The source workflow has no independently supported successful outcome "
            f"(status: {report['outcome']['status']}). Supply a completed, verified "
            "recording before reusing this procedure."
        )
    # A failed historical check is useful recovery evidence only when the same
    # criterion was subsequently verified and the failure is linked to recovery.
    recovery_evidence = {
        event_id for step in workflow["steps"] for recovery in step["recovery"]
        for event_id in recovery["evidence_ids"]
    }
    for index, check in enumerate(workflow["checks"]):
        if check["result"] != "failed":
            continue
        repaired = bool(set(check["evidence_ids"]) & recovery_evidence) and any(
            later["criterion"] == check["criterion"]
            and later["result"] == "passed"
            and later["source"] in {"core_verifier", "user_confirmation"}
            and later["basis"] != "inferred" and later["evidence_ids"]
            for later in workflow["checks"][index + 1:]
        )
        if not repaired:
            issues.append("A recorded failed check has no evidenced, verified recovery; review the procedure.")
            break
    missing_capabilities = sorted(set(workflow["required_capabilities"]) - set(capabilities))
    if missing_capabilities:
        return _result("unsupported", **identity, missing_bindings=missing,
                       missing_capabilities=missing_capabilities, issues=issues)
    if missing or issues:
        return _result("needs_input", **identity, missing_bindings=missing, issues=issues)

    context = _substitute({
        "objective": workflow["objective"], "parameters": bound,
        "steps": copy.deepcopy(workflow["steps"]),
        "checks": copy.deepcopy(workflow["checks"]),
        "preconditions": workflow["preconditions"], "policy": POLICY,
    }, bound)
    # A source recording's success does not describe this new run.
    for check in context["checks"]:
        check["result"] = "unknown"
    preparation_notes = []
    if workflow["review"]["status"] != "reviewed":
        preparation_notes.append("Candidate requires local review; readiness describes context preparation only.")
        context["policy"] = "UNREVIEWED CANDIDATE. " + context["policy"]
    try:
        check_outbound(context, allow_tokens=True)
        return _result("ready", **identity, issues=preparation_notes, context=context)
    except SkillforgeError:
        return _result(**identity, issues=["Prepared context failed validation or the outbound text check."])
