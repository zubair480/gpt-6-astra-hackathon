"""Dedicated operator-visible browser. All returned pixels/metadata stay local."""
import asyncio
import base64
import io
import os
import struct
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from PIL import Image

from ..privacy import PrivacyError


class BrowserSession:
    def __init__(self, *, profile_dir=None, headless=False, channel="msedge",
                 viewport=None, allow_loopback_http=False, stop_check=None,
                 navigation_timeout_ms=30000, capture_timeout_ms=5000):
        # This is an application-owned profile, never the user's normal Edge data.
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        self.profile_dir = Path(profile_dir) if profile_dir else base / "PLVA" / "BrowserProfile"
        self.headless, self.channel = headless, channel
        self.viewport = viewport or {"width": 1200, "height": 900}
        self.allow_loopback_http = allow_loopback_http
        self.stop_check = stop_check
        self.navigation_timeout_ms = navigation_timeout_ms
        self.capture_timeout_ms = capture_timeout_ms
        self.authorized_origins = set()
        self.context = None
        self._playwright = None
        self._page = None
        self._pages = {}
        self._revisions = {}
        self._prepared_pages = set()
        self._process = None
        self._browser = None
        self._counter = 0
        self._loop = None
        self.last_capture_diagnostics = None

    @property
    def page(self):
        return self._page

    @property
    def active_tab_id(self):
        return next((key for key, page in self._pages.items() if page is self._page), None)

    def _check(self):
        if self._loop is not None and asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("BrowserSession must use its owning event loop")

    def check_cancelled(self):
        self._check()
        if self.stop_check:
            self.stop_check()

    @staticmethod
    def origin(url):
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().encode("idna").decode("ascii")
            if ":" in host:
                host = "[" + host + "]"
            port = parsed.port
            suffix = "" if port is None or (parsed.scheme, port) in (("https", 443), ("http", 80)) else ":" + str(port)
            return parsed.scheme.lower() + "://" + host + suffix
        except (ValueError, UnicodeError):
            raise PrivacyError("Invalid navigation URL") from None

    def validate_url(self, url):
        if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
            raise PrivacyError("Invalid navigation URL")
        try:
            parsed = urlsplit(url)
            permitted = parsed.scheme == "https" or (
                self.allow_loopback_http and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
            if not permitted or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError()
            self.origin(url)  # Also validates malformed ports and host encoding.
        except (ValueError, UnicodeError):
            raise PrivacyError("Navigation requires an ordinary HTTPS URL") from None
        return url

    def _register(self, page):
        if page in self._pages.values():
            return
        self._counter += 1
        self._pages[str(self._counter)] = page
        self._revisions[page] = 0
        # A new tab/popup becomes the selected content source. Manual selection
        # is refreshed from browser visibility metadata before capture/actions.
        self._page = page
        page.on("close", lambda: self._remove(page))
        page.on("framenavigated", lambda frame: self._navigated(page, frame))

    def _navigated(self, page, frame):
        if frame is page.main_frame and page in self._revisions:
            self._revisions[page] += 1

    def _remove(self, page):
        self._pages = {key: p for key, p in self._pages.items() if p is not page}
        self._revisions.pop(page, None)
        self._prepared_pages.discard(page)
        if self._page is page:
            self._page = next(reversed(self._pages.values()), None)

    def _browser_executable(self):
        if self.channel == "chromium":
            return self._playwright.chromium.executable_path
        if self.channel != "msedge":
            raise ValueError("Supported browser channels are msedge and chromium")
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                if path.is_file():
                    return str(path)
        raise RuntimeError("Microsoft Edge is required for the visible PLVA browser")

    async def _wait_for_debug_port(self, port_file):
        # Edge may publish the file before its Windows write handle is released.
        # Retry only missing/locked reads, within the original startup budget.
        for _ in range(150):
            if self._process.returncode is not None:
                raise RuntimeError("Dedicated browser exited; its profile may already be in use")
            try:
                lines = port_file.read_text().splitlines()
            except (FileNotFoundError, PermissionError):
                lines = []
            if len(lines) >= 2 and lines[0].isdigit():
                return lines[0]
            await asyncio.sleep(.1)
        raise RuntimeError("Dedicated browser did not expose its local control endpoint")

    async def start(self):
        self._check()
        if self.context and self._browser and not self._browser.is_connected():
            await self.close()
        if self.context:
            return self
        self._loop = asyncio.get_running_loop()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            # Launch our own browser and attach without Playwright's default
            # focus emulation. launch_persistent_context marks *every* tab as
            # focused, preventing correct detection of operator tab switches.
            port_file = self.profile_dir / "DevToolsActivePort"
            port_file.unlink(missing_ok=True)
            args = [self._browser_executable(), "--user-data-dir=" + str(self.profile_dir.resolve()),
                    "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                    "--disable-features=BackForwardCache,CalculateNativeWinOcclusion",
                    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                    "--disable-extensions",
                    "--no-first-run", "--no-default-browser-check", "about:blank"]
            if self.headless:
                args.insert(1, "--headless=new")
            self._process = await asyncio.create_subprocess_exec(
                *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            port = await self._wait_for_debug_port(port_file)
            self._browser = await self._playwright.chromium.connect_over_cdp(
                "http://127.0.0.1:" + port, no_defaults=True, timeout=self.navigation_timeout_ms)
            protocol = await self._browser.new_browser_cdp_session()
            await protocol.send("Browser.setDownloadBehavior", {"behavior": "deny"})
            await protocol.detach()
            self.context = self._browser.contexts[0]
            self.context.set_default_navigation_timeout(self.navigation_timeout_ms)
            self.context.on("page", self._register)
            for page in self.context.pages:
                self._register(page)
            if not self._pages:
                self._register(await self.context.new_page())
            return self
        except BaseException:
            await self.close()
            raise

    async def active_page(self):
        self._check()
        if not self.context:
            raise RuntimeError("BrowserSession is not started")
        visible = []
        focused = []
        for page in list(self._pages.values()):
            if page.is_closed():
                self._remove(page)
                continue
            if page not in self._prepared_pages:
                await page.set_viewport_size(self.viewport)
                self._prepared_pages.add(page)
            try:
                # Generic browser state only: no DOM text or form values.
                state = await page.evaluate("({visible: document.visibilityState === 'visible', focused: document.hasFocus()})")
                if state["visible"]:
                    visible.append(page)
                    if state["focused"]:
                        focused.append(page)
            except Exception:
                # A navigating document may temporarily have no execution context.
                continue
        if len(focused) == 1:
            self._page = focused[0]
        elif len(visible) == 1:
            self._page = visible[0]
        if self._page is None or self._page.is_closed():
            raise PrivacyError("No open browser tab; open a website first")
        return self._page

    async def open(self, url, *, new_tab=False):
        self.validate_url(url)
        await self.start()
        if new_tab or self._page is None:
            page = await self.context.new_page()
            self._register(page)
            await page.bring_to_front()
        return await self.navigate(url, authorize=True)

    async def navigate(self, url, *, authorize=False):
        self._check()
        self.validate_url(url)
        page = await self.active_page()
        await page.goto(url, wait_until="domcontentloaded")
        self.validate_url(page.url)
        if authorize:
            # Redirects do not implicitly authorize a different token destination.
            self.authorized_origins.add(self.origin(url))
        return self.active_tab_id

    async def back(self):
        page = await self.active_page()
        await page.go_back(wait_until="domcontentloaded")
        self.validate_url(page.url)

    async def forward(self):
        page = await self.active_page()
        await page.go_forward(wait_until="domcontentloaded")
        self.validate_url(page.url)

    async def reload(self):
        page = await self.active_page()
        self.validate_url(page.url)
        await page.reload(wait_until="domcontentloaded")
        self.validate_url(page.url)

    async def tabs(self):
        self._check()
        if not self.context or not self._pages:
            return []
        await self.active_page()
        result = []
        for tab_id, page in list(self._pages.items()):
            if not page.is_closed():
                result.append({"id": tab_id, "url": page.url, "title": await page.title()})
        return result

    async def select_tab(self, tab_id):
        self._check()
        page = self._pages.get(str(tab_id))
        if page is None or page.is_closed():
            raise PrivacyError("Unknown browser tab")
        await page.bring_to_front()
        self._page = page
        return str(tab_id)

    async def _capture_png(self, page):
        # Playwright's screenshot preparation waits for animation frames/fonts.
        # Those can stop when the operator covers or minimizes the Edge window.
        # Capture this page's compositor surface directly, never the desktop.
        started = time.monotonic()
        stage = "attach"
        protocol = None
        try:
            protocol = await asyncio.wait_for(self.context.new_cdp_session(page),
                                             timeout=self.capture_timeout_ms / 1000)
            stage = "capture"
            result = await asyncio.wait_for(protocol.send("Page.captureScreenshot", {
                "format": "png", "fromSurface": True, "captureBeyondViewport": False,
            }), timeout=self.capture_timeout_ms / 1000)
            stage = "decode"
            png = base64.b64decode(result["data"], validate=True)
            # Computer-action coordinates are CSS viewport pixels even on a
            # monitor with display scaling. Normalize before local detection.
            stage = "image"
            with Image.open(io.BytesIO(png)) as image:
                size = (self.viewport["width"], self.viewport["height"])
                if image.size != size:
                    output = io.BytesIO()
                    image.resize(size, Image.Resampling.LANCZOS).save(output, format="PNG")
                    png = output.getvalue()
            self.last_capture_diagnostics = {
                "status": "ok", "elapsed_ms": round((time.monotonic() - started) * 1000)}
            return png
        except Exception as exc:
            # Fixed reason codes only: driver errors may contain private URLs,
            # page content or payloads. Never expose their message/repr.
            reason = "timeout" if isinstance(exc, TimeoutError) else "failed"
            if page.is_closed():
                reason = "page_closed"
            elif self._browser and not self._browser.is_connected():
                reason = "browser_disconnected"
            self.last_capture_diagnostics = {
                "status": "error", "stage": stage, "reason": reason,
                "exception_type": type(exc).__name__ if type(exc).__name__ in {
                    "Error", "TimeoutError", "TargetClosedError", "ValueError",
                    "KeyError", "UnidentifiedImageError", "OSError", "RuntimeError"} else "Exception",
                "elapsed_ms": round((time.monotonic() - started) * 1000)}
            raise PrivacyError(f"Browser viewport capture failed [{stage}.{reason}]; retry local preview") from None
        finally:
            if protocol is not None:
                try:
                    await asyncio.wait_for(protocol.detach(), timeout=2)
                except Exception:
                    # The operator may close this tab during capture or cleanup.
                    pass

    async def capture(self):
        foreground_retried = False
        for _ in range(2):
            page = await self.active_page()
            url = self.validate_url(page.url)
            revision = self._revisions.get(page)
            tab_id = self.active_tab_id
            title = await page.title()
            try:
                png = await self._capture_png(page)
            except PrivacyError:
                diagnostic = self.last_capture_diagnostics or {}
                if (foreground_retried or diagnostic.get("stage") != "capture"
                        or diagnostic.get("reason") not in {"timeout", "failed"}):
                    raise
                # Some Windows compositor states still refuse hidden capture.
                # Retry once with the SAME selected page visible. Never switch
                # back to a stale tab if the operator selected another one.
                if await self.active_page() is not page or self._revisions.get(page) != revision:
                    continue
                foreground_retried = True
                await page.bring_to_front()
                if await self.active_page() is not page or self._revisions.get(page) != revision:
                    continue
                try:
                    png = await self._capture_png(page)
                finally:
                    if self.last_capture_diagnostics is not None:
                        self.last_capture_diagnostics["foreground_retry"] = True
            if self.last_capture_diagnostics is not None:
                self.last_capture_diagnostics["foreground_retry"] = foreground_retried
            if await self.active_page() is not page or page.url != url or self._revisions.get(page) != revision:
                continue
            if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
                raise PrivacyError("Browser capture did not return a PNG")
            width, height = struct.unpack(">II", png[16:24])
            return {"png": png, "width": width, "height": height,
                    "tab_id": tab_id, "url": url, "title": title,
                    "capture_recovery": "foreground" if foreground_retried else None}
        raise PrivacyError("Browser changed tabs or navigated during capture; retry preview")

    async def execute(self, action, privacy):
        self.check_cancelled()
        from .actions import execute_action
        return await execute_action(self, action, privacy)

    async def close(self):
        # Closing remains available even when the operator's stop flag is set.
        playwright = self._playwright
        self.context = self._playwright = self._page = None
        self._pages.clear()
        self._revisions.clear()
        self._prepared_pages.clear()
        self.authorized_origins.clear()
        try:
            if self._browser and self._browser.is_connected():
                try:
                    protocol = await self._browser.new_browser_cdp_session()
                    await protocol.send("Browser.close")
                except Exception:
                    # The operator may have closed Edge during this await.
                    # Still reap only the process we launched below.
                    pass
        finally:
            if self._process:
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self._process.terminate()
                    await self._process.wait()
                self._process = None
            self._browser = None
            if playwright:
                await playwright.stop()
            self._loop = None
