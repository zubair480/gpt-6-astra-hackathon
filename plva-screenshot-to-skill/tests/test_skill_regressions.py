"""Reproducible workflow-learning quality cases, using only synthetic evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from plva_skill_learning.exporter import write_package
from plva_skill_learning.ingest import approve_bundle, import_bundle
from plva_skill_learning.runner_adapter import prepare_run
from plva_skill_learning.synthesis import draft
from plva_skill_learning.timeline import evidence_map


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "shipment-demo"
BINDINGS = {"customer_shipping_address": "ADDRESS_7_b812", "order_id": "DEMO-205"}


class SkillRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "recording"
        shutil.copytree(FIXTURE, self.bundle)

    def package(self, mutate=None, bindings=None):
        manifest = json.loads((self.bundle / "manifest.json").read_text())
        events = [json.loads(line) for line in (self.bundle / "events.jsonl").read_text().splitlines()]
        if mutate:
            mutate(manifest, events)
        # Render the actual test states; no real desktop capture or hidden raw data.
        observations = {event["frame_id"]: event for event in events if event["type"] == "observation"}
        for frame in manifest["frames"]:
            observation = observations.get(frame["frame_id"])
            if observation:
                image = Image.new("RGB", (800, 480), "#f5f7fa")
                drawing = ImageDraw.Draw(image)
                drawing.text((24, 20), "SYNTHETIC QUALITY TEST - no live application", fill="#163a52")
                drawing.text((24, 80), observation.get("text", "Recorded screen"), fill="#163a52")
                for i, token in enumerate(observation.get("tokens", [])):
                    drawing.text((24, 160 + i * 30), token["token"], fill="#163a52")
                path = self.bundle / frame["path"]
                image.save(path)
                frame["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.bundle / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        store = self.root / "approvals.json"
        approve_bundle(self.bundle, store, role_hints_trusted=True)
        recording = import_bundle(self.bundle, store)
        workflow = draft(recording)
        folder = self.root / "candidate"
        write_package(workflow, evidence_map(recording, workflow), folder)
        prepared = prepare_run(folder, copy.deepcopy(BINDINGS if bindings is None else bindings), workflow["required_capabilities"])
        return workflow, prepared

    def test_incidental_private_token_does_not_require_a_binding(self):
        def mutate(manifest, events):
            events[0]["tokens"].append({"token": "EMAIL_2_cafe", "class": "EMAIL", "role_hint": "ticket_owner_email"})
            events[0]["text"] += " Ticket owner contact EMAIL_2_cafe is visible but unused."
        workflow, prepared = self.package(mutate)
        mandatory = {p["name"] for p in workflow["parameters"] if p["required"]}
        self.assertNotIn("ticket_owner_email", mandatory, "Merely visible contact data became mandatory workflow input.")
        self.assertEqual("ready", prepared["status"])

    def test_one_private_token_with_two_roles_requires_review(self):
        def mutate(manifest, events):
            events[0]["tokens"].append({"token": "ADDRESS_1_a3f9", "class": "ADDRESS", "role_hint": "billing_address"})
        workflow, prepared = self.package(mutate, bindings={"private_input_1": "ADDRESS_7_b812", "order_id": "DEMO-205"})
        private = [p for p in workflow["parameters"] if p["type"] == "private_token"]
        self.assertTrue(private)
        self.assertIsNone(private[0]["binding_role"])
        self.assertEqual("needs_input", prepared["status"])

    def test_conflicting_token_classes_require_review(self):
        def mutate(manifest, events):
            events[0]["tokens"].append({"token": "ADDRESS_1_a3f9", "class": "EMAIL", "role_hint": "customer_shipping_address"})
        workflow, prepared = self.package(mutate)
        self.assertEqual("needs_input", prepared["status"], "Conflicting class metadata silently fell back to the token prefix.")
        self.assertTrue(workflow["unresolved_questions"])

    def test_one_public_value_with_two_roles_requires_review(self):
        def mutate(manifest, events):
            events[0]["public_values"].append({"value": "DEMO-104", "role_hint": "support_ticket_id"})
        workflow, prepared = self.package(mutate, bindings={"customer_shipping_address": "ADDRESS_7_b812"})
        self.assertTrue(workflow["unresolved_questions"])
        self.assertEqual("needs_input", prepared["status"])

    def test_failed_source_cannot_prepare_as_ready(self):
        def mutate(manifest, events):
            manifest["outcome"]["status"] = "failed"
            events[-1]["result"] = "failed"
        _, prepared = self.package(mutate)
        self.assertEqual("needs_input", prepared["status"], "A failed demonstration was prepared as if it were successful.")
        self.assertIsNone(prepared["context"])

    def test_cancelled_source_cannot_prepare_as_ready(self):
        def mutate(manifest, events):
            manifest["outcome"]["status"] = "cancelled"
        _, prepared = self.package(mutate)
        self.assertEqual("needs_input", prepared["status"], "A cancelled demonstration needs an explicit review decision.")
        self.assertIsNone(prepared["context"])

    def test_unrecovered_failed_check_blocks_preparation(self):
        def mutate(manifest, events):
            manifest["outcome"] = {"status": "unknown", "check_ids": ["c1", "c2"]}
            events[-1]["result"] = "failed"
        _, prepared = self.package(mutate)
        self.assertEqual("needs_input", prepared["status"], "An unrecovered failed final check was ignored.")

    @staticmethod
    def corrected_typing(manifest, events):
        criterion = "Order reference equals the selected source order."
        raw = [
            {"type": "observation", "frame_id": "frame-0001", "text": "Source order DEMO-104 requests a replacement.",
             "tokens": [{"token": "ADDRESS_1_a3f9", "class": "ADDRESS", "role_hint": "customer_shipping_address"}],
             "public_values": [{"value": "DEMO-104", "role_hint": "order_id"}]},
            {"type": "action", "action_id": "wrong-type", "status": "executed", "operation": {"kind": "type", "target_hint": "Order reference", "text": "DEMO-999"}, "before_event_id": "t1", "after_event_id": "t3"},
            {"type": "observation", "frame_id": "frame-0002", "text": "Order reference DEMO-999 is present; it does not match the selected source order."},
            {"type": "check", "check_id": "wrong-order", "result": "failed", "source": "core_verifier", "criterion": criterion, "evidence_ids": ["t2", "t3"]},
            {"type": "correction", "source": "user", "text": "Replace the wrong order reference with the selected source order DEMO-104.", "evidence_ids": ["t2", "t3"]},
            {"type": "action", "action_id": "correct-type", "status": "executed", "operation": {"kind": "type", "target_hint": "Order reference", "text": "DEMO-104"}, "before_event_id": "t3", "after_event_id": "t7"},
            {"type": "observation", "frame_id": "frame-0003", "text": "Order reference DEMO-104 matches the selected source order."},
            {"type": "check", "check_id": "correct-order", "result": "passed", "source": "core_verifier", "criterion": criterion, "evidence_ids": ["t6", "t7"]},
            {"type": "action", "action_id": "destination", "status": "executed", "operation": {"kind": "type", "target_hint": "Customer shipping address", "text": "ADDRESS_1_a3f9"}, "before_event_id": "t7", "after_event_id": "t10"},
            {"type": "observation", "frame_id": "frame-0004", "text": "Replacement form contains the selected order and protected customer shipping address."},
            {"type": "check", "check_id": "form-complete", "result": "passed", "source": "core_verifier", "criterion": "Replacement form order and destination match the selected source values.", "evidence_ids": ["t6", "t7", "t9", "t10"]},
        ]
        events[:] = [{"event_id": f"t{i}", "sequence": i, "time_ms": i * 500, **event} for i, event in enumerate(raw, 1)]
        manifest["outcome"] = {"status": "passed", "check_ids": ["correct-order", "form-complete"]}

    def test_corrected_typing_omits_superseded_wrong_write(self):
        workflow, _ = self.package(self.corrected_typing)
        normal = " ".join(step["instruction"] for step in workflow["steps"])
        self.assertNotIn("DEMO-999", normal, "Learning retained the known-wrong typing action as a mandatory step.")
        self.assertTrue(any(step["recovery"] for step in workflow["steps"]))

    def test_corrected_typing_does_not_require_wrong_state(self):
        workflow, _ = self.package(self.corrected_typing)
        preconditions = " ".join(value for step in workflow["steps"] for value in step["preconditions"])
        self.assertNotIn("DEMO-999", preconditions, "The repaired step still requires the wrong state before it can run.")

    def test_recovered_historical_check_allows_corrected_workflow(self):
        workflow, prepared = self.package(self.corrected_typing)
        self.assertTrue(any(check["result"] == "failed" for check in workflow["checks"]), "Failure evidence must remain inspectable.")
        self.assertEqual("ready", prepared["status"], "A later verified correction must distinguish recovered from unresolved failure.")

    def test_failed_click_validation_message_is_not_a_precondition(self):
        workflow, prepared = self.package()
        preconditions = " ".join(value for step in workflow["steps"] for value in step["preconditions"])
        self.assertNotIn("Validation message: select", preconditions)
        self.assertEqual("ready", prepared["status"])


if __name__ == "__main__":
    unittest.main()
