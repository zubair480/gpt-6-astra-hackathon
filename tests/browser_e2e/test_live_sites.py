"""Opt-in ordinary-site navigation contract checks, never a privacy proof.

PLVA_RUN_LIVE_BROWSER=1 enables network/browser use. Every test creates and
destroys its own profile; no running server or operator browser is attached.
Run: python -m unittest discover -s tests/browser_e2e -p test_live_sites.py -v
"""
from __future__ import annotations

import importlib
import inspect
import io
import os
import tempfile
import unittest
from urllib.parse import urlsplit

from PIL import Image


@unittest.skipUnless(os.environ.get("PLVA_RUN_LIVE_BROWSER") == "1",
                     "opt-in real-site navigation; PLVA_RUN_LIVE_BROWSER=1")
class LiveSiteNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            module = importlib.import_module("plva.browser")
        except ModuleNotFoundError as exc:
            if exc.name == "plva.browser":
                self.skipTest("BrowserSession component is not integrated")
            raise
        browser_class = getattr(module, "BrowserSession", None)
        if browser_class is None:
            self.skipTest("BrowserSession export is not integrated")
        parameters = inspect.signature(browser_class).parameters
        profile_option = next((name for name in
                               ("profile_dir", "user_data_dir", "profile_path")
                               if name in parameters), None)
        if profile_option is None:
            self.skipTest("BrowserSession needs an explicit isolated-profile constructor option")
        self.profile = tempfile.TemporaryDirectory(prefix="plva-independent-live-")
        self.addCleanup(self.profile.cleanup)
        self.browser = browser_class(**{profile_option: self.profile.name})
        self.addAsyncCleanup(self.browser.close)
        await self.browser.start()

    async def checked_capture(self, expected_host):
        capture = await self.browser.capture()
        self.assertIsInstance(capture["png"], bytes)
        self.assertTrue(capture["png"].startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(capture["png"])) as frame:
            frame.load()
            self.assertEqual(frame.size, (capture["width"], capture["height"]))
            self.assertGreater(min(frame.size), 0)
        hostname = urlsplit(capture["url"]).hostname or ""
        self.assertTrue(hostname == expected_host or hostname.endswith("." + expected_host),
                        "Unexpected navigation origin; investigate redirect/barrier locally")
        self.assertTrue(capture["tab_id"])
        self.assertIsInstance(capture["title"], str)
        tabs = await self.browser.tabs()
        self.assertIn(capture["tab_id"], [tab["id"] for tab in tabs])
        await self.browser.select_tab(capture["tab_id"])
        following = await self.browser.capture()
        self.assertEqual(following["tab_id"], capture["tab_id"])
        return capture

    async def test_two_unmodified_form_origins_navigation_only(self):
        # Ordinary publicly hosted forms; do not fill, submit, or modify markup.
        for url, host in (("https://httpbin.org/forms/post", "httpbin.org"),
                          ("https://www.selenium.dev/selenium/web/web-form.html",
                           "selenium.dev")):
            with self.subTest(origin=host):
                await self.browser.open(url)
                await self.checked_capture(host)

    async def test_amazon_public_navigation_only(self):
        # A same-origin CAPTCHA can still satisfy navigation. Human review of
        # the page/barrier is required; this is expressly not a PII mask test.
        await self.browser.open("https://www.amazon.com/")
        await self.checked_capture("amazon.com")


if __name__ == "__main__":
    unittest.main()
