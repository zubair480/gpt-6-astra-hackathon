"""Observation cache behavior with isolated memory state and no browser/API access."""
import base64
import copy
import hashlib
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from PIL import Image

from plva.web_runtime import WebRuntime


def png(color):
    output = io.BytesIO()
    Image.new("RGB", (32, 16), color).save(output, "PNG")
    return output.getvalue()


class WebObservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = SimpleNamespace(lock=threading.RLock(), state={
            "step": 0, "raw_frame": None, "protected_frame": None,
            "manifest": [], "frame_hash": None, "source": "web",
            "stats": {"frames": 0, "masks": 0, "resolved": 0, "model_calls": 0},
            "detector": {"status": "idle"},
        })
        # Avoid constructing a persistent runtime thread or importing real server state.
        server_patch = patch.object(WebRuntime, "s", new_callable=PropertyMock,
                                    return_value=self.server)
        server_patch.start()
        self.addCleanup(server_patch.stop)
        self.runtime = WebRuntime.__new__(WebRuntime)
        self.runtime.stage = "idle"
        self.runtime.cached_raw_hash = None
        self.runtime.cached_protected = None
        self.raw_a, self.raw_b = png("white"), png("yellow")
        self.safe_a, self.safe_b = png("black"), png("blue")
        self.frame_a = {"png": self.raw_a, "tab_id": "tab-a"}
        self.frame_b = {"png": self.raw_b, "tab_id": "tab-a"}
        self.findings = [{"kind": "EMAIL", "value": "synthetic@example.test"}]
        self.result_a = {"png": self.safe_a, "manifest": [{"token": "[EMAIL_1]"}], "count": 1}
        self.result_b = {"png": self.safe_b, "manifest": [{"token": "[EMAIL_2]"}], "count": 1}
        self.runtime.browser = SimpleNamespace(capture=AsyncMock(return_value=self.frame_a))
        self.runtime.metadata = AsyncMock()
        self.runtime.detector = SimpleNamespace(detect=Mock(return_value=self.findings))
        self.runtime.privacy = SimpleNamespace(protect=Mock(return_value=self.result_a))

    async def test_identical_png_reuses_protection_but_updates_observation(self):
        first = await self.runtime.observe()
        # A different tab showing byte-identical pixels still refreshes tab metadata.
        duplicate = {"png": bytes(self.raw_a), "tab_id": "tab-b"}
        self.runtime.browser.capture.return_value = duplicate
        second = await self.runtime.observe()

        self.assertEqual(first, second)
        self.assertEqual(first[0], base64.b64encode(self.safe_a).decode())
        self.runtime.detector.detect.assert_called_once_with(self.raw_a)
        self.runtime.privacy.protect.assert_called_once_with(self.raw_a, self.findings)
        self.assertEqual(self.runtime.browser.capture.await_count, 2)
        self.assertEqual(self.runtime.metadata.await_count, 2)
        self.runtime.metadata.assert_awaited_with(duplicate)
        self.assertEqual(self.server.state["stats"]["frames"], 2)
        self.assertEqual(self.server.state["step"], 2)
        self.assertEqual(self.server.state["frame_hash"], hashlib.sha256(self.safe_a).hexdigest())

    async def test_changed_png_requires_new_detection_and_protection(self):
        first = await self.runtime.observe()
        self.runtime.browser.capture.return_value = self.frame_b
        self.runtime.privacy.protect.return_value = self.result_b
        second = await self.runtime.observe()

        self.assertNotEqual(first, second)
        self.assertEqual(self.runtime.detector.detect.call_count, 2)
        self.runtime.detector.detect.assert_called_with(self.raw_b)
        self.runtime.privacy.protect.assert_called_with(self.raw_b, self.findings)
        self.assertEqual(self.server.state["protected_frame"], base64.b64encode(self.safe_b).decode())
        self.assertEqual(self.runtime.cached_raw_hash, hashlib.sha256(self.raw_b).hexdigest())
        self.assertIs(self.runtime.cached_protected, self.result_b)

    async def test_changed_png_detection_failure_never_publishes_or_returns_old_result(self):
        await self.runtime.observe()
        before = copy.deepcopy(self.server.state)
        old_hash = self.runtime.cached_raw_hash
        self.runtime.browser.capture.return_value = self.frame_b
        self.runtime.detector.detect.side_effect = RuntimeError("Detector unavailable")

        with self.assertRaisesRegex(RuntimeError, "Detector unavailable"):
            await self.runtime.observe()

        self.assertEqual(self.server.state, before)
        self.assertEqual(self.runtime.cached_raw_hash, old_hash)
        self.assertIs(self.runtime.cached_protected, self.result_a)
        self.assertEqual(self.runtime.privacy.protect.call_count, 1)
        self.assertEqual(self.runtime.metadata.await_count, 1)
        self.assertEqual(self.runtime.stage, "detect")

        # Retrying the changed frame must run detection again, never treat it as cached.
        self.runtime.detector.detect.side_effect = None
        self.runtime.privacy.protect.return_value = self.result_b
        result = await self.runtime.observe()
        self.assertEqual(self.runtime.detector.detect.call_count, 3)
        self.assertEqual(result[0], base64.b64encode(self.safe_b).decode())


if __name__ == "__main__":
    unittest.main()
