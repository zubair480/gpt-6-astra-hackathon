"""Rehearse exported skill contracts with bounded local synthetic inputs.

These checks exercise the actual package validator and runner adapter. They do
not operate an application, interpret a changed screenshot, or prove task success.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
import tempfile

from .common import SkillforgeError, canonical, digest, read_json, write_json
from .exporter import write_package
from .runner_adapter import prepare_run
from .safety import findings
from .validation import PACKAGE_FILES, validate_skill


_KNOWN_SYNTHETIC_SOURCE_TOKENS = ("ADDRESS_1_a3f9",)
_LIMITS = [
    "These are local JSON contract checks using synthetic input values, not browser or computer-use runs.",
    "A ready prepared context does not establish task completion or grant permission to act.",
    "Changed-layout execution and live model adaptation still require the main PLVA runtime.",
    "Passing these cases does not establish general safety, image redaction, or performance improvement.",
]


def _snapshot(skill_path):
    root = Path(skill_path)
    if root.is_symlink() or not root.is_dir():
        raise SkillforgeError("invalid_package", "Rehearsal requires an existing local skill package.")
    if {path.name for path in root.iterdir()} != PACKAGE_FILES:
        raise SkillforgeError("invalid_package", "Rehearsal requires the four-file skill package.")
    result = {}
    try:
        for name in sorted(PACKAGE_FILES):
            path = root / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
                raise SkillforgeError("invalid_package", "A rehearsal package file is linked or exceeds the size limit.")
            result[name] = path.read_bytes()
    except OSError:
        raise SkillforgeError("invalid_package", "A rehearsal package file could not be read.") from None
    return result


def _snapshot_digest(snapshot):
    return digest(canonical([
        {"file": name, "sha256": digest(content)} for name, content in sorted(snapshot.items())
    ]))


def package_digest(skill_path) -> str:
    """Bind a report to all four package files, including evidence and review data."""
    return _snapshot_digest(_snapshot(skill_path))


def _write_snapshot(snapshot, target):
    target.mkdir()
    for name, content in snapshot.items():
        (target / name).write_bytes(content)


def _case(case_id, title, change, expectation, category, *, result=None,
          passed=None, details=None, input_preview=None):
    pending = result is None
    actual = "not_run" if pending else result["status"]
    if not pending and passed is None:
        passed = actual == expectation
    status = "pending" if pending else "passed" if passed else "failed"
    details = list(details or [])
    if result:
        # The adapter already returns bounded, sanitized decision messages.
        # Retain only plain diagnostic text, never source values or filesystem paths.
        for issue in result.get("issues", []):
            if (isinstance(issue, str) and len(issue) <= 1000
                    and not findings(issue) and not any(marker in issue for marker in ("/", "\\", "\n", "\r"))):
                details.append("Decision: " + issue)
    output = {
        "case_id": case_id, "title": title, "change": change,
        "expectation": expectation, "actual_status": actual,
        "passed": None if pending else bool(passed), "status": status,
        "details": details, "category": category,
    }
    if input_preview is not None:
        output["input_preview"] = input_preview
    return output


def _used_parameters(workflow):
    return set(re.findall(r"\{\{([a-z][a-z0-9_]*)\}\}", json.dumps({
        key: workflow[key] for key in ("objective", "preconditions", "steps", "checks")
    })))


def _fresh_bindings(workflow):
    bindings = {}
    used_parameters = _used_parameters(workflow)
    old_hashes = {item for parameter in workflow["parameters"] for item in parameter["source_token_hashes"]}
    for index, parameter in enumerate(workflow["parameters"], 1):
        if not parameter["required"] and parameter["name"] not in used_parameters:
            continue
        if parameter["type"] == "private_token":
            token_class = parameter["token_class"]
            if not token_class or not re.fullmatch(r"[A-Z][A-Z0-9]*", token_class):
                return None
            # Generated names are deliberately synthetic and match the real token protocol.
            for attempt in range(16):
                suffix = digest(f"rehearsal:{index}:{attempt}".encode())[:8]
                value = f"{token_class}_{700000 + index}_{suffix}"
                if digest(value.encode()) not in old_hashes:
                    break
            else:
                return None
        else:
            role = parameter["binding_role"] or parameter["name"]
            value = "REHEARSAL-ORDER-205" if "order" in role.lower() else f"REHEARSAL-VALUE-{index}"
        bindings[parameter["name"]] = value
    return bindings


def run_rehearsal(skill_path, *, include_variants=True) -> dict:
    """Evaluate the exact package snapshot and return an honest bounded report.

    Package variants live in a temporary directory and are discarded. Unsupported
    scenario shapes remain pending rather than receiving an artificial pass.
    """
    snapshot = _snapshot(skill_path)
    cases = []
    with tempfile.TemporaryDirectory(prefix="plva-rehearsal-") as temporary:
        temporary = Path(temporary)
        base = temporary / "source"
        _write_snapshot(snapshot, base)
        report = validate_skill(base)
        if report["status"] == "invalid":
            raise SkillforgeError("invalid_package", "Rehearsal requires a package that passes validation.")
        workflow = read_json(base / "workflow.json")
        evidence = read_json(base / "evidence-map.json")
        bindings = _fresh_bindings(workflow)
        capabilities = workflow["required_capabilities"]
        private = next((p for p in workflow["parameters"] if p["name"] == "customer_shipping_address"), None)
        if private is None or private["type"] != "private_token":
            private = next((p for p in workflow["parameters"] if p["type"] == "private_token"), None)
        public = next((p for p in workflow["parameters"] if p["name"] == "order_id"), None)
        if public is None or public["type"] != "string":
            public = next((p for p in workflow["parameters"] if p["type"] == "string"), None)
        used_parameters = _used_parameters(workflow)
        required_private = next((p for p in ([private] if private else []) + workflow["parameters"]
                                 if p["type"] == "private_token" and (p["required"] or p["name"] in used_parameters)), None)
        required_public = next((p for p in ([public] if public else []) + workflow["parameters"]
                                if p["type"] == "string" and (p["required"] or p["name"] in used_parameters)), None)
        private = required_private or private
        public = required_public or public

        def prepare(path=base, values=None, caps=None):
            return prepare_run(path, copy.deepcopy(bindings if values is None else values),
                               list(capabilities if caps is None else caps))

        def add(case_id, title, change, expectation, category, **kwargs):
            cases.append(_case(case_id, title, change, expectation, category, **kwargs))

        usable = bindings is not None
        unavailable = ["The skill does not expose parameter classes this synthetic scenario can exercise."]
        fresh = prepare() if usable else None
        fresh_context = (fresh or {}).get("context") or {}
        fresh_passed = bool(fresh and fresh["status"] == "ready"
                            and fresh_context.get("parameters") == bindings
                            and all(check["result"] == "unknown" for check in fresh_context.get("checks", [])))
        add("fresh_bindings", "Fresh workspace inputs", "Replace recorded inputs with newly generated synthetic values.",
            "ready", "bindings", result=fresh, passed=fresh_passed,
            details=["Checked the actual prepared parameter values and reset current-run check results."] if usable else unavailable,
            input_preview=bindings if usable else None)

        for parameter, case_id, title in [(required_private, "missing_private_binding", "Missing private input"),
                                           (required_public, "missing_public_binding", "Missing public input")]:
            if usable and parameter:
                values = dict(bindings)
                values.pop(parameter["name"])
                result = prepare(values=values)
                add(case_id, title, "Omit one declared input while retaining the other fresh bindings.",
                    "needs_input", "bindings", result=result,
                    passed=result["status"] == "needs_input" and parameter["name"] in result["missing_bindings"],
                    details=["Checked that the omitted parameter appears in missing_bindings."], input_preview=values)
            else:
                add(case_id, title, "Omit one declared input.", "needs_input", "bindings", details=unavailable)

        known_stale = next(((p, token) for p in workflow["parameters"] if p["type"] == "private_token"
                            for token in _KNOWN_SYNTHETIC_SOURCE_TOKENS
                            if token.split("_", 1)[0] == p["token_class"]
                            and digest(token.encode()) in p["source_token_hashes"]), None)
        if usable and known_stale:
            stale_parameter, stale_token = known_stale
            result = prepare(values={**bindings, stale_parameter["name"]: stale_token})
            add("stale_source_token", "Stale source reference", "Supply a known synthetic source token whose hash is recorded in the package.",
                "invalid", "bindings", result=result,
                details=["The known synthetic token was matched to a recorded source hash before testing."],
                input_preview={stale_parameter["name"]: "[known synthetic source reference]"})
        else:
            add("stale_source_token", "Stale source reference", "Attempt to reuse a source-session reference.",
                "invalid", "bindings", details=["No known synthetic source token matches this package. Hashes cannot recover an unknown source value."])

        if usable and private:
            name = private["name"]
            result = prepare(values={**bindings, name: "17 Example Lane, Test City"})
            add("private_plaintext", "Plaintext in a private slot", "Supply fixed fictional plaintext instead of an opaque private reference.",
                "invalid", "bindings", result=result,
                details=["Only a fixed fictional test value was used; no real private value was loaded."],
                input_preview={name: "[fictional plaintext test value]"})
            wrong_class = "EMAIL" if private["token_class"] != "EMAIL" else "ADDRESS"
            result = prepare(values={**bindings, name: f"{wrong_class}_800001_cafe"})
            add("wrong_token_class", "Wrong private reference class", "Supply a fresh synthetic token of a different class.",
                "invalid", "bindings", result=result,
                details=["The synthetic reference class differs from the declared parameter class."],
                input_preview={name: f"{wrong_class}_800001_cafe"})
        else:
            for case_id, title in [("private_plaintext", "Plaintext in a private slot"), ("wrong_token_class", "Wrong private reference class")]:
                add(case_id, title, "Change the private input representation.", "invalid", "bindings", details=unavailable)

        if usable and capabilities:
            result = prepare(caps=capabilities[1:])
            add("missing_capability", "Missing runtime capability", "Remove one capability required by this skill.",
                "unsupported", "scope", result=result,
                passed=result["status"] == "unsupported" and capabilities[0] in result["missing_capabilities"],
                details=["Checked that the omitted capability appears in missing_capabilities."])
        else:
            add("missing_capability", "Missing runtime capability", "Remove one required runtime capability.",
                "unsupported", "scope", details=["This skill has no required capability to remove, or synthetic bindings are unavailable."])

        def variant(name, new_workflow, new_evidence):
            path = temporary / name
            write_package(new_workflow, new_evidence, path)
            return path

        variant_reason = ["Package variants were disabled for this rehearsal."] if not include_variants else unavailable
        if include_variants and usable and required_private:
            changed = copy.deepcopy(workflow)
            next(p for p in changed["parameters"] if p["name"] == private["name"])["binding_role"] = None
            result = prepare(path=variant("ambiguous-role", changed, evidence))
            add("unresolved_private_role", "Ambiguous private role", "Remove a private parameter's role while retaining its token class.",
                "needs_input", "bindings", result=result,
                passed=result["status"] == "needs_input" and private["name"] in result["missing_bindings"],
                details=["A token class alone must not resolve the private binding's meaning."])
        else:
            add("unresolved_private_role", "Ambiguous private role", "Remove a private parameter's binding role.",
                "needs_input", "bindings", details=variant_reason)

        referenced = next((event_id for step in workflow["steps"] for event_id in step["evidence_ids"]
                           if event_id in evidence["event_ids"]), None)
        if include_variants and usable and referenced:
            path = temporary / "broken-evidence"
            _write_snapshot(snapshot, path)
            broken = copy.deepcopy(evidence)
            broken["event_ids"].remove(referenced)
            write_json(path / "evidence-map.json", broken)
            broken_validation = validate_skill(path)
            result = prepare(path=path)
            add("missing_evidence", "Broken evidence reference", "Remove an event that an actual learned step references.",
                "invalid", "evidence", result=result,
                passed=result["status"] == "invalid" and broken_validation["status"] == "invalid",
                details=["Both package validation and preparation were exercised on the deliberately broken copy."])
        else:
            add("missing_evidence", "Broken evidence reference", "Remove an event referenced by a learned step.",
                "invalid", "evidence", details=variant_reason if not include_variants or not usable else ["The skill has no step event reference to remove."])

        for outcome, case_id, title in [("failed", "failed_source_outcome", "Failed demonstration outcome"),
                                         ("unknown", "unknown_source_outcome", "Unproven demonstration outcome")]:
            if include_variants and usable:
                changed_evidence = copy.deepcopy(evidence)
                changed_evidence["outcome"] = {"status": outcome, "check_ids": []}
                path = variant(f"outcome-{outcome}", workflow, changed_evidence)
                outcome_report = validate_skill(path)
                result = prepare(path=path)
                add(case_id, title, f"Set the source outcome to {outcome} while leaving the reusable steps intact.",
                    "needs_input", "evidence", result=result,
                    passed=result["status"] == "needs_input" and outcome_report["outcome"]["status"] == outcome,
                    details=[f"The package validator reported the source outcome as {outcome}.",
                             "A procedure without a successful demonstration should request review before being considered ready."])
            else:
                add(case_id, title, f"Set the source outcome to {outcome}.", "needs_input", "evidence", details=variant_reason)

        add("changed_layout_execution", "Changed application layout", "Move fields and rename a button in a real second-run workspace.",
            "successful live execution", "runtime",
            details=["Not run. This module has no application executor or visual reasoning loop.",
                     "Use the main PLVA runner to collect a real changed-layout result."])

    return {
        "schema_version": "1.0", "kind": "offline_skill_rehearsal",
        "skill_id": workflow["skill_id"], "revision": workflow["revision"],
        "package_digest": _snapshot_digest(snapshot),
        "totals": {status: sum(case["status"] == status for case in cases) for status in ("passed", "failed", "pending")},
        "cases": cases, "live_execution": "pending", "limits": list(_LIMITS),
    }
