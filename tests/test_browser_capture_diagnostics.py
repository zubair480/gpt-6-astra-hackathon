"""Capture diagnostics identify failures without reflecting driver payloads."""
import asyncio
import io
import unittest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from plva.browser import BrowserSession
from plva.privacy import PrivacyError


class CaptureDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = BrowserSession()
        self.protocol = MagicMock(send=AsyncMock(), detach=AsyncMock())
        self.session.context = MagicMock(new_cdp_session=AsyncMock(return_value=self.protocol))
        self.page = MagicMock(is_closed=MagicMock(return_value=False))

    async def test_capture_timeout_identified_without_driver_text(self):
        self.protocol.send.side_effect = TimeoutError('https://private.invalid/?token=SECRET_VALUE')
        with self.assertRaisesRegex(PrivacyError, r'capture.timeout') as caught:
            await self.session._capture_png(self.page)
        self.assertNotIn('SECRET_VALUE', str(caught.exception))
        self.assertNotIn('SECRET_VALUE', str(self.session.last_capture_diagnostics))
        self.assertEqual(self.session.last_capture_diagnostics['exception_type'], 'TimeoutError')
        self.protocol.detach.assert_awaited_once()

    async def test_stalled_capture_uses_separate_short_timeout(self):
        self.session.capture_timeout_ms = 10
        cancelled = asyncio.Event()

        async def stalled(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.protocol.send.side_effect = stalled
        with self.assertRaisesRegex(PrivacyError, r'capture.timeout'):
            await asyncio.wait_for(self.session._capture_png(self.page), timeout=1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.session.navigation_timeout_ms, 30000)
        self.protocol.detach.assert_awaited_once()

    async def test_stalled_attach_uses_separate_short_timeout(self):
        self.session.capture_timeout_ms = 10

        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        self.session.context.new_cdp_session.side_effect = stalled
        with self.assertRaisesRegex(PrivacyError, r'attach.timeout'):
            await asyncio.wait_for(self.session._capture_png(self.page), timeout=1)
        self.protocol.detach.assert_not_awaited()

    async def test_attach_failure_identified(self):
        self.session.context.new_cdp_session.side_effect = RuntimeError('PRIVATE_PAGE_TEXT')
        with self.assertRaisesRegex(PrivacyError, r'attach.failed'):
            await self.session._capture_png(self.page)
        self.assertNotIn('PRIVATE_PAGE_TEXT', str(self.session.last_capture_diagnostics))
        self.protocol.detach.assert_not_awaited()

    async def test_invalid_image_identified(self):
        self.protocol.send.return_value = {'data': 'bm90IGEgcG5n'}
        with self.assertRaisesRegex(PrivacyError, r'image.failed'):
            await self.session._capture_png(self.page)

    async def test_disconnect_and_cleanup_failure_do_not_expose_driver_text(self):
        self.protocol.send.side_effect = RuntimeError('PRIVATE_PAGE_TEXT')
        self.protocol.detach.side_effect = RuntimeError('PRIVATE_PAGE_TEXT')
        self.page.is_closed.return_value = True
        with self.assertRaisesRegex(PrivacyError, r'capture.page_closed'):
            await self.session._capture_png(self.page)


class CaptureRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = BrowserSession()
        self.page = MagicMock(url='https://example.test/', title=AsyncMock(return_value='Fixture'),
                              bring_to_front=AsyncMock())
        self.session._pages = {'1': self.page}
        self.session._page = self.page
        self.session._revisions = {self.page: 0}
        self.session.active_page = AsyncMock(return_value=self.page)
        output = io.BytesIO()
        Image.new('RGB', (640, 480), 'green').save(output, format='PNG')
        self.png = output.getvalue()
        self.session.last_capture_diagnostics = {'stage': 'capture', 'reason': 'timeout'}

    async def test_capture_retries_same_selected_page_once_and_exposes_recovery(self):
        self.session._capture_png = AsyncMock(side_effect=[PrivacyError('capture'), self.png])
        frame = await self.session.capture()
        self.assertEqual(frame['tab_id'], '1')
        self.assertEqual(frame['capture_recovery'], 'foreground')
        self.assertEqual(self.session._capture_png.await_count, 2)
        self.page.bring_to_front.assert_awaited_once()

    async def test_capture_does_not_loop_on_repeated_failure(self):
        self.session._capture_png = AsyncMock(side_effect=PrivacyError('capture'))
        with self.assertRaises(PrivacyError):
            await self.session.capture()
        self.assertEqual(self.session._capture_png.await_count, 2)
        self.page.bring_to_front.assert_awaited_once()
        self.assertTrue(self.session.last_capture_diagnostics['foreground_retry'])

    async def test_changed_selected_page_is_never_brought_back(self):
        other = MagicMock()
        self.session.active_page.side_effect = [self.page, other, self.page, other]
        self.session._capture_png = AsyncMock(side_effect=PrivacyError('capture'))
        with self.assertRaises(PrivacyError):
            await self.session.capture()
        self.page.bring_to_front.assert_not_awaited()

    async def test_decode_failure_is_not_retried(self):
        self.session.last_capture_diagnostics = {'stage': 'decode', 'reason': 'failed'}
        self.session._capture_png = AsyncMock(side_effect=PrivacyError('decode'))
        with self.assertRaises(PrivacyError):
            await self.session.capture()
        self.assertEqual(self.session._capture_png.await_count, 1)
        self.page.bring_to_front.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
