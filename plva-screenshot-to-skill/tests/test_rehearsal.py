"""Rehearsal measures actual adapter behavior and preserves its practical limits."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plva_skill_learning.common import SkillforgeError, digest, read_json
from plva_skill_learning.exporter import write_package
from plva_skill_learning.ingest import import_bundle
from plva_skill_learning.rehearsal import package_digest, run_rehearsal
from plva_skill_learning.runner_adapter import prepare_run as actual_prepare_run
from plva_skill_learning.synthesis import draft
from plva_skill_learning.timeline import evidence_map


ROOT = Path(__file__).resolve().parents[1]


class RehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recording = import_bundle(ROOT / "fixtures" / "shipment-demo")
        cls.workflow = draft(cls.recording)
        cls.evidence = evidence_map(cls.recording, cls.workflow)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.skill = self.root / "candidate"
        write_package(copy.deepcopy(self.workflow), copy.deepcopy(self.evidence), self.skill)

    def cases(self, report):
        return {case["case_id"]: case for case in report["cases"]}

    def test_main_fixture_exercises_typed_contracts_and_live_stays_pending(self):
        report = run_rehearsal(self.skill)
        cases = self.cases(report)
        self.assertEqual(report["kind"], "offline_skill_rehearsal")
        self.assertEqual(report["skill_id"], self.workflow["skill_id"])
        self.assertEqual(report["revision"], self.workflow["revision"])
        self.assertEqual(len(cases), 12)
        self.assertEqual(sum(report["totals"].values()), len(cases))
        for case_id in ["fresh_bindings", "missing_private_binding", "missing_public_binding", "stale_source_token",
                        "private_plaintext", "wrong_token_class", "missing_capability", "unresolved_private_role", "missing_evidence"]:
            with self.subTest(case=case_id):
                self.assertEqual(cases[case_id]["status"], "passed")
                self.assertEqual(cases[case_id]["actual_status"], cases[case_id]["expectation"])
        self.assertEqual(report["live_execution"], "pending")
        self.assertEqual(cases["changed_layout_execution"]["status"], "pending")
        self.assertIsNone(cases["changed_layout_execution"]["passed"])
        self.assertEqual(cases["changed_layout_execution"]["actual_status"], "not_run")
        self.assertTrue(any("not browser" in limit for limit in report["limits"]))
        self.assertNotIn("ADDRESS_1_a3f9", json.dumps(report))
        self.assertEqual(set(cases["fresh_bindings"]["input_preview"]), {p["name"] for p in self.workflow["parameters"]})

    def test_failed_or_unproven_source_outcome_is_not_considered_ready(self):
        cases = self.cases(run_rehearsal(self.skill))
        for case_id in ["failed_source_outcome", "unknown_source_outcome"]:
            with self.subTest(case=case_id):
                self.assertEqual(cases[case_id]["expectation"], "needs_input")
                self.assertEqual(cases[case_id]["actual_status"], "needs_input")
                self.assertTrue(cases[case_id]["passed"])

    def test_result_records_a_real_adapter_regression_instead_of_faking_a_pass(self):
        def broken_missing_input(path, bindings, capabilities):
            result = actual_prepare_run(path, bindings, capabilities)
            if "customer_shipping_address" not in bindings and result["status"] == "needs_input":
                result["status"] = "ready"
            return result

        with patch("plva_skill_learning.rehearsal.prepare_run", side_effect=broken_missing_input):
            report = run_rehearsal(self.skill)
        case = self.cases(report)["missing_private_binding"]
        self.assertEqual(case["actual_status"], "ready")
        self.assertEqual(case["expectation"], "needs_input")
        self.assertFalse(case["passed"])
        self.assertEqual(case["status"], "failed")
        self.assertGreaterEqual(report["totals"]["failed"], 1)

    def test_rehearsal_is_offline_and_leaves_original_package_untouched(self):
        before = {path.name: path.read_bytes() for path in self.skill.iterdir()}
        with patch("socket.create_connection", side_effect=AssertionError("Rehearsal must remain offline.")):
            report = run_rehearsal(self.skill)
        self.assertEqual({path.name: path.read_bytes() for path in self.skill.iterdir()}, before)
        self.assertEqual({path.name for path in self.root.iterdir()}, {"candidate"})
        self.assertEqual(report["package_digest"], package_digest(self.skill))
        self.assertEqual(run_rehearsal(self.skill), report)

    def test_package_digest_binds_evidence_markdown_workflow_and_validation(self):
        initial = package_digest(self.skill)
        self.assertEqual(len(initial), 64)
        for name in ["SKILL.md", "workflow.json", "evidence-map.json", "validation.json"]:
            with self.subTest(file=name):
                path = self.skill / name
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n")
                    self.assertNotEqual(package_digest(self.skill), initial)
                finally:
                    path.write_bytes(original)
        self.assertEqual(package_digest(self.skill), initial)

    def test_unavailable_source_token_is_pending_for_other_private_classes(self):
        workflow = copy.deepcopy(self.workflow)
        parameter = next(p for p in workflow["parameters"] if p["type"] == "private_token")
        parameter["token_class"] = "EMAIL"
        parameter["source_token_hashes"] = [digest(b"EMAIL_42_aaaa")]
        other = self.root / "different-private-class"
        write_package(workflow, copy.deepcopy(self.evidence), other)
        report = run_rehearsal(other)
        cases = self.cases(report)
        self.assertEqual(cases["fresh_bindings"]["status"], "passed")
        self.assertTrue(cases["fresh_bindings"]["input_preview"][parameter["name"]].startswith("EMAIL_"))
        self.assertEqual(cases["wrong_token_class"]["status"], "passed")
        self.assertEqual(cases["stale_source_token"]["status"], "pending")
        self.assertIsNone(cases["stale_source_token"]["passed"])
        self.assertNotIn("EMAIL_42_aaaa", json.dumps(report))

    def test_unused_optional_provenance_does_not_create_artificial_missing_inputs(self):
        workflow = copy.deepcopy(self.workflow)
        # Put incidental metadata first to also exercise generic scenario selection.
        workflow["parameters"][:0] = [
            {"name": "incidental_billing_address", "type": "private_token", "visibility": "private",
             "required": False, "binding_role": None, "token_class": "ADDRESS",
             "source_token_hashes": [digest(b"ADDRESS_18_baba")]},
            {"name": "incidental_page_label", "type": "string", "visibility": "public",
             "required": False, "binding_role": None, "token_class": None, "source_token_hashes": []},
        ]
        # Remove the demo-specific names while preserving the actual procedure variables.
        workflow = json.loads(json.dumps(workflow).replace("customer_shipping_address", "destination_input")
                              .replace("order_id", "order_reference"))
        skill = self.root / "incidental-provenance"
        write_package(workflow, copy.deepcopy(self.evidence), skill)
        report = run_rehearsal(skill)
        cases = self.cases(report)
        self.assertEqual(report["totals"], {"passed": 11, "failed": 0, "pending": 1})
        self.assertEqual(set(cases["fresh_bindings"]["input_preview"]), {"destination_input", "order_reference"})
        self.assertEqual(set(cases["missing_private_binding"]["input_preview"]), {"order_reference"})
        self.assertEqual(set(cases["missing_public_binding"]["input_preview"]), {"destination_input"})
        self.assertTrue(any("Decision: " in detail for detail in cases["private_plaintext"]["details"]))
        self.assertNotIn("ADDRESS_18_baba", json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_skipped_variants_remain_pending_and_do_not_export_mutations(self):
        with patch("plva_skill_learning.rehearsal.write_package", side_effect=AssertionError("Variants were disabled.")):
            report = run_rehearsal(self.skill, include_variants=False)
        cases = self.cases(report)
        for case_id in ["unresolved_private_role", "missing_evidence", "failed_source_outcome", "unknown_source_outcome"]:
            self.assertEqual(cases[case_id]["status"], "pending")
            self.assertIsNone(cases[case_id]["passed"])
        self.assertEqual(report["totals"], {"passed": 7, "failed": 0, "pending": 5})

    def test_invalid_source_package_cannot_receive_a_rehearsal_certificate(self):
        path = self.skill / "evidence-map.json"
        evidence = read_json(path)
        evidence["event_ids"] = []
        path.write_text(json.dumps(evidence), encoding="utf-8")
        with self.assertRaises(SkillforgeError) as error:
            run_rehearsal(self.skill)
        self.assertEqual(error.exception.code, "invalid_package")
        self.assertNotIn(str(self.skill), str(error.exception))


if __name__ == "__main__":
    unittest.main()
