"""Opt-in repeated Amazon capture on a runtime-like daemon Proactor loop.

PLVA_BROWSER_LIVE=1 python -m unittest discover -s tests -p test_browser_persistent_capture.py -v
One temporary visible Edge profile; no login, CAPTCHA, or purchase interaction.
"""
import asyncio
import base64
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest

from PIL import Image

from plva.browser import BrowserSession


class PersistentBrowserWorker:
    """Submit separate serialized requests without closing the owning loop."""
    def __init__(self, profile):
        self.profile = profile
        # Match WebRuntime exactly: construct the loop in its caller thread,
        # then run it in a daemon without setting that thread's default loop.
        self.loop = asyncio.ProactorEventLoop() if hasattr(asyncio, "ProactorEventLoop") else asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Persistent browser worker did not start")
        try:
            self.submit(self._initialize())
        except BaseException:
            self.close()
            raise

    def _run(self):
        self.ready.set()
        self.loop.run_forever()
        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.loop.close()

    async def _initialize(self):
        self.lock = asyncio.Lock()
        self.browser = BrowserSession(profile_dir=self.profile, headless=False,
                                      navigation_timeout_ms=20000)
        await self.browser.start()
        await self.browser.open("https://www.amazon.com/")
        self.page = await self.browser.active_page()
        # A retained session is the control for the per-capture attach/detach path.
        self.control = await self.browser.context.new_cdp_session(self.page)
        target = await self.control.send("Target.getTargetInfo")
        window = await self.control.send("Browser.getWindowForTarget", {
            "targetId": target["targetInfo"]["targetId"]})
        self.window_id = window["windowId"]

    def submit(self, coroutine, timeout=60):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    @staticmethod
    def _local_processing(png):
        # Simulate blocking local detector work without installing/model-loading
        # another OCR instance on the shared machine.
        with Image.open(io.BytesIO(png)) as image:
            image.convert("L").resize((300, 225)).histogram()
        time.sleep(.4)

    async def capture_request(self, label, process_locally=True):
        async with self.lock:
            row = {"stage": label, "worker_thread": threading.get_ident()}
            started = time.monotonic()
            try:
                frame = await self.browser.capture()
                row.update(tab_id=frame["tab_id"], width=frame["width"], height=frame["height"],
                           png_sha256=hashlib.sha256(frame["png"]).hexdigest(),
                           url_is_amazon=frame["url"].startswith("https://www.amazon.com/"))
                if process_locally:
                    await asyncio.to_thread(self._local_processing, frame["png"])
            except Exception as error:
                row["capture_error"] = type(error).__name__
                diagnostic = getattr(self.browser, "last_capture_diagnostics", None) or {}
                row["capture_diagnostic"] = {key: diagnostic[key] for key in ("stage", "reason", "foreground_retry") if key in diagnostic}
            row["capture_seconds"] = round(time.monotonic() - started, 3)
            started = time.monotonic()
            try:
                control = await asyncio.wait_for(self.control.send("Page.captureScreenshot", {
                    "format": "png", "fromSurface": True, "captureBeyondViewport": False}), timeout=20)
                png = base64.b64decode(control["data"], validate=True)
                with Image.open(io.BytesIO(png)) as image:
                    row["retained_session_size"] = list(image.size)
            except Exception as error:
                # Exception class only: browser protocol errors can contain URLs.
                row["retained_session_error"] = type(error).__name__
            row["retained_session_seconds"] = round(time.monotonic() - started, 3)
            print("PERSISTENT_CAPTURE=" + json.dumps(row), flush=True)
            return row

    async def cover(self):
        async with self.lock:
            # Separate context/window in the SAME owned Edge process. It is not
            # a managed content tab and must not replace Amazon as capture source.
            self.cover_context = await self.browser._browser.new_context()
            cover = await self.cover_context.new_page()
            await cover.set_content("<!doctype html><title>Owned cover window</title><body style='background:#334155'>Capture regression cover</body>")
            protocol = await self.cover_context.new_cdp_session(cover)
            target = await protocol.send("Target.getTargetInfo")
            window = await protocol.send("Browser.getWindowForTarget", {"targetId": target["targetInfo"]["targetId"]})
            await protocol.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "maximized"}})
            await cover.bring_to_front()
            await protocol.detach()
            return window["windowId"] != self.window_id

    async def uncover(self):
        async with self.lock:
            await self.cover_context.close()
            await self.page.bring_to_front()

    async def _close(self):
        async with self.lock:
            await self.browser.close()

    def close(self):
        try:
            self.submit(self._close())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(15)


@unittest.skipUnless(os.environ.get("PLVA_BROWSER_LIVE") == "1", "Opt-in real Edge/Amazon test")
class PersistentCaptureTests(unittest.TestCase):
    def test_amazon_repeated_requests_local_processing_and_covered_window(self):
        with tempfile.TemporaryDirectory(prefix="plva-persistent-capture-") as profile:
            worker = PersistentBrowserWorker(profile)
            rows = []
            try:
                for label in ("initial-preview", "next-run-after-caller-return", "next-run-after-local-processing"):
                    rows.append(worker.submit(worker.capture_request(label)))
                    time.sleep(.25)  # The caller returns; the browser loop stays running.
                self.assertTrue(worker.submit(worker.cover()), "Cover must be a different owned browser window")
                rows.append(worker.submit(worker.capture_request("covered-after-processing")))
                worker.submit(worker.uncover())
                rows.append(worker.submit(worker.capture_request("restored-next-request")))
            finally:
                worker.close()
            self.assertFalse(worker.thread.is_alive(), "Browser worker must terminate cleanly")
            for row in rows:
                with self.subTest(stage=row["stage"]):
                    self.assertNotIn("capture_error", row, row)
                    self.assertNotIn("retained_session_error", row, row)
                    self.assertTrue(row["url_is_amazon"])
                    self.assertEqual((row["width"], row["height"]), (1200, 900))
                    self.assertEqual(row["tab_id"], rows[0]["tab_id"])
            self.assertEqual(len({row["worker_thread"] for row in rows}), 1)


if __name__ == "__main__":
    unittest.main()
