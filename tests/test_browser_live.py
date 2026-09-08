"""Opt-in Edge integration checks; never use a personal browser profile.

Run: $env:PLVA_BROWSER_LIVE='1'; python -m unittest discover -s tests -p test_browser_live.py -v
Public navigation performs no sign-in, form submission, or CAPTCHA interaction.
"""
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from plva.browser import BrowserSession
from plva.privacy import PrivacyError, PrivacySession


@unittest.skipUnless(os.environ.get('PLVA_BROWSER_LIVE') == '1', 'Opt-in real Edge test')
class BrowserLiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix='plva-session2-profile-')
        self.browser = BrowserSession(profile_dir=self.profile.name, headless=False)
        await self.browser.start()

    async def asyncTearDown(self):
        await self.browser.close()
        self.profile.cleanup()

    async def test_public_amazon_and_second_site_capture(self):
        evidence = Path(tempfile.mkdtemp(prefix='plva-session2-public-evidence-'))
        rows = []
        for index, url in enumerate(('https://www.amazon.com/', 'https://example.com/')):
            await self.browser.open(url, new_tab=index > 0)
            frame = await self.browser.capture()
            self.assertTrue(frame['url'].startswith(url))
            with Image.open(io.BytesIO(frame['png'])) as image:
                self.assertEqual(image.size, (frame['width'], frame['height']))
                self.assertGreater(image.width, 300)
            (evidence / f'site-{index}.png').write_bytes(frame['png'])
            rows.append({k: frame[k] for k in ('tab_id', 'url', 'title', 'width', 'height')})
            rows[-1]['sha256'] = hashlib.sha256(frame['png']).hexdigest()
        self.assertNotEqual(rows[0]['tab_id'], rows[1]['tab_id'])
        self.assertEqual(len(await self.browser.tabs()), 2)
        await self.browser.select_tab(rows[0]['tab_id'])
        self.assertEqual((await self.browser.capture())['tab_id'], rows[0]['tab_id'])
        await self.browser.execute({'type': 'scroll', 'scroll_y': 250}, PrivacySession())
        self.assertEqual((await self.browser.capture())['tab_id'], rows[0]['tab_id'])
        # Simulate the operator choosing a browser tab outside select_tab().
        # This catches browser-driver focus emulation reporting every tab active.
        second_page = next(p for p in self.browser.context.pages if p.url == rows[1]['url'])
        await second_page.bring_to_front()
        self.assertEqual((await self.browser.capture())['tab_id'], rows[1]['tab_id'])
        await self.browser.select_tab(rows[1]['tab_id'])
        self.assertEqual((await self.browser.capture())['url'], rows[1]['url'])
        (evidence / 'navigation.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        print('\nPUBLIC_NAVIGATION_EVIDENCE=' + str(evidence), flush=True)
        print(json.dumps(rows), flush=True)

    async def test_real_engine_checked_token_and_navigation(self):
        # This synthetic fixture supplements public navigation. It is not an
        # ordinary-site or image-detector acceptance claim. No request leaves Edge.
        html = '''<!doctype html><title>Local token destination fixture</title>
          <form method="post"><input id="email" type="email" autocomplete="email">
          <input id="search" type="search"></form>
          <a target="_blank" href="https://plva-browser-test.invalid/popup">Popup</a>
          <script>window.inputEvents = 0;
          document.addEventListener('input', () => window.inputEvents++);</script>'''
        await self.browser.context.route('https://plva-browser-test.invalid/**',
            lambda route: route.fulfill(status=200, content_type='text/html', body=html))
        await self.browser.open('https://plva-browser-test.invalid/one')
        privacy = PrivacySession()
        frame = await self.browser.capture()
        privacy.protect(frame['png'], [{'kind': 'EMAIL', 'value': 'synthetic@example.test',
            'label': 'Email', 'x': 0, 'y': 0, 'width': 200, 'height': 50}])
        await self.browser.page.locator('#email').focus()
        summary = await self.browser.execute({'type': 'type', 'text': '[EMAIL_1]'}, privacy)
        self.assertEqual(summary['resolved'], 1)
        self.assertNotIn('synthetic@example.test', json.dumps(summary))
        self.assertEqual(await self.browser.page.locator('#email').input_value(), 'synthetic@example.test')
        self.assertEqual(await self.browser.page.evaluate('window.inputEvents'), 1)
        await self.browser.page.locator('#search').focus()
        with self.assertRaises(PrivacyError):
            await self.browser.execute({'type': 'type', 'text': '[EMAIL_1]'}, privacy)
        self.assertEqual(await self.browser.page.locator('#search').input_value(), '')
        await self.browser.execute({'type': 'navigate', 'url': 'https://plva-browser-test.invalid/two'}, privacy)
        await self.browser.execute({'type': 'back'}, privacy)
        self.assertTrue((await self.browser.capture())['url'].endswith('/one'))
        await self.browser.execute({'type': 'forward'}, privacy)
        self.assertTrue((await self.browser.capture())['url'].endswith('/two'))
        await self.browser.execute({'type': 'reload'}, privacy)
        async with self.browser.context.expect_page() as popup_event:
            await self.browser.page.get_by_text('Popup', exact=True).click()
        popup = await popup_event.value
        await popup.wait_for_load_state('domcontentloaded')
        await popup.bring_to_front()
        self.assertTrue((await self.browser.capture())['url'].endswith('/popup'))
        self.assertEqual(len(await self.browser.tabs()), 2)


if __name__ == '__main__':
    unittest.main()
