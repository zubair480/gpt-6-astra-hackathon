import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from plva.browser.actions import execute_action
from plva.privacy import PrivacyError, PrivacySession


class BrowserActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.privacy = PrivacySession()
        self.token = self.privacy._register('EMAIL', 'private@example.net')
        self.field = dict(origin='https://example.org', focused=True, visible=True, editable=True,
                          type='email', autocomplete='email', name='email', id='',
                          role='', label='', search=False, formOrigin='', formMethod='')
        self.handle = SimpleNamespace(evaluate=AsyncMock(side_effect=[self.field, True]), dispose=AsyncMock())
        self.page = SimpleNamespace(url='https://example.org/contact',
                                    evaluate_handle=AsyncMock(return_value=self.handle),
                                    keyboard=SimpleNamespace(insert_text=AsyncMock(), press=AsyncMock()),
                                    mouse=SimpleNamespace(click=AsyncMock(), move=AsyncMock(), wheel=AsyncMock()))
        self.session = SimpleNamespace(check_cancelled=Mock(), validate_url=Mock(), active_page=AsyncMock(return_value=self.page),
                                       authorized_origins={'https://example.org'},
                                       origin=lambda url: '/'.join(url.split('/')[:3]),
                                       navigate=AsyncMock(), back=AsyncMock(), forward=AsyncMock(),
                                       reload=AsyncMock(), select_tab=AsyncMock())

    async def type_token(self, text=None):
        return await execute_action(self.session, {'type': 'type', 'text': text or self.token}, self.privacy)

    async def test_contact_token_local_only_and_input_immutable(self):
        action = {'type': 'type', 'text': self.token}
        original = copy.deepcopy(action)
        result = await execute_action(self.session, action, self.privacy)
        self.assertEqual(action, original)
        self.assertEqual(result['resolved'], 1)
        self.assertNotIn('private@example.net', repr(result))
        self.assertEqual(self.handle.evaluate.call_args.args[1]['text'], 'private@example.net')
        self.page.keyboard.insert_text.assert_not_awaited()

    async def test_unsafe_destinations_never_resolve(self):
        changes = [dict(type='search'), dict(type='url'), dict(type='password'),
                   dict(name='q'), dict(role='searchbox'), dict(label='Search email'),
                   dict(formMethod='get'), dict(formOrigin='https://other.org'),
                   dict(origin='https://other.org'), dict(editable=False), dict(focused=False), dict(visible=False),
                   dict(type='text', autocomplete=''), dict(autocomplete='tel')]
        for change in changes:
            with self.subTest(change=change):
                self.handle.evaluate.side_effect = [self.field | change, True]
                resolver = Mock(wraps=self.privacy.resolve)
                privacy = SimpleNamespace(TOKEN=self.privacy.TOKEN, resolve=resolver)
                with self.assertRaises(PrivacyError):
                    await execute_action(self.session, {'type': 'type', 'text': self.token}, privacy)
                resolver.assert_not_called()

    async def test_secret_and_unknown_tokens_fail(self):
        for text in ('[SECRET_1]', '[EMAIL_999]', '[ALIEN_1]'):
            with self.subTest(text=text):
                self.handle.evaluate.side_effect = [self.field, True]
                with self.assertRaises(PrivacyError):
                    await self.type_token(text)

    async def test_origin_changed_before_resolution(self):
        self.page.url = 'https://other.org/'
        with self.assertRaisesRegex(PrivacyError, 'changed'):
            await self.type_token()

    async def test_focus_changed_at_insertion(self):
        self.handle.evaluate.side_effect = [self.field, False]
        with self.assertRaisesRegex(PrivacyError, 'changed'):
            await self.type_token()

    async def test_raw_driver_error_is_sanitized(self):
        self.handle.evaluate.side_effect = [self.field, RuntimeError('private@example.net')]
        with self.assertRaises(PrivacyError) as caught:
            await self.type_token()
        self.assertNotIn('private@example.net', str(caught.exception))

    async def test_private_urls_blocked_and_navigation_cannot_authorize(self):
        for url in ('https://example.org/?q=[EMAIL_1]', 'https://example.org/?q=private@example.net'):
            with self.assertRaises(PrivacyError):
                await execute_action(self.session, {'type': 'navigate', 'url': url}, self.privacy)
        self.session.navigate.assert_not_awaited()
        await execute_action(self.session, {'type': 'navigate', 'url': 'https://second.org'}, self.privacy)
        self.session.navigate.assert_awaited_once_with('https://second.org', authorize=False)

    async def test_chrome_clipboard_console_shortcuts_blocked(self):
        for keys in (['CTRL', 'L'], ['ALT', 'D'], ['F6'], ['F12'], ['CTRL', 'C'],
                     ['CTRL', 'V'], ['CTRL', 'SHIFT', 'I'], ['Meta', 'L']):
            with self.subTest(keys=keys), self.assertRaises(PrivacyError):
                await execute_action(self.session, {'type': 'keypress', 'keys': keys}, self.privacy)
        self.page.keyboard.press.assert_not_awaited()
        await execute_action(self.session, {'type': 'keypress', 'keys': ['CTRL', 'A']}, self.privacy)
        self.page.keyboard.press.assert_awaited_once_with('Control+A')

    async def test_plain_input_summary_contains_no_text(self):
        result = await execute_action(self.session, {'type': 'type', 'text': 'hello'}, self.privacy)
        self.page.keyboard.insert_text.assert_awaited_once_with('hello')
        self.assertNotIn('hello', repr(result))

    async def test_cancellation_propagates_before_resolution(self):
        self.session.check_cancelled.side_effect = [None, None, InterruptedError('Stopped')]
        with self.assertRaises(InterruptedError):
            await self.type_token()
        self.assertEqual(self.handle.evaluate.await_count, 1)

    async def test_non_web_context_blocks_input(self):
        self.session.validate_url.side_effect = PrivacyError('Navigation requires an ordinary HTTPS URL')
        with self.assertRaises(PrivacyError):
            await self.type_token()
        self.page.evaluate_handle.assert_not_awaited()

    async def test_stop_during_page_scan_blocks_click(self):
        self.session.check_cancelled.side_effect = [None, InterruptedError('Stopped')]
        with self.assertRaises(InterruptedError):
            await execute_action(self.session, {'type': 'click', 'x': 20, 'y': 20}, self.privacy)
        self.page.mouse.click.assert_not_awaited()


