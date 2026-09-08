"""Regression for visible Edge capture while its own window is minimized."""
import asyncio
import io
import os
import tempfile
import time
import unittest

from PIL import Image
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from plva.browser import BrowserSession


@unittest.skipUnless(os.environ.get('PLVA_RUN_BROWSER_TESTS') == '1',
                     'Set PLVA_RUN_BROWSER_TESTS=1 for visible Edge capture tests')
class CoveredWindowCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.profile = tempfile.TemporaryDirectory(prefix="plva-covered-capture-")
        self.session = BrowserSession(profile_dir=self.profile.name, headless=False,
                                      viewport={"width": 640, "height": 480})
        await self.session.start()

        async def fixture(route):
            second = "second.example" in route.request.url
            colors = ("rgb(110,20,150)", "rgb(240,200,20)") if second else ("rgb(20,60,180)", "rgb(20,150,60)")
            await route.fulfill(content_type="text/html", body=f'''<!doctype html>
                <title>{"Second" if second else "First"} capture fixture</title>
                <style>
                  html,body {{margin:0;padding:0;scroll-behavior:auto}}
                  section {{height:480px}}
                  .moving {{position:fixed;left:0;top:0;width:16px;height:16px;
                    background:red;animation:pulse 1s infinite alternate}}
                  @keyframes pulse {{from {{opacity:.2}} to {{opacity:1}}}}
                </style>
                <section style="background:{colors[0]}"></section>
                <section style="background:{colors[1]}"></section>
                <section style="background:rgb(40,40,40)"></section>
                <div class="moving"></div>''')
        await self.session.context.route("**/*", fixture)
        self.first_id = await self.session.open("https://first.example/")
        self.first = self.session.page
        self.protocol = await self.session.context.new_cdp_session(self.first)
        target = await self.protocol.send("Target.getTargetInfo")
        window = await self.protocol.send("Browser.getWindowForTarget", {"targetId": target["targetInfo"]["targetId"]})
        self.window_id = window["windowId"]

    async def asyncTearDown(self):
        await self.session.close()
        self.profile.cleanup()

    async def minimize(self):
        await self.protocol.send("Browser.setWindowBounds", {
            "windowId": self.window_id, "bounds": {"windowState": "minimized"}})
        # Browser launch flags may keep document visibility "visible" while
        # minimized; assert the actual window state instead of page emulation.
        for _ in range(30):
            state = await self.protocol.send("Browser.getWindowBounds", {"windowId": self.window_id})
            if state["bounds"]["windowState"] == "minimized":
                return
            await asyncio.sleep(.05)
        self.fail("Isolated Edge window did not become minimized")

    async def restore(self):
        await self.protocol.send("Browser.setWindowBounds", {
            "windowId": self.window_id, "bounds": {"windowState": "normal"}})
        await self.first.bring_to_front()

    def assert_frame(self, frame, tab_id, url, pixel):
        self.assertEqual(frame["tab_id"], tab_id)
        self.assertEqual(frame["url"], url)
        self.assertEqual((frame["width"], frame["height"]), (640, 480))
        with Image.open(io.BytesIO(frame["png"])) as image:
            self.assertEqual(image.size, (640, 480))
            self.assertEqual(image.convert("RGB").getpixel((100, 100)), pixel)

    async def test_original_animated_screenshot_path_is_bounded_when_minimized(self):
        await self.minimize()
        started = time.monotonic()
        try:
            png = await self.first.screenshot(type="png", full_page=False,
                                              animations="disabled", scale="css", timeout=1500)
            self.assertTrue(png.startswith(b"\x89PNG"))
            outcome = "completed"
        except PlaywrightTimeoutError:
            outcome = "timed out as reported"
        print(f"Original minimized screenshot path {outcome} in {time.monotonic() - started:.2f}s")

    async def test_capture_minimized_scrolled_viewport_restore_and_manual_tab_change(self):
        await self.first.evaluate("window.scrollTo(0,480)")
        self.assertEqual(await self.first.evaluate("window.scrollY"), 480)
        await self.minimize()
        frame = await asyncio.wait_for(self.session.capture(), timeout=10)
        self.assert_frame(frame, self.first_id, "https://first.example/", (20, 150, 60))
        await self.first.evaluate("document.querySelectorAll('section')[1].style.background='rgb(80,170,90)'")
        frame = await asyncio.wait_for(self.session.capture(), timeout=10)
        self.assert_frame(frame, self.first_id, "https://first.example/", (80, 170, 90))
        await self.restore()
        frame = await asyncio.wait_for(self.session.capture(), timeout=10)
        self.assert_frame(frame, self.first_id, "https://first.example/", (80, 170, 90))

        second_id = await self.session.open("https://second.example/", new_tab=True)
        second = self.session.page
        await self.session.select_tab(self.first_id)
        # External selection bypasses BrowserSession.select_tab deliberately.
        await second.bring_to_front()
        frame = await asyncio.wait_for(self.session.capture(), timeout=10)
        self.assert_frame(frame, second_id, "https://second.example/", (110, 20, 150))
        await self.first.bring_to_front()
        frame = await asyncio.wait_for(self.session.capture(), timeout=10)
        self.assert_frame(frame, self.first_id, "https://first.example/", (80, 170, 90))


if __name__ == "__main__":
    unittest.main()
