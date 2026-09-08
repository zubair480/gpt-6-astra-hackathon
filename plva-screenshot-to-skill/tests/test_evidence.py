import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plva_skill_learning.common import SkillforgeError
from plva_skill_learning.ingest import approve_bundle, import_bundle
from plva_skill_learning.timeline import build_timeline, evidence_map


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "shipment-demo"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        shutil.copytree(FIXTURE, self.bundle)
        self.store = self.root / "approved.json"

    def manifest(self):
        return json.loads((self.bundle / "manifest.json").read_text())

    def write_manifest(self, manifest):
        (self.bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def events(self):
        return [json.loads(line) for line in (self.bundle / "events.jsonl").read_text().splitlines()]

    def write_events(self, events):
        (self.bundle / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def approved(self, **options):
        approve_bundle(self.bundle, self.store, **options)
        return import_bundle(self.bundle, self.store)

    def assert_error(self, code, callback):
        with self.assertRaises(SkillforgeError) as error:
            callback()
        self.assertEqual(error.exception.code, code)
        return error.exception

    def test_pinned_fixture_and_statuses(self):
        recording = import_bundle(self.bundle)
        self.assertEqual(recording["bundle_digest"], import_bundle(FIXTURE)["bundle_digest"])
        self.assertFalse(recording["approval"]["allow_cloud"])
        self.assertTrue(recording["approval"]["role_hints_trusted"])
        self.assertEqual({e["status"] for e in recording["events"] if e["type"] == "action"}, {"proposed", "executed", "failed", "blocked"})

    def test_flags_do_not_trust_changed_bundle(self):
        manifest = self.manifest()
        manifest["task"] = "A different synthetic task"
        self.write_manifest(manifest)
        self.assert_error("unapproved_bundle", lambda: import_bundle(self.bundle))
        approved = self.approved(allow_cloud=True, role_hints_trusted=False)
        self.assertEqual(approved["approval"], {"allow_cloud": True, "role_hints_trusted": False})
        self.assertEqual(approved["approval_store"], str(self.store))
        manifest["task"] += " changed"
        self.write_manifest(manifest)
        self.assert_error("unapproved_bundle", lambda: import_bundle(self.bundle, self.store))

    def test_internal_approval_store_rejected(self):
        self.assert_error("unsafe_approval_store", lambda: approve_bundle(self.bundle, self.bundle / "approval.json"))

    def test_sequence_is_authoritative_and_time_can_tie(self):
        events = self.events()
        for event in events:
            event["time_ms"] = 0
        self.write_events(list(reversed(events)))
        recording = self.approved()
        self.assertEqual([e["sequence"] for e in recording["events"]], list(range(1, 19)))
        self.assertEqual(recording["events"][2]["after_event_id"], "e4")

    def test_duplicate_sequence_and_id_rejected(self):
        for field in ["sequence", "event_id"]:
            with self.subTest(field=field):
                events = [json.loads(line) for line in (FIXTURE / "events.jsonl").read_text().splitlines()]
                events[1][field] = events[0][field]
                self.write_events(events)
                self.assert_error("duplicate_event", lambda: import_bundle(self.bundle))

    def test_missing_and_wrong_reference_rejected(self):
        events = self.events()
        events[2]["after_event_id"] = "no-such-event"
        self.write_events(events)
        self.assert_error("missing_reference", lambda: import_bundle(self.bundle))
        events[2]["after_event_id"] = "e1"
        self.write_events(events)
        self.assert_error("reference_order", lambda: import_bundle(self.bundle))

    def test_path_escapes_and_filename_not_echoed(self):
        original = self.manifest()
        for unsafe in ["../private-CANARY.txt", "/private/CANARY.png", "C:/private/CANARY.png", "frames\\CANARY.png", "frames/../CANARY.png", "frames/CANARY.png:secret", "//host/share/CANARY.png"]:
            with self.subTest(path=unsafe):
                manifest = copy.deepcopy(original)
                manifest["frames"][0]["path"] = unsafe
                self.write_manifest(manifest)
                error = self.assert_error("unsafe_path", lambda: import_bundle(self.bundle))
                self.assertNotIn("CANARY", str(error))

    def test_checks_must_cite_observations_or_actions(self):
        original = self.events()
        for reference in ["e9", "e18"]:
            with self.subTest(reference=reference):
                events = copy.deepcopy(original)
                events[13]["evidence_ids"] = [reference]
                self.write_events(events)
                self.assert_error("invalid_evidence_type", lambda: import_bundle(self.bundle))
        events = copy.deepcopy(original)
        events[13]["evidence_ids"] = []
        self.write_events(events)
        self.assertEqual(self.approved()["events"][13]["evidence_ids"], [])

    @unittest.skipUnless(hasattr(Path, "is_junction"), "Host Python has no junction inspection")
    def test_windows_junction_paths_rejected(self):
        try:
            import _winapi
        except ImportError:
            self.skipTest("Windows junctions are not available on this host")
        if not hasattr(_winapi, "CreateJunction"):
            self.skipTest("Host Python has no junction creation helper")
        link = self.root / "bundle-junction"
        _winapi.CreateJunction(str(self.bundle), str(link))
        self.assertTrue(link.is_junction())
        self.assert_error("unsafe_path", lambda: import_bundle(link))
        internal = self.bundle / "frames-junction"
        _winapi.CreateJunction(str(self.bundle / "frames"), str(internal))
        manifest = self.manifest()
        manifest["frames"][0]["path"] = "frames-junction/frame-0001.png"
        self.write_manifest(manifest)
        self.assert_error("unsafe_path", lambda: import_bundle(self.bundle))

    def test_linked_files_rejected(self):
        target = self.bundle / "frames" / "frame-0001.png"
        outside = self.root / "outside.png"
        shutil.copyfile(target, outside)
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest("Creating symbolic links requires host permission")
        self.assert_error("unsafe_path", lambda: import_bundle(self.bundle))

    def test_hash_and_missing_file(self):
        target = self.bundle / "frames" / "frame-0001.png"
        target.write_bytes(target.read_bytes() + b"tampered")
        self.assert_error("hash_mismatch", lambda: import_bundle(self.bundle))
        target.unlink()
        self.assert_error("missing_file", lambda: import_bundle(self.bundle))

    def test_malformed_version_raw_and_size_limits(self):
        original = self.manifest()
        for field, value in [("schema_version", "2.0"), ("provenance", {**original["provenance"], "data_class": "raw"})]:
            manifest = copy.deepcopy(original)
            manifest[field] = value
            self.write_manifest(manifest)
            self.assert_error("schema_invalid", lambda: import_bundle(self.bundle))
        (self.bundle / "manifest.json").write_text("broken CANARY", encoding="utf-8")
        error = self.assert_error("invalid_json", lambda: import_bundle(self.bundle))
        self.assertNotIn("CANARY", str(error))
        shutil.copyfile(FIXTURE / "manifest.json", self.bundle / "manifest.json")
        with patch("plva_skill_learning.ingest.MAX_FRAME_BYTES", 8):
            self.assert_error("size_limit", lambda: import_bundle(self.bundle))
        with patch("plva_skill_learning.ingest.MAX_EVENTS", 2):
            self.assert_error("size_limit", lambda: import_bundle(self.bundle))
        with patch("plva_skill_learning.ingest.MAX_IMAGE_PIXELS", 8):
            self.assert_error("size_limit", lambda: import_bundle(self.bundle))

    def test_screenshot_only_requires_order_and_exposes_inference(self):
        manifest = self.manifest()
        manifest["capture_mode"] = "screenshots_only"
        manifest["outcome"] = {"status": "unknown", "check_ids": []}
        self.write_manifest(manifest)
        self.write_events([e for e in self.events() if e["type"] == "observation"])
        recording = self.approved()
        self.assertTrue(any("inferred" in note for note in recording["warnings"]))
        self.assertTrue(any("gaps" in note for note in recording["warnings"]))
        events = self.events()
        del events[0]["sequence"]
        self.write_events(events)
        self.assert_error("schema_invalid", lambda: import_bundle(self.bundle, self.store))

    def test_model_done_is_not_independent_outcome(self):
        events = self.events()
        for event in events:
            if event["type"] == "check":
                event["source"] = "model_interpretation"
        self.write_events(events)
        recording = self.approved()
        self.assertTrue(any("unverified" in note for note in recording["warnings"]))

    def test_dedup_retains_all_ids_and_action_boundaries(self):
        recording = import_bundle(self.bundle)
        observation = recording["events"][0]
        duplicate = {**observation, "event_id": "duplicate", "sequence": 2}
        changed = {**observation, "event_id": "changed", "sequence": 3, "text": "Tiny validation error appeared."}
        action = {**recording["events"][6], "sequence": 4}
        after = {**changed, "event_id": "after", "sequence": 5}
        recording["events"] = [observation, duplicate, changed, action, after]
        timeline = build_timeline(recording)
        self.assertEqual(len(timeline["events"]), 5)
        self.assertEqual(len(timeline["observations"]), 3)
        self.assertEqual(timeline["observations"][0]["event_ids"], [observation["event_id"], "duplicate"])
        self.assertEqual(timeline["observations"][-1]["event_ids"], ["after"])

    def test_windows_overlap_without_losing_stable_ids(self):
        recording = import_bundle(self.bundle)
        timeline = build_timeline(recording, window_size=6, overlap=2)
        windows = timeline["windows"]
        self.assertTrue(all(len(window) <= 6 for window in windows))
        self.assertEqual(windows[0][-2:], windows[1][:2])
        self.assertEqual({e["event_id"] for window in windows for e in window}, {e["event_id"] for e in recording["events"]})
        self.assertEqual(windows[1][0]["event_id"], "e5")
        self.assert_error("invalid_window", lambda: build_timeline(recording, window_size=4, overlap=4))

    def test_evidence_map_links_frames_and_rejects_missing_ids(self):
        recording = import_bundle(self.bundle)
        workflow = {"steps": [{"step_id": "step-1", "evidence_ids": ["e12"], "basis": "observed", "recovery": []}], "checks": [{"check_id": "c1", "evidence_ids": ["e1", "e12", "e13"], "basis": "observed"}]}
        mapping = evidence_map(recording, workflow)
        self.assertEqual(mapping["data_class"], "synthetic")
        self.assertEqual(mapping["links"][0]["frame_ids"], ["frame-0005", "frame-0006"])
        self.assertNotIn("ADDRESS_1_a3f9", json.dumps(mapping))
        workflow["steps"][0]["evidence_ids"] = ["invented-event"]
        self.assert_error("missing_reference", lambda: evidence_map(recording, workflow))


if __name__ == "__main__":
    unittest.main()
