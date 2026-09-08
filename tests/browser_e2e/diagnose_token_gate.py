"""Isolated HTTPBin metadata diagnostic; no OCR, values, provider or form submit."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plva.browser import BrowserSession
from plva.browser import actions


async def main():
    with tempfile.TemporaryDirectory(prefix='plva-gate-diagnostic-') as profile:
        browser = BrowserSession(profile_dir=profile, headless=True)
        try:
            await browser.start()
            await browser.open('https://httpbin.org/forms/post')
            page = await browser.active_page()
            await page.locator('input[type=email]').focus()
            page = await browser.active_page()
            handle = await page.evaluate_handle('document.activeElement')
            try:
                metadata = await handle.evaluate(actions._FIELD)
            finally:
                await handle.dispose()
            allowed = ('origin', 'focused', 'visible', 'editable', 'type',
                       'autocomplete', 'formOrigin', 'formMethod', 'search')
            report = {
                'actions_sha256': hashlib.sha256(Path(actions.__file__).read_bytes()).hexdigest(),
                'selected_url': page.url, 'selected_tab': browser.active_tab_id,
                'location_origin': await page.evaluate('location.origin'),
                'authorized_origins': sorted(browser.authorized_origins),
                'field': {key: metadata.get(key) for key in allowed},
                'field_origin_authorized': metadata.get('origin') in browser.authorized_origins,
                'tabs': [{'id': t['id'], 'url': t['url']} for t in await browser.tabs()],
            }
            try:
                actions._destination(metadata, ['[EMAIL_1]'], browser.authorized_origins)
                report['gate'] = 'allowed'
            except Exception as exc:
                report['gate'] = type(exc).__name__
                report['gate_reason'] = str(exc)
            print(json.dumps(report, indent=2), flush=True)
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
