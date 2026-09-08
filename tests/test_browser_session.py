"""Isolated Edge tests: no existing browser profile or application server used."""
import asyncio
import struct
import tempfile
import unittest

from plva.browser.session import BrowserSession
from plva.privacy import PrivacyError


class URLTests(unittest.TestCase):
    def test_https_urls_and_canonical_origins(self):
        session = BrowserSession()
        self.assertEqual(session.validate_url("https://www.amazon.com/s?k=mugs"), "https://www.amazon.com/s?k=mugs")
        self.assertEqual(session.origin("https://EXAMPLE.com:443/a"), "https://example.com")
        self.assertEqual(session.origin("https://example.com:8443/a"), "https://example.com:8443")

    def test_reject_non_web_or_credential_urls(self):
        for url in ["file:///tmp/a", "javascript:alert(1)", "data:text/html,hi",
                    "http://example.com", "https://name:pass@example.com", "https://",
                    "https://example.com:bad/", "https://example.com/\n",
                    "https://example.com\\@evil.com", "about:blank"]:
            with self.subTest(url=url), self.assertRaises(PrivacyError):
                BrowserSession().validate_url(url)

    def test_loopback_opt_in_is_only_for_tests(self):
        session = BrowserSession(allow_loopback_http=True)
        session.validate_url("http://127.0.0.1:19873/a")
        session.validate_url("http://[::1]:19873/a")
        with self.assertRaises(PrivacyError):
            session.validate_url("http://192.168.1.1/")


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="plva-browser-test-")
        # Headless Chromium has no real selected browser tab; use a visible
        # isolated window for the manual-selection acceptance check.
        self.session = BrowserSession(profile_dir=self.profile.name,
                                      headless=self._testMethodName != "test_tab_selection_popup_and_closed_tab",
                                      viewport={"width": 640, "height": 480})
        await self.session.start()

        async def fixture(route):
            if route.request.url.endswith("/redirect"):
                await route.fulfill(status=302, headers={"location": "https://second.example/"})
            else:
                await route.fulfill(content_type="text/html", body='''<!doctype html>
                    <title>Browser fixture</title><h1>Ordinary page</h1>
                    <a href="https://second.example/" target="_blank">Popup</a>
                    <input type="email" autocomplete="email">''')
        await self.session.context.route("**/*", fixture)

    async def asyncTearDown(self):
        await self.session.close()
        self.profile.cleanup()

    async def test_capture_metadata_and_navigation_authorization(self):
        first_id = await self.session.open("https://first.example/")
        capture = await self.session.capture()
        self.assertEqual(capture["tab_id"], first_id)
        self.assertEqual(capture["url"], "https://first.example/")
        self.assertEqual(capture["title"], "Browser fixture")
        self.assertEqual((capture["width"], capture["height"]), (640, 480))
        self.assertEqual(struct.unpack(">II", capture["png"][16:24]), (640, 480))
        await self.session.navigate("https://second.example/")
        self.assertEqual(self.session.authorized_origins, {"https://first.example"})
        await self.session.back()
        self.assertEqual((await self.session.capture())["url"], "https://first.example/")
        await self.session.forward()
        await self.session.reload()
        self.assertEqual((await self.session.capture())["url"], "https://second.example/")

    async def test_tab_selection_popup_and_closed_tab(self):
        first_id = await self.session.open("https://first.example/")
        second_id = await self.session.open("https://second.example/", new_tab=True)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(await self.session.tabs()), 2)
        await self.session.select_tab(first_id)
        self.assertEqual((await self.session.capture())["tab_id"], first_id)
        # User-like tab change outside BrowserSession.select_tab is detected.
        second = next(page for key, page in self.session._pages.items() if key == second_id)
        await second.bring_to_front()
        self.assertEqual((await self.session.capture())["tab_id"], second_id)
        async with self.session.context.expect_page() as popup_event:
            await second.get_by_text("Popup", exact=True).click()
        popup = await popup_event.value
        await popup.wait_for_load_state("domcontentloaded")
        await popup.bring_to_front()
        self.assertIs(await self.session.active_page(), popup)
        await popup.close()
        self.assertEqual(len(await self.session.tabs()), 2)
        with self.assertRaises(PrivacyError):
            await self.session.select_tab("missing")

    async def test_redirect_does_not_authorize_redirect_destination(self):
        # Simulate the navigation redirect at the transport boundary. Chromium
        # does not reliably re-route a fulfilled 302 to an intercepted fake DNS
        # origin, so avoid depending on external DNS in this permission test.
        from unittest.mock import AsyncMock
        original = self.session.page.goto
        async def redirected(url, **kwargs):
            return await original("https://second.example/", **kwargs)
        self.session.page.goto = AsyncMock(side_effect=redirected)
        await self.session.open("https://first.example/redirect")
        self.assertEqual((await self.session.capture())["url"], "https://second.example/")
        self.assertEqual(self.session.authorized_origins, {"https://first.example"})

    async def test_pause_keeps_manual_preview_available(self):
        def stopped():
            raise InterruptedError("Stopped")
        self.session.stop_check = stopped
        await self.session.open("https://first.example/")
        self.assertTrue((await self.session.capture())["png"])
        with self.assertRaises(InterruptedError):
            await self.session.execute({"type": "wait"}, None)

    async def test_capture_detects_tab_race(self):
        await self.session.open("https://first.example/")
        page = self.session.page
        original = self.session._capture_png

        async def changed(captured_page):
            png = await original(captured_page)
            await page.goto("https://second.example/" if "first" in page.url else "https://first.example/")
            return png
        self.session._capture_png = changed
        with self.assertRaisesRegex(PrivacyError, "changed tabs or navigated"):
            await self.session.capture()


if __name__ == "__main__":
    unittest.main()
