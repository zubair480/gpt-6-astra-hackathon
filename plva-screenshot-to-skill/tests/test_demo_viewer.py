"""The hackathon walkthrough displays real local outputs without changing the skill."""
from __future__ import annotations

import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plva_skill_learning.common import SkillforgeError, read_json, write_json
from plva_skill_learning.demo_viewer import _json_for_html, write_demo_viewer
from plva_skill_learning.exporter import write_package
from plva_skill_learning.ingest import import_bundle
from plva_skill_learning.runner_adapter import prepare_run
from plva_skill_learning.synthesis import draft
from plva_skill_learning.timeline import evidence_map


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class ViewerHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.payload_chunks = []
        self.in_payload = False
        self.payload_count = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "script" and attrs.get("id") == "demo-data":
            self.in_payload = True
            self.payload_count += 1
            if attrs.get("type") != "application/json":
                raise AssertionError("Demo payload must be inert application/json.")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False

    def handle_data(self, data):
        if self.in_payload:
            self.payload_chunks.append(data)

    @property
    def payload(self):
        return json.loads("".join(self.payload_chunks))


class DemoViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recording = import_bundle(FIXTURES / "shipment-demo")
        cls.workflow = draft(cls.recording)
        cls.evidence = evidence_map(cls.recording, cls.workflow)
        cls.bindings = read_json(FIXTURES / "new-run-bindings.json")
        cls.capabilities = read_json(FIXTURES / "capabilities.json")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_demo(self, workflow=None):
        workflow = copy.deepcopy(self.workflow if workflow is None else workflow)
        package = write_package(workflow, copy.deepcopy(self.evidence), self.root / "candidate")
        prepared = prepare_run(self.root / "candidate", self.bindings, self.capabilities)
        write_json(self.root / "prepared-context.json", prepared)
        write_json(self.root / "evaluation.json", {
            "demo_kind": "synthetic_offline", "generation": "deterministic_mock",
            "source_outcome": package["validation"]["outcome"],
            "package_validation": package["validation"]["status"],
            "fresh_binding_preparation": prepared["status"],
            "review_acceptance": "pending_user_review", "live_astra_synthesis": "not_run",
            "changed_layout_execution": "pending_main_runtime",
            "privacy": {"reusable_skill_has_session_tokens": False, "image_redaction_verified": False},
            "performance_improvement": "not_measured",
            "changed_layout_input": str(FIXTURES / "changed-layout"),
        })
        return workflow, prepared

    def test_walkthrough_payload_uses_actual_workflow_and_fresh_prepared_context(self):
        workflow, prepared = self.make_demo()
        path = write_demo_viewer(self.root, FIXTURES)
        self.assertIsInstance(path, Path)
        self.assertEqual(path.parent, self.root)
        self.assertEqual(path.suffix, ".html")
        parsed = ViewerHTML(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed.payload_count, 1)
        payload = parsed.payload
        self.assertEqual(payload["workflow"], workflow)
        self.assertEqual(payload["prepared"], prepared)
        self.assertEqual(len(payload["workflow"]["steps"]), len(self.workflow["steps"]))
        self.assertEqual(payload["workflow"]["source_recording_ids"], [self.recording["manifest"]["recording_id"]])
        self.assertEqual(payload["prepared"]["context"]["parameters"], self.bindings)
        encoded = json.dumps(payload)
        self.assertIn("pending_main_runtime", encoded)
        self.assertIn("data:image/png;base64,", encoded)
        self.assertIn("ADDRESS_7_b812", json.dumps(payload["prepared"]))
        self.assertNotIn("ADDRESS_1_a3f9", json.dumps(payload["prepared"]))
        self.assertEqual(payload["rehearsal"]["totals"], {"passed": 11, "failed": 0, "pending": 1})
        pending = next(c for c in payload["rehearsal"]["cases"] if c["case_id"] == "changed_layout_execution")
        self.assertEqual(pending["status"], "pending")
        self.assertTrue(any(attrs.get("id") == "panel-lab" for _, attrs in parsed.tags))

    def test_stale_candidate_rehearsal_cannot_be_displayed_as_current(self):
        from plva_skill_learning.rehearsal import run_rehearsal
        self.make_demo()
        report = run_rehearsal(self.root / "candidate")
        report["package_digest"] = "0" * 64
        write_json(self.root / "rehearsal.json", report)
        with self.assertRaises(SkillforgeError) as caught:
            write_demo_viewer(self.root, FIXTURES)
        self.assertEqual(caught.exception.code, "stale_rehearsal")

    def test_learning_audit_is_hidden_when_implementation_has_changed(self):
        from plva_skill_learning.demo_viewer import _quality_audit
        with patch("plva_skill_learning.demo_viewer.read_json", return_value={"source_hashes": {}}), patch.object(Path, "exists", return_value=True):
            self.assertIsNone(_quality_audit())

    def test_walkthrough_is_local_and_leaves_four_file_package_unchanged(self):
        self.make_demo()
        candidate = self.root / "candidate"
        before = {path.name: path.read_bytes() for path in candidate.iterdir()}
        with patch("socket.create_connection", side_effect=AssertionError("Viewer must work offline.")):
            path = write_demo_viewer(self.root, FIXTURES)
        after = {path.name: path.read_bytes() for path in candidate.iterdir()}
        self.assertEqual(after, before)
        self.assertEqual(set(after), {"SKILL.md", "workflow.json", "evidence-map.json", "validation.json"})
        self.assertNotEqual(path.parent, candidate)
        parsed = ViewerHTML(path.read_text(encoding="utf-8"))
        for tag, attrs in parsed.tags:
            if tag == "script":
                self.assertNotIn("src", attrs, "The walkthrough must embed its own code.")
            if tag == "link" and "stylesheet" in attrs.get("rel", "").split():
                self.fail("The walkthrough must embed its own styles.")
            if tag == "img" and "src" in attrs:
                self.assertFalse(attrs["src"].startswith(("http:", "https:", "//")))

    def test_json_embedding_cannot_close_its_script_element(self):
        value = {"task": '</script><script>alert("task text")</script>&\u2028\u2029'}
        embedded = _json_for_html(value)
        self.assertEqual(json.loads(embedded), value)
        self.assertNotIn("<", embedded)
        self.assertNotIn("</script", embedded.lower())
        parsed = ViewerHTML('<script id="demo-data" type="application/json">' + embedded + "</script>")
        self.assertEqual(parsed.payload_count, 1)
        self.assertEqual(parsed.payload, value)
        self.assertEqual(sum(tag == "script" for tag, _ in parsed.tags), 1)

    def test_candidate_task_text_remains_data_in_generated_walkthrough(self):
        workflow = copy.deepcopy(self.workflow)
        task_text = 'Show the literal text </script><script>alert("task text")</script> in this task.'
        workflow["objective"] = task_text
        self.make_demo(workflow)
        path = write_demo_viewer(self.root, FIXTURES)
        html = path.read_text(encoding="utf-8")
        self.assertNotIn('</script><script>alert("task text")</script>', html)
        parsed = ViewerHTML(html)
        self.assertEqual(parsed.payload_count, 1)
        self.assertEqual(parsed.payload["workflow"]["objective"], task_text)


if __name__ == "__main__":
    unittest.main()
