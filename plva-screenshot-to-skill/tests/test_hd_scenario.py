"""The presentation fixture carries actual item values across workspace changes."""
import json
from pathlib import Path
import tempfile
import unittest

from plva_skill_learning.common import read_json
from plva_skill_learning.exporter import write_package
from plva_skill_learning.ingest import import_bundle
from plva_skill_learning.runner_adapter import prepare_run
from plva_skill_learning.synthesis import draft
from plva_skill_learning.timeline import evidence_map

ROOT = Path(__file__).resolve().parents[1]


class HDScenarioTests(unittest.TestCase):
    def test_changed_product_is_bound_in_selection_and_outcome_check(self):
        fixtures = ROOT / "fixtures/hd"
        recording = import_bundle(fixtures / "shipment-demo")
        workflow = draft(recording)
        parameter = next(p for p in workflow["parameters"] if p["name"] == "replacement_item")
        self.assertTrue(parameter["required"])
        selection = next(s for s in workflow["steps"] if "select {{replacement_item}}" in s["instruction"])
        self.assertIn("{{replacement_item}}", selection["postcondition"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate"
            write_package(workflow, evidence_map(recording, workflow), path)
            bindings = read_json(fixtures / "new-run-bindings.json")
            result = prepare_run(path, bindings, workflow["required_capabilities"])
            self.assertEqual(result["status"], "ready")
            self.assertIn("select Wireless mouse", json.dumps(result["context"]["steps"]))
            self.assertIn("Wireless mouse", json.dumps(result["context"]["checks"]))
            self.assertNotIn("USB-C hub", json.dumps(result["context"]))
            del bindings["replacement_item"]
            missing = prepare_run(path, bindings, workflow["required_capabilities"])
            self.assertEqual(missing["status"], "needs_input")
            self.assertIn("replacement_item", missing["missing_bindings"])


if __name__ == "__main__":
    unittest.main()
