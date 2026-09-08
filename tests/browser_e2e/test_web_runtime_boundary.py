"""Actual web loop boundary probes with isolated state and mocked provider."""
import importlib.util
import threading
import unittest
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from plva.privacy import PrivacyError, PrivacySession


@unittest.skipUnless(importlib.util.find_spec('plva.web_runtime'),
                     'WebRuntime is not integrated')
class WebBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def make_runtime(self):
        from plva.web_runtime import WebRuntime
        state = SimpleNamespace(stop=threading.Event(), lock=threading.Lock(),
                                state={'stats': {'model_calls': 0, 'resolved': 0},
                                       'step': 1, 'detector': {'latency_ms': 0}},
                                requests=[])

        class IsolatedRuntime(WebRuntime):
            @property
            def s(self):
                return state

        runtime = IsolatedRuntime.__new__(IsolatedRuntime)
        runtime.privacy = PrivacySession()
        runtime.detector = None
        runtime.browser = SimpleNamespace(execute=AsyncMock(return_value={'resolved': 0}),
                                         capture=AsyncMock())
        runtime.event = MagicMock()
        provider = ModuleType('plva.provider')
        provider.AstraProvider = MagicMock()
        provider.AstraProvider.return_value.respond = AsyncMock(
            side_effect=AssertionError('Unexpected provider send'))
        return runtime, provider

    async def test_observation_failures_never_call_provider(self):
        for error in (RuntimeError('capture failed'), RuntimeError('OCR failed'),
                      PrivacyError('redaction failed')):
            with self.subTest(stage=str(error)):
                runtime, provider = self.make_runtime()
                runtime.observe = AsyncMock(side_effect=error)
                with patch.dict('sys.modules', {'plva.provider': provider}):
                    with self.assertRaises(type(error)):
                        await runtime.run('Synthetic task', 'MOCK')
                provider.AstraProvider.return_value.respond.assert_not_awaited()

    async def test_real_observation_stage_failure_sets_error_and_never_sends(self):
        # Exercise actual command -> run -> observe -> detector/protection wiring.
        # Mock only the capture source, failure-producing component and provider.
        for stage in ('detector', 'protection'):
            with self.subTest(stage=stage):
                runtime, provider = self.make_runtime()
                runtime.guard = None
                runtime.cached_raw_hash = runtime.cached_protected = None
                png = b'local-synthetic-png-input'
                runtime.browser.capture.return_value = {'png': png}
                runtime.detector = SimpleNamespace(detect=MagicMock(return_value=[]))
                if stage == 'detector':
                    runtime.detector.detect.side_effect = RuntimeError('Forced local detector failure')
                with patch.object(runtime.privacy, 'protect',
                                  side_effect=PrivacyError('Forced protection failure')) as protect:
                    with patch.dict('sys.modules', {'plva.provider': provider}):
                        result = await runtime.command('run', 'Synthetic task', 'MOCK')
                runtime.detector.detect.assert_called_once_with(png)
                if stage == 'detector':
                    protect.assert_not_called()
                else:
                    protect.assert_called_once_with(png, [])
                provider.AstraProvider.return_value.respond.assert_not_awaited()
                self.assertIn('error', result)
                self.assertEqual(runtime.s.state['status'], 'error')
                self.assertIsNone(runtime.s.state['protected_frame'])
                self.assertIsNone(runtime.cached_protected)
                self.assertEqual(runtime.s.requests, [])

    async def test_stop_during_observation_never_calls_provider(self):
        runtime, provider = self.make_runtime()

        async def stopped_observation():
            runtime.s.stop.set()
            return 'MOCK', []

        runtime.observe = stopped_observation
        with patch.dict('sys.modules', {'plva.provider': provider}):
            with self.assertRaises(InterruptedError):
                await runtime.run('Synthetic task', 'MOCK')
        provider.AstraProvider.return_value.respond.assert_not_awaited()

    def mock_action_response(self, call_type):
        """Deliberately mocked output, never a provider receipt acceptance proof."""
        if call_type == 'computer_call':
            call = {'type': call_type, 'call_id': 'mock-call',
                    'actions': [{'type': 'scroll', 'x': 10, 'y': 10,
                                 'direction': 'down', 'pixels': 100}]}
        else:
            call = {'type': call_type, 'call_id': 'mock-call',
                    'name': 'navigate_browser',
                    'arguments': '{"url":"https://example.com/"}'}
        return ({'id': 'mock-response', 'output': [call]},
                {'response_id': 'mock-response', 'status': 'responded'})

    async def test_stop_while_provider_pending_blocks_actions_and_followup(self):
        for call_type in ('computer_call', 'function_call'):
            with self.subTest(call_type=call_type):
                runtime, provider = self.make_runtime()
                runtime.observe = AsyncMock(return_value=('MOCK-PROTECTED-FRAME', []))

                async def stopped_response(**kwargs):
                    # Simulate stop arriving after send and before response return.
                    runtime.s.stop.set()
                    return self.mock_action_response(call_type)

                respond = provider.AstraProvider.return_value.respond
                respond.side_effect = stopped_response
                with patch.dict('sys.modules', {'plva.provider': provider}):
                    with self.assertRaises(InterruptedError):
                        await runtime.run('Synthetic task', 'MOCK')
                respond.assert_awaited_once()
                runtime.browser.execute.assert_not_awaited()
                runtime.observe.assert_awaited_once()
                self.assertEqual(runtime.s.state['stats']['model_calls'], 1)
                # The already-returned mock response may be retained in audit.
                self.assertEqual(len(runtime.s.requests), 1)

    async def test_followup_capture_failure_blocks_second_send(self):
        for call_type in ('computer_call', 'function_call'):
            with self.subTest(call_type=call_type):
                runtime, provider = self.make_runtime()
                actual_observe = runtime.observe
                capture_failure = RuntimeError('Synthetic followup capture failure')
                runtime.browser.capture.side_effect = capture_failure
                observation_count = 0

                async def first_frame_then_failed_capture():
                    nonlocal observation_count
                    observation_count += 1
                    if observation_count == 1:
                        return 'MOCK-PROTECTED-FRAME', []
                    # Exercise the real observation capture branch; it raises
                    # before OCR/redaction and performs no real browser access.
                    return await actual_observe()

                runtime.observe = AsyncMock(side_effect=first_frame_then_failed_capture)
                respond = provider.AstraProvider.return_value.respond
                respond.side_effect = None
                respond.return_value = self.mock_action_response(call_type)
                with patch.dict('sys.modules', {'plva.provider': provider}):
                    with self.assertRaisesRegex(RuntimeError, 'followup capture failure'):
                        await runtime.run('Synthetic task', 'MOCK')
                respond.assert_awaited_once()
                runtime.browser.execute.assert_awaited_once()
                runtime.browser.capture.assert_awaited_once()
                self.assertEqual(runtime.observe.await_count, 2)
                self.assertEqual(runtime.s.state['stats']['model_calls'], 1)
                self.assertEqual(len(runtime.s.requests), 1)
