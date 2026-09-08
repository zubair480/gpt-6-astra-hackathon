"""Opt-in real-site pixel proof with synthetic values; never submits a form.

DOM selectors/values are verifier-only setup/oracles. Detector receives PNG only.
No markup, routing, styles, annotations or detector hints are injected.
"""
import asyncio
import hashlib
import json
import os
import secrets
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from plva.privacy import PrivacySession, PrivacyError
from tests.browser_e2e.pixel_oracle import (
    assert_entered_pixels_masked, assert_same_visible_field,
    native_visibility_diagnostics, assert_moved_field_pixels_masked,
)


def public_location(url):
    parsed = urlsplit(url)
    return parsed.scheme + '://' + parsed.netloc + parsed.path


@unittest.skipUnless(os.environ.get('PLVA_RUN_LIVE_PRIVACY') == '1',
                     'Explicit isolated real-site privacy opt-in required')
class RealSitePrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.oracles = []
        self.addCleanup(self.retain_failure_artifacts)
        from plva.browser import BrowserSession
        from plva.detection import ScreenshotDetector
        self.profile = tempfile.TemporaryDirectory(prefix='plva-pixel-live-')
        self.addCleanup(self.profile.cleanup)
        self.browser = BrowserSession(profile_dir=self.profile.name, headless=True)
        self.addAsyncCleanup(self.browser.close)
        await self.browser.start()
        self.detector = ScreenshotDetector()
        self.privacy = PrivacySession()

    def retain_failure_artifacts(self):
        result = self._outcome.result
        failed = any(test is self for test, _ in result.failures + result.errors)
        if not failed or not self.oracles:
            return
        directory = Path(tempfile.mkdtemp(prefix='plva-local-failed-oracle-'))
        for index, oracle in enumerate(self.oracles):
            metadata = {}
            for key, value in oracle.items():
                if key.endswith('_png'):
                    (directory / f'{index}-{key}.png').write_bytes(value)
                else:
                    metadata[key] = value
            (directory / f'{index}-oracle.json').write_text(
                json.dumps(metadata, indent=2), encoding='utf-8')
        print(json.dumps({'local_failure_artifact_directory': str(directory)}), flush=True)

    async def visibility(self, field):
        # Detached canvas measures local truth only; no document mutation and no
        # return value is passed to ScreenshotDetector or a cloud provider.
        metrics = await field.evaluate('''el => {
            const s = getComputedStyle(el), c = document.createElement('canvas');
            const ctx = c.getContext('2d');
            ctx.font = s.font || `${s.fontSize} ${s.fontFamily}`;
            const letter = parseFloat(s.letterSpacing) || 0;
            const word = parseFloat(s.wordSpacing) || 0;
            const lines = el.value.split('\\n');
            const widths = lines.map(t => ctx.measureText(t).width +
                Math.max(0, t.length - 1) * letter + (t.match(/ /g) || []).length * word);
            const glyphs = lines.map(t => ctx.measureText(t || 'M'));
            const glyphHeight = Math.max(...glyphs.map(m =>
                m.actualBoundingBoxAscent + m.actualBoundingBoxDescent));
            const lineHeight = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.2;
            return {content_width: el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight),
                content_height: el.clientHeight - parseFloat(s.paddingTop) - parseFloat(s.paddingBottom),
                text_width: Math.max(...widths), text_height: glyphHeight + (lines.length - 1) * lineHeight,
                scroll_left: el.scrollLeft, scroll_top: el.scrollTop,
                client_width: el.clientWidth, scroll_width: el.scrollWidth,
                client_height: el.clientHeight, scroll_height: el.scrollHeight,
                viewport: [innerWidth, innerHeight],
                wrapping: s.whiteSpace, font: s.font};
        }''')
        return metrics, native_visibility_diagnostics(metrics)

    def verify_oracle(self, oracle):
        # Compute pixel evidence independently, even when exact OCR later fails.
        failures = []
        try:
            oracle['pixel_diagnostics'] = assert_entered_pixels_masked(
                oracle['empty_png'], oracle['filled_png'], oracle['protected_png'],
                oracle['masks'], oracle['box'], oracle['metrics']['viewport'], oracle['kind'],
                stable_empty_png=oracle['stable_empty_png'])
        except AssertionError as error:
            oracle['pixel_error'] = str(error)
            failures.append(str(error))
        if not oracle['visibility']['complete_text_fits']:
            failures.append('Complete value does not fit native field geometry')
        if not any(r['kind'] == oracle['kind'] and r['value'] == oracle['value']
                   for r in oracle['findings']):
            failures.append('Exact synthetic value was not recognized from PNG')
        self.assertFalse(failures, '; '.join(failures))

    async def protected_field(self, field, kind, value):
        await field.fill('')
        await field.press('Tab')
        before = await self.browser.capture()
        stable_before = await self.browser.capture()
        box = await field.bounding_box()  # Verifier pixel oracle only.
        await field.fill(value)
        await field.press('Tab')
        after = await self.browser.capture()
        metrics, visibility = await self.visibility(field)
        started = time.perf_counter()
        findings = await asyncio.to_thread(self.detector.detect, after['png'])
        result = self.privacy.protect(after['png'], findings)
        elapsed = round((time.perf_counter() - started) * 1000)
        oracle = dict(empty_png=before['png'], stable_empty_png=stable_before['png'],
                      filled_png=after['png'], protected_png=result['png'], box=box,
                      kind=kind, value=value, findings=findings, masks=result['masks'],
                      metrics=metrics, visibility=visibility)
        self.oracles.append(oracle)
        self.verify_oracle(oracle)
        self.assertTrue(value not in json.dumps(result['manifest']), 'Raw value leaked in manifest')
        self.last_protected = result['png']
        self.last_oracle = oracle
        token = next(m['token'] for m in result['manifest'] if m['kind'] == kind
                     and self.privacy.resolve(m['token']) == value)
        print(json.dumps({'origin': self.browser.origin(after['url']), 'kind': kind,
                          'tab_id': after['tab_id'], **oracle['pixel_diagnostics'],
                          'latency_ms': elapsed,
                          'protected_sha256': hashlib.sha256(result['png']).hexdigest()}))
        return token

    async def test_httpbin_contact_pixels_and_local_token_followup(self):
        await self.browser.open('https://httpbin.org/forms/post')
        print(json.dumps({'opened_url': self.browser.page.url,
                          'document_origin': await self.browser.page.evaluate('location.origin'),
                          'authorized_origins': sorted(self.browser.authorized_origins)}), flush=True)
        field = self.browser.page.locator('input[type=email]')
        email = 'q' + secrets.token_hex(3) + '@example.com'
        token = await self.protected_field(field, 'EMAIL', email)
        await field.fill('')
        await field.focus()
        action = {'type': 'type', 'text': token}
        selected = await self.browser.active_page()
        print(json.dumps({'selected_url': public_location(selected.url),
                          'token_gate_origin': await selected.evaluate('location.origin'),
                          'tabs': [{'id': tab['id'], 'url': public_location(tab['url'])}
                                   for tab in await self.browser.tabs()],
                          'authorized_origins': sorted(self.browser.authorized_origins)}), flush=True)
        from plva.browser import actions as browser_actions
        destination = browser_actions._destination
        def diagnostic_destination(metadata, tokens, authorized):
            allowed = ('origin', 'visible', 'focused', 'editable', 'type',
                       'formMethod', 'formOrigin', 'autocomplete', 'search')
            print(json.dumps({'actual_destination': {k: metadata.get(k) for k in allowed},
                              'actual_authorized_origins': sorted(authorized)}), flush=True)
            return destination(metadata, tokens, authorized)
        with patch.object(browser_actions, '_destination', diagnostic_destination):
            result = await self.browser.execute(action, self.privacy)
        self.assertEqual(result.get('resolved'), 1)
        self.assertTrue(await field.input_value() == email, 'Executor inserted wrong value')
        self.assertEqual(action['text'], token)
        # Capture actual executor output before any verifier re-entry.
        await field.press('Tab')
        frame = await self.browser.capture()
        findings = await asyncio.to_thread(self.detector.detect, frame['png'])
        safe = self.privacy.protect(frame['png'], findings)
        metrics, visibility = await self.visibility(field)
        followup = dict(self.last_oracle, filled_png=frame['png'], protected_png=safe['png'],
                        findings=findings, masks=safe['masks'], metrics=metrics,
                        visibility=visibility)
        self.oracles.append(followup)
        self.verify_oracle(followup)
        self.assertGreater(safe['count'], 0)
        assert_same_visible_field(self.last_protected, safe['png'],
                                  followup['box'], metrics['viewport'])
        phone = '202-555-01' + str(secrets.randbelow(100)).zfill(2)
        await self.protected_field(self.browser.page.locator('input[type=tel]'), 'PHONE', phone)
        await field.focus()
        for blocked in ('[EMAIL_99999]', '[SECRET_1]'):
            with self.assertRaises(PrivacyError):
                await self.browser.execute({'type': 'type', 'text': blocked}, self.privacy)
        self.assertTrue(await field.input_value() == email, 'Rejected action changed value')

    async def test_selenium_textarea_email_pixels(self):
        await self.browser.open('https://www.selenium.dev/selenium/web/web-form.html')
        email = 'q' + secrets.token_hex(3) + '@example.com'
        await self.protected_field(self.browser.page.locator('textarea'), 'EMAIL', email)

    async def test_two_origin_scroll_navigation_tab_and_stop(self):
        # Native viewport control makes the ordinary form scrollable; no CSS edits.
        self.browser.viewport = {'width': 1200, 'height': 400}
        await self.browser.page.set_viewport_size(self.browser.viewport)
        await self.browser.open('https://httpbin.org/forms/post')
        first_page = self.browser.page
        first_tab = self.browser.active_tab_id
        field = first_page.locator('input[type=email]')
        await self.protected_field(field, 'EMAIL', 'q' + secrets.token_hex(3) + '@example.com')
        reference = dict(self.last_oracle)
        await self.browser.execute({'type': 'scroll', 'x': 700, 'y': 200,
                                    'scroll_y': 65, 'scroll_x': 0}, self.privacy)
        await first_page.wait_for_function('window.scrollY > 0')

        async def verify_transition(label):
            frame = await self.browser.capture()
            self.assertEqual(frame['tab_id'], first_tab)
            self.assertEqual(self.browser.origin(frame['url']), 'https://httpbin.org')
            findings = await asyncio.to_thread(self.detector.detect, frame['png'])
            protected = self.privacy.protect(frame['png'], findings)
            box = await field.bounding_box()
            pixels = assert_moved_field_pixels_masked(
                reference['empty_png'], reference['filled_png'], frame['png'],
                protected['png'], protected['masks'], reference['box'], box,
                (1200, 400), 'EMAIL', stable_empty_png=reference['stable_empty_png'])
            self.assertTrue(any(f['kind'] == 'EMAIL' and f['value'] == reference['value']
                                for f in findings), 'Transition lost exact email discovery')
            print(json.dumps({'transition': label, 'tab_id': frame['tab_id'],
                              'origin': self.browser.origin(frame['url']), **pixels,
                              'protected_sha256': hashlib.sha256(protected['png']).hexdigest()}), flush=True)

        await verify_transition('actual_scroll')
        await self.browser.open('https://www.selenium.dev/selenium/web/web-form.html', new_tab=True)
        second_tab = self.browser.active_tab_id
        self.assertNotEqual(first_tab, second_tab)
        await self.protected_field(self.browser.page.locator('textarea'), 'EMAIL',
                                   'q' + secrets.token_hex(3) + '@example.com')
        await self.browser.execute({'type': 'navigate', 'url': 'https://example.com/'}, self.privacy)
        navigated = await self.browser.capture()
        self.assertEqual(self.browser.origin(navigated['url']), 'https://example.com')
        self.assertEqual(navigated['tab_id'], second_tab)
        await self.browser.execute({'type': 'select_tab', 'tab_id': first_tab}, self.privacy)
        await verify_transition('return_from_other_origin_tab')
        stop = threading.Event()

        def stop_check():
            if stop.is_set():
                raise InterruptedError('Stopped by test operator')

        self.browser.stop_check = stop_check
        stop.set()
        await field.focus()
        with self.assertRaises(InterruptedError):
            await self.browser.execute({'type': 'type', 'text': 'must-not-insert'}, self.privacy)
        self.assertTrue(await field.input_value() == reference['value'], 'Stop allowed insertion')
        await field.press('Tab')
        await verify_transition('manual_capture_after_stop')


if __name__ == '__main__':
    unittest.main()
