"""Turn approved evidence into a conservative, editable workflow candidate."""
from __future__ import annotations

import copy
import re

from .common import SkillforgeError, TOKEN_PATTERN, canonical, check_schema, digest


def _unique(values):
    return list(dict.fromkeys(values))


def _name(value):
    value = re.sub(r"[^a-z0-9_]", "_", value.lower()).strip("_")
    return (value if value and value[0].isalpha() else "input_" + value)[:60]


def _parameterize(recording, retained_events=None):
    """Only host-approved role metadata assigns semantic private roles."""
    trusted = recording["approval"].get("role_hints_trusted", False)
    events = recording["events"]
    retained_events = events if retained_events is None else retained_events
    recorded_values = [item["operation"].get("text", "") for item in retained_events if item["type"] == "action" and item["status"] == "executed"]
    input_text = "\n".join([recording["manifest"]["task"]] + recorded_values + [item["criterion"] for item in retained_events if item["type"] == "check"])
    tokens = sorted(set(re.findall(TOKEN_PATTERN, canonical({"task": recording["manifest"]["task"], "events": events}).decode())))
    metadata = {}
    for event in events:
        for item in event.get("tokens", []):
            metadata.setdefault(item["token"], []).append(item)
    params, replacements, questions = [], {}, []
    used_names = set()

    def allocate(preferred):
        base = _name(preferred)
        result = base
        i = 2
        while result in used_names:
            result = f"{base}_{i}"
            i += 1
        used_names.add(result)
        return result

    for number, token in enumerate(tokens, 1):
        entries = metadata.get(token, [])
        roles = {item.get("role_hint") for item in entries if item.get("role_hint")}
        role = next(iter(roles)) if trusted and len(roles) == 1 else None
        classes = {item["class"] for item in entries}
        token_class = next(iter(classes)) if len(classes) == 1 and classes == {token.split("_")[0]} else (token.split("_")[0] if not classes else None)
        required = token in input_text
        name = allocate(role or f"private_input_{number}")
        if role is None and required:
            questions.append(f"Confirm the binding role of {{{{{name}}}}}; token class alone does not identify its business meaning.")
        if token_class is None and required:
            questions.append(f"Resolve conflicting token class metadata for {{{{{name}}}}} before reuse.")
        params.append({"name": name, "type": "private_token", "visibility": "private", "required": required,
                       "binding_role": role, "token_class": token_class, "source_token_hashes": [digest(token.encode())]})
        replacements[token] = "{{" + name + "}}" if required else "[unrelated protected context omitted]"

    public_roles = {}
    for event in events:
        for item in event.get("public_values", []):
            value = item["value"]
            used_value = value in recorded_values or (value and re.search(r"(?<![\w.-])" + re.escape(value) + r"(?![\w-])", recording["manifest"]["task"]))
            if value and not re.search(TOKEN_PATTERN, value) and used_value:
                public_roles.setdefault(value, set()).add(item["role_hint"])
    for number, (value, roles) in enumerate(public_roles.items(), 1):
        role = next(iter(roles)) if trusted and len(roles) == 1 else None
        name = allocate(role or f"public_input_{number}")
        if role is None:
            questions.append(f"Confirm the binding role of {{{{{name}}}}}; the public value has untrusted or conflicting role metadata.")
        params.append({"name": name, "type": "string", "visibility": "public", "required": True,
                       "binding_role": role, "token_class": None, "source_token_hashes": []})
        replacements[value] = "{{" + name + "}}"

    replacement_pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(old) for old in sorted(replacements, key=len, reverse=True)) + r")(?![\w-])") if replacements else None
    identity_fields = {"event_id", "action_id", "step_id", "check_id", "frame_id", "evidence_ids", "check_ids", "before_event_id", "after_event_id", "binding_role", "name", "role_hint"}

    def replace(value):
        if isinstance(value, str):
            if not replacement_pattern:
                return value
            # One pass avoids cascading substitutions; preserve existing placeholders.
            return "".join(part if part.startswith("{{") else replacement_pattern.sub(lambda match: replacements[match.group(0)], part)
                           for part in re.split(r"(\{\{[a-z][a-z0-9_]*\}\})", value))
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: item if key in identity_fields else replace(item) for key, item in value.items()}
        return value

    return params, questions, replace