@unittest.skipUnless(os.environ.get('PLVA_RUN_BROWSER_TESTS') == '1', 'Explicit isolated Edge integration opt-in')
class BrowserActionEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_edge_token_input_and_negative_search(self):
        from plva.browser import BrowserSession
        with tempfile.TemporaryDirectory(prefix='plva-action-test-') as profile:
            browser = BrowserSession(profile_dir=profile, headless=False)
            try:
                await browser.start()
                await browser.context.route('https://plva-action-test.example/**',
                    lambda route: route.fulfill(content_type='text/html', body='''
                    <input id="contact" type="email" autocomplete="email">
                    <input id="person" autocomplete="name">
                    <input id="search" type="search">
                    <script>window.inputEvents = 0;
                    document.addEventListener('input', () => window.inputEvents++);</script>'''))
                await browser.open('https://plva-action-test.example/')
                page = await browser.active_page()
                privacy = PrivacySession()
                email = privacy._register('EMAIL', 'synthetic@example.net')
                name = privacy._register('NAME', 'Synthetic Person')
                for selector, token, expected in [('#contact', email, 'synthetic@example.net'),
                                                   ('#person', name, 'Synthetic Person')]:
                    await page.locator(selector).focus()
                    result = await browser.execute({'type': 'type', 'text': token}, privacy)
                    self.assertEqual(result['resolved'], 1)
                    self.assertEqual(await page.locator(selector).input_value(), expected)
                self.assertEqual(await page.evaluate('window.inputEvents'), 2)
                await page.locator('#search').focus()
                with self.assertRaises(PrivacyError):
                    await browser.execute({'type': 'type', 'text': email}, privacy)
                self.assertEqual(await page.locator('#search').input_value(), '')
            finally:
                await browser.close()


if __name__ == '__main__':
    unittest.main()
