"""Procedure quality regressions beyond schema validity and action labels."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from plva_skill_learning.common import SkillforgeError, check_schema
from plva_skill_learning.exporter import render_skill, renders_matching_workflow, write_package
from plva_skill_learning.ingest import approve_bundle, import_bundle
from plva_skill_learning.synthesis import draft
from plva_skill_learning.timeline import evidence_map
from plva_skill_learning.validation import validate_skill
from test_synthesis import MockTransport

ROOT = Path(__file__).resolve().parents[1]

# Exact compact example from the original v1 Markdown format. Keep independent of
# the renderer and ignored audit directory so fresh clones test compatibility.
LEGACY_MARKDOWN = '''---
name: recorded-example
description: "Use this workflow to Open the recorded form. Review unresolved questions and bind inputs from the current workspace."
---

# Open recorded form

Open the recorded form.

## Inputs

No parameter bindings were identified in the recording.

## Procedure

1. Open the form. (observed; evidence: e3, e1, e4)
   Checkpoint: The form is open.

## Outcome checks

No independent outcome checks were recorded; establish a current-run success check before relying on the result.

## Execution boundary

Bind private inputs to fresh opaque references supplied by PLVA. The current runtime owns permissions, approvals, and execution. This package grants none. Inspect semantic targets in the current visual state; historical coordinates are not replay instructions.

The recording is evidence of one demonstration. Review acceptance is not a successful rerun. Consult `validation.json` for the specific checks performed and pending live execution.

Detailed step references are in `evidence-map.json`; the local source recording may be unavailable in another workspace.
'''


class SkillQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def recording(self, mutate=None, cloud=False):
        path = self.folder / "bundle"
        shutil.copytree(ROOT / "fixtures" / "shipment-demo", path)
        manifest = json.loads((path / "manifest.json").read_text())
        events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        if mutate:
            mutate(manifest, events)
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (path / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        store = self.folder / "approvals.json"
        approve_bundle(path, store, allow_cloud=cloud, role_hints_trusted=True)
        return import_bundle(path, store)

    def test_procedure_contains_context_inputs_and_observable_checkpoints(self):
        workflow = draft(self.recording())
        address = next(step for step in workflow["steps"] if "{{customer_shipping_address}}" in step["instruction"])
        self.assertIn("shipping", address["instruction"])
        self.assertIn("{{customer_shipping_address}}", address["postcondition"])
        self.assertNotEqual(address["goal"], address["target_hints"][0])
        self.assertGreater(len(address["target_hints"]), 1)
        markdown = render_skill(workflow)
        for field in ("Before:", "Do:", "Locate:", "Verify:", "Evidence:"):
            self.assertIn(field, markdown)
        self.assertIn("shown on the support ticket", markdown)

    def test_recovery_has_a_recorded_trigger_instead_of_unconditional_retry(self):
        workflow = draft(self.recording())
        recovery = next(recovery for step in workflow["steps"] for recovery in step["recovery"])
        self.assertTrue(recovery["instruction"].startswith("If "))
        self.assertIn("select the replacement item", recovery["instruction"].lower())
        self.assertIn("e8", recovery["evidence_ids"])
        self.assertNotIn("e7", [ref for step in workflow["steps"] for ref in step["evidence_ids"]])

    def test_visible_public_metadata_and_identifier_prefixes_do_not_become_inputs(self):
        def mutate(manifest, events):
            events[0]["public_values"].extend([{"value": "VIP", "role_hint": "customer_segment"}, {"value": "DEMO", "role_hint": "account_prefix"}])
            events[0]["text"] += " Segment VIP and account prefix DEMO are visible."
        workflow = draft(self.recording(mutate))
        self.assertEqual({"customer_shipping_address", "order_id"}, {item["name"] for item in workflow["parameters"]})

    def test_short_public_value_does_not_corrupt_words_or_stable_identifiers(self):
        def mutate(manifest, events):
            events[0]["public_values"] = [{"value": "A", "role_hint": "order_id"}]
            events[4]["operation"]["text"] = "A"
            events[5]["text"] = "Order reference A is present."
        workflow = draft(self.recording(mutate))
        check_schema(workflow, "workflow")
        self.assertTrue(any("Application: shipping" in step["target_hints"] for step in workflow["steps"]))
        self.assertIn("{{order_id}}", workflow["steps"][1]["instruction"])
        self.assertTrue(all(step["step_id"].startswith("step-") for step in workflow["steps"]))

    def test_unknown_outcome_is_an_explicit_question_even_with_passing_checks(self):
        def mutate(manifest, events):
            manifest["outcome"]["status"] = "unknown"
        workflow = draft(self.recording(mutate))
        self.assertTrue(any("outcome is unknown" in question for question in workflow["unresolved_questions"]))
        self.assertIn("outcome is unknown", render_skill(workflow))

    def test_model_cannot_replace_current_binding_with_a_recording_specific_value(self):
        def mutate(data):
            step = next(item for item in data["steps"] if "{{order_id}}" in item["instruction"])
            step["instruction"] = step["instruction"].replace("{{order_id}}", "DEMO-999")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-value"}):
            with self.assertRaises(SkillforgeError) as caught:
                draft(self.recording(cloud=True), "astra", {"transport": MockTransport(mutate)})
        self.assertEqual("model_binding_changed", caught.exception.code)

    def test_model_cannot_erase_a_missing_postcondition(self):
        def mutate_source(manifest, events):
            events[2].pop("after_event_id")
        def mutate_response(data):
            data["steps"][0]["postcondition"] = "Everything succeeded."
            data["steps"][0]["open_questions"] = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-value"}):
            workflow = draft(self.recording(mutate_source, cloud=True), "astra", {"transport": MockTransport(mutate_response)})
        self.assertIn("not recorded", workflow["steps"][0]["postcondition"])
        self.assertTrue(workflow["steps"][0]["open_questions"])

    def test_model_cannot_fill_an_unrecorded_typing_value(self):
        def mutate_source(manifest, events):
            events[4]["operation"].pop("text")
        def mutate_response(data):
            step = next(item for item in data["steps"] if "missing input" in item["instruction"])
            step["instruction"] = "Enter DEMO-999 into the order reference."
            step["open_questions"] = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-value"}):
            workflow = draft(self.recording(mutate_source, cloud=True), "astra", {"transport": MockTransport(mutate_response)})
        self.assertTrue(any("missing input" in step["instruction"] and step["open_questions"] for step in workflow["steps"]))

    def test_original_v1_markdown_validates_but_manual_edits_do_not(self):
        recording = self.recording()
        workflow = draft(recording)
        workflow.update(skill_id="recorded-example", title="Open recorded form", objective="Open the recorded form.",
                        parameters=[], checks=[], preconditions=[], unresolved_questions=[])
        workflow["steps"] = [{"step_id": "open-form", "goal": "Open form", "preconditions": [], "instruction": "Open the form.",
                              "target_hints": ["Form"], "postcondition": "The form is open.", "check_ids": [], "recovery": [],
                              "evidence_ids": ["e3", "e1", "e4"], "basis": "observed", "open_questions": []}]
        mapping = evidence_map(recording, workflow)
        mapping["outcome"] = {"status": "unknown", "check_ids": []}
        path = self.folder / "original-v1"
        write_package(workflow, mapping, path)
        (path / "SKILL.md").write_text(LEGACY_MARKDOWN, encoding="utf-8")
        self.assertNotEqual(LEGACY_MARKDOWN, render_skill(workflow))
        self.assertTrue(renders_matching_workflow(LEGACY_MARKDOWN, workflow))
        self.assertEqual("candidate", validate_skill(path)["status"])
        modified = LEGACY_MARKDOWN.replace("Open the form.", "Open a different form.", 1)
        (path / "SKILL.md").write_text(modified, encoding="utf-8")
        self.assertFalse(renders_matching_workflow(modified, workflow))
        report = validate_skill(path)
        self.assertEqual("invalid", report["status"])
        self.assertIn("markdown_workflow_mismatch_use_review_edit", report["structure"]["errors"])

    def test_inferred_or_unsupported_pass_does_not_label_failure_recovered(self):
        workflow = draft(self.recording())
        failed = {"check_id": "old-check", "criterion": "The input matches the source.", "source": "core_verifier", "result": "failed", "basis": "observed", "evidence_ids": ["e5"]}
        passed = {**failed, "check_id": "new-check", "result": "passed", "basis": "inferred", "evidence_ids": ["e12"]}
        workflow["checks"] = [failed, passed]
        workflow["steps"][0]["recovery"] = [{"instruction": "Correct the input.", "basis": "observed", "evidence_ids": ["e5"]}]
        self.assertNotIn("Historical recovery evidence:", render_skill(workflow))
        passed.update(basis="observed", evidence_ids=[])
        self.assertNotIn("Historical recovery evidence:", render_skill(workflow))
        passed["evidence_ids"] = ["e12"]
        self.assertIn("Historical recovery evidence:", render_skill(workflow))


if __name__ == "__main__":
    unittest.main()
