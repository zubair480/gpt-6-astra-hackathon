"""Bounded startup polling while Edge publishes its debugging endpoint."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from plva.browser import BrowserSession


class StartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = BrowserSession()
        self.session._process = MagicMock(returncode=None)
        self.port_file = MagicMock()

    async def test_locked_then_valid_file(self):
        self.port_file.read_text.side_effect = [PermissionError(), '12345\n/devtools/browser/test']
        with patch('plva.browser.session.asyncio.sleep', new_callable=AsyncMock) as sleep:
            self.assertEqual(await self.session._wait_for_debug_port(self.port_file), '12345')
        sleep.assert_awaited_once_with(.1)

    async def test_missing_and_partial_file_then_valid(self):
        self.port_file.read_text.side_effect = [FileNotFoundError(), '12345', '12345\n/devtools/browser/test']
        with patch('plva.browser.session.asyncio.sleep', new_callable=AsyncMock) as sleep:
            self.assertEqual(await self.session._wait_for_debug_port(self.port_file), '12345')
        self.assertEqual(sleep.await_count, 2)

    async def test_persistent_lock_exhausts_original_budget(self):
        self.port_file.read_text.side_effect = PermissionError()
        with patch('plva.browser.session.asyncio.sleep', new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(RuntimeError, 'did not expose'):
                await self.session._wait_for_debug_port(self.port_file)
        self.assertEqual(sleep.await_count, 150)

    async def test_exited_process_does_not_wait(self):
        self.session._process.returncode = 1
        with self.assertRaisesRegex(RuntimeError, 'browser exited'):
            await self.session._wait_for_debug_port(self.port_file)
        self.port_file.read_text.assert_not_called()

    async def test_unrelated_io_error_is_not_hidden(self):
        self.port_file.read_text.side_effect = OSError('unrelated I/O failure')
        with self.assertRaises(OSError):
            await self.session._wait_for_debug_port(self.port_file)