def _step_id(event_id):
    # Stable under window overlap and changes to preceding event count.
    return "step-" + digest(event_id.encode())[:16]


def _instruction(operation, app=None):
    target = operation["target_hint"]
    value = operation.get("text")
    kind = operation["kind"]
    location = f" in {app}" if app else " in the current application"
    if kind == "type":
        return f"Locate the editable field for {target}{location} and enter {value}. Use the current run's input and compare the populated field with that input before continuing." if value else f"Locate the editable field for {target}{location}; establish its missing input before populating it."
    if kind == "select":
        return f"Locate {target}{location}, select {value or target}, and confirm that the selection is retained."
    return {"navigate": f"Open the workflow for {target}{location} and confirm that its current form or page is ready.",
            "click": f"Locate the control whose function is {target}{location}. Activate it once, then inspect the resulting state before taking another action.",
            "wait": f"Wait for {target}{location} to become ready; inspect the state before continuing.",
            "inspect": f"Inspect {target}{location} and compare it with the recorded checkpoint."}[kind]


def _correction_analysis(events):
    """Remove known wrong writes only when explicit correction links establish why."""
    index = {item["event_id"]: item for item in events}
    superseded, repaired_by, recovered_checks = set(), {}, set()
    for correction in (item for item in events if item["type"] == "correction"):
        refs = set(correction["evidence_ids"])
        for ref in list(refs):
            refs.update(index.get(ref, {}).get("evidence_ids", []))
        previous_writes = [item for item in events if item["type"] == "action" and item["status"] == "executed"
                           and item["operation"]["kind"] in {"type", "select"} and item["sequence"] < correction["sequence"]
                           and (item["event_id"] in refs or item.get("after_event_id") in refs)]
        for previous in previous_writes:
            replacement = next((item for item in events if item["sequence"] > correction["sequence"] and item["type"] == "action"
                                and item["status"] == "executed" and item["operation"]["kind"] == previous["operation"]["kind"]
                                and item["operation"]["target_hint"].casefold() == previous["operation"]["target_hint"].casefold()), None)
            if replacement is None:
                continue
            superseded.add(previous["event_id"])
            repaired_by[replacement["event_id"]] = correction
            old_refs = {previous["event_id"], previous.get("after_event_id")}
            new_refs = {replacement["event_id"], replacement.get("after_event_id")}
            failures = [item for item in events if item["type"] == "check" and item["result"] == "failed" and old_refs.intersection(item["evidence_ids"])]
            for failure in failures:
                if any(item["type"] == "check" and item["result"] == "passed" and item["source"] != "model_interpretation"
                       and item["sequence"] > replacement["sequence"] and item["criterion"] == failure["criterion"]
                       and new_refs.intersection(item["evidence_ids"]) for item in events):
                    recovered_checks.add(failure["check_id"])
    return superseded, repaired_by, recovered_checks


