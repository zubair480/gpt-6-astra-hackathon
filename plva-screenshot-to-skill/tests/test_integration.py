import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from plva_skill_learning.api import SkillForge
from plva_skill_learning.cli import main
from plva_skill_learning.common import SkillforgeError, check_schema, read_json, write_json
from plva_skill_learning.exporter import write_package
from plva_skill_learning.ingest import approve_bundle, import_bundle
from plva_skill_learning.synthesis import draft
from plva_skill_learning.timeline import evidence_map
from plva_skill_learning.validation import validate_data, validate_skill

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/shipment-demo"


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recording = import_bundle(FIXTURE)
        self.workflow = draft(self.recording)
        self.evidence = evidence_map(self.recording, self.workflow)

    def package(self):
        path = self.root / "candidate"
        write_package(self.workflow, self.evidence, path)
        return path

    def test_public_api_import_draft_export_prepare(self):
        forge = SkillForge(self.root / "state")
        imported = forge.import_recording(FIXTURE)
        candidate = forge.draft_skill(imported["recording_id"], {"out": str(self.root / "draft")})
        report = forge.validate_skill(candidate["path"])
        check_schema(report, "validation")
        self.assertEqual(report["status"], "candidate")
        self.assertEqual(report["outcome"]["source"], "synthetic_fixture")
        exported = forge.export_skill(candidate["candidate_id"], self.root / "shared")
        self.assertEqual(set(p.name for p in Path(exported["path"]).iterdir()), {"SKILL.md", "workflow.json", "evidence-map.json", "validation.json"})
        prepared = forge.prepare_run(exported["path"], read_json(ROOT / "fixtures/new-run-bindings.json"), read_json(ROOT / "fixtures/capabilities.json"))
        self.assertEqual(prepared["status"], "ready")
        self.assertNotIn("ADDRESS_1_a3f9", json.dumps(prepared))
        self.assertIn("ADDRESS_7_b812", json.dumps(prepared))
        self.assertTrue(all(c["result"] == "unknown" for c in prepared["context"]["checks"]))

    def test_one_command_demo_is_offline_and_not_a_live_reuse_claim(self):
        out = self.root / "demo"
        with contextlib.redirect_stdout(io.StringIO()):
            status = main(["demo", "--out", str(out), "--fixtures", str(ROOT / "fixtures")])
        self.assertEqual(status, 0)
        evaluation = read_json(out / "evaluation.json")
        self.assertEqual(evaluation["fresh_binding_preparation"], "ready")
        self.assertEqual(evaluation["live_astra_synthesis"], "not_run")
        self.assertEqual(evaluation["changed_layout_execution"], "pending_main_runtime")
        self.assertEqual(evaluation["review_acceptance"], "pending_user_review")
        self.assertEqual(evaluation["offline_rehearsal"], {"passed": 11, "failed": 0, "pending": 1})

    def test_rehearsal_cli_writes_real_report_without_modifying_package(self):
        path = self.package()
        before = {p.name: p.read_bytes() for p in path.iterdir()}
        report_path = self.root / "rehearsal.json"
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            status = main(["rehearse", str(path), "--out", str(report_path)])
        self.assertEqual(status, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(read_json(report_path), report)
        self.assertEqual(report["totals"], {"passed": 11, "failed": 0, "pending": 1})
        self.assertEqual(before, {p.name: p.read_bytes() for p in path.iterdir()})

    def test_canary_filename_errors_never_echo_the_canary(self):
        bad = self.root / "PLVA_CANARY_SECRET_fixture"
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            status = main(["import", str(bad)])
        self.assertEqual(status, 2)
        self.assertNotIn("PLVA_CANARY", stderr.getvalue())
        self.assertNotIn(str(self.root), stderr.getvalue())

    def test_export_canary_in_fields_and_parent_directory(self):
        for field in ("title", "objective"):
            changed = copy.deepcopy(self.workflow)
            changed[field] = "PLVA_CANARY_SECRET_never_export"
            self.assertEqual(validate_data(changed, self.evidence)["status"], "invalid")
        target = self.root / "PLVA_CANARY_SECRET" / "skill"
        with self.assertRaises(SkillforgeError):
            write_package(self.workflow, self.evidence, target)
        self.assertFalse(target.exists())

    def test_missing_references_variables_and_false_status_fail(self):
        bad_reference = copy.deepcopy(self.workflow)
        bad_reference["steps"][0]["evidence_ids"].append("missing-event")
        self.assertEqual(validate_data(bad_reference, self.evidence)["status"], "invalid")
        bad_variable = copy.deepcopy(self.workflow)
        bad_variable["steps"][0]["instruction"] += " {{undeclared_input}}"
        self.assertEqual(validate_data(bad_variable, self.evidence)["status"], "invalid")
        false_status = copy.deepcopy(self.workflow)
        false_status["validation_status"] = "validated_on_fixture"
        self.assertEqual(validate_data(false_status, self.evidence)["status"], "invalid")

    def test_package_rejects_markdown_tampering_and_executable_files(self):
        path = self.package()
        (path / "SKILL.md").write_text((path / "SKILL.md").read_text() + "\nUnrecorded task instructions.\n")
        self.assertEqual(validate_skill(path)["status"], "invalid")
        (path / "run.py").write_text("print('unexpected executable')")
        self.assertIn("unexpected_or_missing_package_files", validate_skill(path)["structure"]["errors"])

    def test_empty_core_checks_cannot_prove_success(self):
        path = self.root / "source"
        shutil.copytree(FIXTURE, path)
        events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        for event in events:
            if event["type"] == "check":
                event["evidence_ids"] = []
        (path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        registry = self.root / "approvals.json"
        approve_bundle(path, registry, role_hints_trusted=True)
        recording = import_bundle(path, registry)
        workflow = draft(recording)
        report = validate_data(workflow, evidence_map(recording, workflow))
        self.assertEqual(report["outcome"]["status"], "unknown")

    def test_invalid_validation_json_never_certifies_package(self):
        path = self.package()
        write_json(path / "validation.json", {"status": "universally_verified"})
        self.assertEqual(validate_skill(path)["status"], "invalid")

    def test_saved_rerun_notes_are_checked_before_review_export(self):
        from plva_skill_learning.review import accept
        path = self.package()
        report = read_json(path / "validation.json")
        report["reruns"][0]["details"] = "PLVA_CANARY_SECRET_in_rerun_error"
        write_json(path / "validation.json", report)
        self.assertEqual(validate_skill(path)["status"], "invalid")
        with self.assertRaises(SkillforgeError):
            accept(path, self.root / "accepted")


if __name__ == "__main__":
    unittest.main()
