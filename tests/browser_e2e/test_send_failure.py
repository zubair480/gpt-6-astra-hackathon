"""Baseline provider-loop boundary probes: mock network, no real provider claim."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plva.privacy import PrivacyError, PrivacySession
from plva.runtime import Runner


class SendFailureTests(unittest.IsolatedAsyncioTestCase):
    def runner(self):
        runner = Runner.__new__(Runner)
        runner.s = SimpleNamespace(stop=threading.Event())
        runner.privacy = PrivacySession()
        runner.task = 'Benign synthetic task'
        runner.key = 'MOCK-NOT-A-CREDENTIAL'
        return runner

    async def test_observation_failure_prevents_client_creation(self):
        for error in (PrivacyError('protection failed'), RuntimeError('detector failed')):
            with self.subTest(error=type(error).__name__):
                runner = self.runner()
                runner.observe = AsyncMock(side_effect=error)
                with patch('plva.runtime.httpx.AsyncClient') as client:
                    with self.assertRaises(type(error)):
                        await runner.astra()
                    client.assert_not_called()

    async def test_stop_before_send_prevents_post(self):
        runner = self.runner()
        runner.s.stop.set()
        runner.observe = AsyncMock(return_value=('MOCK', []))
        with patch('plva.runtime.httpx.AsyncClient') as client:
            post = client.return_value.__aenter__.return_value.post
            with self.assertRaises(InterruptedError):
                await runner.astra()
            post.assert_not_called()