def draft(recording, mode="mock", options=None):
    """Create a candidate; no model claim or review is treated as execution."""
    from .ingest import import_bundle
    from .safety import check_outbound
    from .timeline import build_timeline

    options = options or {}
    if mode not in {"mock", "astra"}:
        raise SkillforgeError("unsupported_mode", "Use mock or astra synthesis mode.")
    fresh = import_bundle(recording["bundle_path"], approval_store=recording.get("approval_store"))
    if fresh["bundle_digest"] != recording["bundle_digest"]:
        raise SkillforgeError("recording_changed", "The recording changed after import; import it again before drafting.")
    recording = fresh
    check_outbound({"manifest": recording["manifest"], "events": recording["events"]}, allow_tokens=True)
    timeline = build_timeline(recording, window_size=options.get("window_size", 24), overlap=options.get("overlap", 4))
    events = timeline["events"]
    index = {event["event_id"]: event for event in events}
    superseded, repaired_by, recovered_checks = _correction_analysis(events)
    retained_events = [event for event in events if event["event_id"] not in superseded]
    params, questions, replace = _parameterize(recording, retained_events)
    checks = []
    for event in events:
        if event["type"] == "check":
            supported = bool(event["evidence_ids"])
            checks.append({"check_id": event["check_id"], "criterion": event["criterion"], "source": event["source"],
                           "result": event["result"] if supported else "unknown", "evidence_ids": _unique([event["event_id"]] + event["evidence_ids"]),
                           "basis": {"core_verifier": "observed", "user_confirmation": "user_confirmed", "model_interpretation": "inferred"}[event["source"]] if supported else "inferred"})
            if not supported:
                questions.append(f"Check {event['check_id']} has no supporting evidence; supply an independent observation or verification before treating it as passed.")
            elif event["result"] == "failed" and event["check_id"] not in recovered_checks:
                questions.append(f"Check {event['check_id']} failed without a demonstrated verified recovery; establish the correct result before reuse.")
    screenshots_only = recording["manifest"]["capture_mode"] == "screenshots_only"
    steps = []
    if screenshots_only:
        observations = timeline["observations"]
        for before, after in zip(observations, observations[1:]):
            steps.append({"step_id": _step_id(after["event_id"]), "goal": "Reach the next recorded visual state",
                          "preconditions": [before.get("text") or "Inspect the preceding recorded frame."],
                          "instruction": "Infer and review the transition between these recorded states before attempting it; no action log establishes the intervening operation.",
                          "target_hints": [], "postcondition": after.get("text") or "Compare the resulting screen with the next recorded frame.",
                          "check_ids": [], "recovery": [], "evidence_ids": _unique(before.get("event_ids", [before["event_id"]]) + after.get("event_ids", [after["event_id"]])),
                          "basis": "inferred", "open_questions": ["Which action caused this transition? Screenshots alone do not establish it."]})
        if not steps and observations:
            event = observations[0]
            steps.append({"step_id": _step_id(event["event_id"]), "goal": "Review the recorded state", "preconditions": [],
                          "instruction": "Review the available frame and supply the missing workflow actions.", "target_hints": [],
                          "postcondition": event.get("text") or "Recorded frame inspected.", "check_ids": [], "recovery": [],
                          "evidence_ids": [event["event_id"]], "basis": "inferred", "open_questions": ["A single frame does not establish a workflow."]})
        questions.append("Recorded images establish visual states; intervening actions and causal links require review.")
    else:
        failed_states = {item["after_event_id"] for item in events if item["type"] == "action" and (item["status"] == "failed" or item["event_id"] in superseded) and item.get("after_event_id")}
        for event in events:
            if event["type"] != "action" or event["status"] != "executed" or event["event_id"] in superseded:
                continue
            before = index.get(event.get("before_event_id"), {})
            after = index.get(event.get("after_event_id"), {})
            refs = _unique([event["event_id"]] + [event[key] for key in ("before_event_id", "after_event_id") if key in event])
            step_checks = [check["check_id"] for check in checks if event["event_id"] in check["evidence_ids"] and check["check_id"] not in recovered_checks]
            app = after.get("app") or before.get("app")
            preconditions = ["Current recorded context: " + before["text"]] if before.get("text") else []
            if event.get("before_event_id") in failed_states:
                preconditions = ["Inspect the current form and the source task."]
            operation = event["operation"]
            target = operation["target_hint"]
            relevant_guidance = next((item for item in reversed(events) if item["type"] == "correction" and item["sequence"] < event["sequence"]
                                      and target.casefold() in item["text"].casefold()), None)
            if operation["kind"] == "select" and relevant_guidance:
                preconditions.append("Recorded source guidance: " + relevant_guidance["text"])
                refs.append(relevant_guidance["event_id"])
            step_questions = [] if after else ["What visible result confirms this action succeeded?"]
            if event["operation"]["kind"] == "type" and not event["operation"].get("text"):
                step_questions.append("Which value belongs in this field? The typing value was not recorded.")
            goal = {"type": "Populate ", "select": "Set the requested choice for ", "navigate": "Reach ", "click": "Complete the recorded transition for ", "wait": "Wait until ready: ", "inspect": "Verify "}[operation["kind"]] + target
            hints = [target] + (["Application: " + app] if app else [])
            if operation["kind"] in {"type", "select"}:
                hints.append("Identify the field by its label and purpose in the current layout.")
            elif operation["kind"] == "click":
                hints.append("Identify the control by its function and resulting state; its label may differ.")
            postcondition = "Confirm the current run reaches this state: " + after["text"] if after.get("text") else "Postcondition was not recorded; inspect the current state before continuing."
            if operation["kind"] == "type" and operation.get("text"):
                postcondition += f" Verify that {target} matches the current input {operation['text']}."
            steps.append({"step_id": _step_id(event["event_id"]), "goal": goal,
                          "preconditions": preconditions, "instruction": _instruction(operation, app),
                          "target_hints": hints, "postcondition": postcondition,
                          "check_ids": step_checks, "recovery": [], "evidence_ids": refs, "basis": "observed",
                          "open_questions": step_questions})
        # Failures remain evidence and become recoveries, never mandatory replay operations.
        for correction in [item for item in events if item["type"] == "correction"]:
            failed = [index[ref] for ref in correction["evidence_ids"] if ref in index and index[ref]["type"] == "action" and index[ref]["status"] == "failed"]
            candidates = []
            for failure in failed:
                candidates.extend(step for step in steps if failure["operation"]["target_hint"] in step["target_hints"])
            if not candidates:
                next_event = next((item for item in events if item["sequence"] > correction["sequence"] and item["type"] == "action" and item["status"] == "executed"), None)
                candidates = [step for step in steps if next_event and step["step_id"] == _step_id(next_event["event_id"])]
            repaired = next((event_id for event_id, source in repaired_by.items() if source["event_id"] == correction["event_id"]), None)
            if repaired:
                candidates = [step for step in steps if step["step_id"] == _step_id(repaired)]
            failure_observations = [index.get(item.get("after_event_id"), {}) for item in failed]
            historical_checks = [item for item in events if item["type"] == "check" and item["check_id"] in recovered_checks
                                 and set(item["evidence_ids"]) & set(correction["evidence_ids"])]
            if historical_checks:
                trigger = "If the check fails: " + historical_checks[0]["criterion"]
            elif any(item.get("text") for item in failure_observations):
                trigger = "If the current form shows the recorded error: " + next(item["text"] for item in failure_observations if item.get("text"))
            else:
                trigger = "If the same recorded problem recurs"
            recovery = {"instruction": trigger + " — " + correction["text"] + " Recheck the corrected state before continuing.",
                        "basis": "user_confirmed" if correction["source"] == "user" else "observed",
                        "evidence_ids": _unique([correction["event_id"]] + correction["evidence_ids"] + [item["event_id"] for item in historical_checks])}
            if candidates:
                candidates[0]["recovery"].append(recovery)
            else:
                questions.append("A recorded correction could not be attached to a successful step; inspect its source evidence.")
    if not checks or not any(check["source"] != "model_interpretation" and check["result"] == "passed" and check["basis"] != "inferred" for check in checks):
        questions.append("No independent outcome check establishes that the demonstrated task succeeded.")
    outcome = recording["manifest"]["outcome"]
    if outcome["status"] in {"unknown", "failed", "cancelled"}:
        questions.append(f"The recorded task outcome is {outcome['status']}; confirm task completion and resolve its gaps before reuse.")
    if outcome["status"] == "passed" and (not outcome["check_ids"] or any(not any(check["check_id"] == check_id and check["result"] == "passed" and check["basis"] != "inferred" for check in checks) for check_id in outcome["check_ids"])):
        questions.append("The recorded completion claim lacks a complete set of independent passing outcome checks.")
    title = replace(recording["manifest"]["task"]).rstrip(". ")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:63].rstrip("-") or "recorded-workflow"
    capabilities = _unique(["observe"] + [event["operation"]["kind"] for event in retained_events if event["type"] == "action" and event["status"] == "executed"])
    workflow = {"schema_version": "1.0", "skill_id": slug, "revision": 1, "title": title, "objective": title + ".",
                "parameters": params, "preconditions": ["Open the source task in the current workspace and inspect its current state."],
                "required_capabilities": capabilities, "steps": replace(steps), "checks": replace(checks), "unresolved_questions": questions,
                "source_recording_ids": [recording["manifest"]["recording_id"]],
                "generation": {"mode": mode, "model": "gpt-6-astra" if mode == "astra" else None, "bundle_digest": recording["bundle_digest"],
                               "window_count": max(1, len(timeline["windows"])), "warnings": _unique(timeline.get("warnings", []) + ["Live changed-workspace execution has not been tested."])},
                "review": {"status": "candidate", "accepted_revision": None}, "validation_status": "candidate"}
    if mode == "astra":
        from .model_adapter import refine_workflow
        workflow = refine_workflow(recording, timeline, workflow, replace, options)
    check_schema(workflow, "workflow")
    check_outbound(workflow)
    return copy.deepcopy(workflow)
