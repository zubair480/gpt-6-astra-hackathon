"""Focused action-boundary tests; no browser, API key, or server required."""
import copy
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from plva.privacy import PrivacyError, PrivacySession
from plva.runtime import Runner


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runner = Runner.__new__(Runner)
        self.runner.privacy = PrivacySession()
        self.runner.s = SimpleNamespace(
            lock=threading.Lock(), stop=threading.Event(),
            state={"message": "", "events": [], "step": 0,
                   "raw_frame": None, "protected_frame": None,
                   "manifest": [], "stats": {"resolved": 0, "frames": 0, "masks": 0}},
        )
        self.runner.page = MagicMock()
        self.runner.page.url = "http://127.0.0.1:18080/demo/shipping"
        self.runner.page.evaluate = AsyncMock(return_value="EMAIL")
        self.runner.page.keyboard.insert_text = AsyncMock()
        self.runner.page.mouse.click = AsyncMock()
        png = io.BytesIO()
        Image.new("RGB", (200, 80), "white").save(png, format="PNG")
        self.png = png.getvalue()
        self.runner.privacy.protect(self.png, [
            {"kind": kind, "value": value, "label": kind,
             "x": 1, "y": 1, "width": 100, "height": 20}
            for kind, value in (("EMAIL", "alice@example.com"),
                                ("SECRET", "sk-hidden123456789"))
        ])

    async def test_matching_destination_resolves_only_at_execution(self):
        with patch("plva.runtime.asyncio.sleep", new_callable=AsyncMock):
            await self.runner.action({"type": "type", "text": "[EMAIL_1]"})
        self.runner.page.keyboard.insert_text.assert_awaited_once_with("alice@example.com")
        self.assertEqual(self.runner.s.state["stats"]["resolved"], 1)
        self.assertNotIn("alice@example.com", str(self.runner.s.state["events"]))
        self.assertIn("[EMAIL_1]", str(self.runner.s.state["events"]))

    async def test_wrong_destination_rejects_without_inserting(self):
        for origin, field in (("http://example.com/demo/shipping", "EMAIL"),
                              ("http://127.0.0.1:18080/demo/shipping", "NAME")):
            with self.subTest(origin=origin, field=field):
                self.runner.page.url = origin
                self.runner.page.evaluate.return_value = field
                with self.assertRaises(PrivacyError):
                    await self.runner.action({"type": "type", "text": "[EMAIL_1]"})
        self.runner.page.keyboard.insert_text.assert_not_awaited()
        self.assertEqual(self.runner.s.state["stats"]["resolved"], 0)

    async def test_secret_rejects_even_in_matching_field(self):
        self.runner.page.evaluate.return_value = "SECRET"
        with self.assertRaises(PrivacyError):
            await self.runner.action({"type": "type", "text": "[SECRET_1]"})
        self.runner.page.keyboard.insert_text.assert_not_awaited()
        self.assertEqual(self.runner.s.state["stats"]["resolved"], 0)

    async def test_stop_prevents_computer_action(self):
        self.runner.s.stop.set()
        with self.assertRaises(InterruptedError):
            await self.runner.action({"type": "click", "x": 10, "y": 20})
        self.runner.page.mouse.click.assert_not_awaited()
        self.assertEqual(self.runner.s.state["events"], [])

    async def test_failed_protection_does_not_publish_raw_observation(self):
        self.runner.page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
        self.runner.page.screenshot = AsyncMock(return_value=self.png)
        before = copy.deepcopy(self.runner.s.state)
        with patch.object(self.runner.privacy, "protect", side_effect=PrivacyError("Failed")):
            with self.assertRaises(PrivacyError):
                await self.runner.observe()
        self.runner.page.screenshot.assert_awaited_once()
        self.assertEqual(self.runner.s.state, before)


if __name__ == "__main__":
    unittest.main()
