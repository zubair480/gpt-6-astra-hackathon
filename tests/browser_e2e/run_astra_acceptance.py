"""Explicit live acceptance: real public form, synthetic email, real Astra.

Run only when the coordinator grants the isolated browser/CPU window:
    python -m tests.browser_e2e.run_astra_acceptance
The verifier uses DOM only to set/check a synthetic field, never for detection.
No form is submitted. Protected evidence is saved locally; raw values are not.
"""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import tempfile
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from plva import server
from plva.browser import BrowserSession
from plva.web_runtime import WebRuntime
from .evidence import validate_audit
from .pixel_oracle import assert_entered_pixels_masked, field_pixel_box


async def exercise(runtime, profile):
    runtime.browser = BrowserSession(profile_dir=profile, headless=True,
                                     stop_check=runtime.check)
    try:
        await runtime.ensure()
        await runtime.browser.open('https://httpbin.org/forms/post')
        page = runtime.browser.page
        form_tab_id = runtime.browser.active_tab_id
        field = page.locator('input[type=email]')
        email = 'p' + secrets.token_hex(3) + '@example.com'
        await field.fill('')
        await field.press('Tab')
        empty = await runtime.browser.capture()
        stable_empty = await runtime.browser.capture()
        box = await field.bounding_box()
        await field.fill(email)
        await field.press('Tab')
        await runtime.observe()
        token = next(m['token'] for m in server.state['manifest']
                     if m['kind'] == 'EMAIL' and runtime.privacy.resolve(m['token']) == email)
        before = Image.open(io.BytesIO(empty['png'])).convert('RGB')
        raw = Image.open(io.BytesIO(base64.b64decode(server.state['raw_frame']))).convert('RGB')
        safe = Image.open(io.BytesIO(base64.b64decode(server.state['protected_frame']))).convert('RGB')
        viewport = (runtime.browser.viewport['width'], runtime.browser.viewport['height'])
        pixel_result = assert_entered_pixels_masked(empty['png'],
            base64.b64decode(server.state['raw_frame']),
            base64.b64decode(server.state['protected_frame']),
            runtime.cached_protected['masks'], box, viewport, 'EMAIL',
            stable_empty_png=stable_empty['png'])
        rectangle = field_pixel_box(box, raw.size, viewport)
        glyph_points = [(x-rectangle[0], y-rectangle[1], raw.getpixel((x,y)))
                        for y in range(rectangle[1], rectangle[3])
                        for x in range(rectangle[0], rectangle[2])
                        if raw.getpixel((x,y)) != before.getpixel((x,y))]
        glyphs = pixel_result['changed_pixels_masked']
        print(json.dumps({'stage':'local-pixel-check', 'masked_glyph_pixels':glyphs}), flush=True)
        typed_verified = False
        original_execute = runtime.browser.execute
        original_observe = runtime.observe
        executed_types = []
        post_type_checks = []

        async def checked_observe():
            result = await original_observe()
            # This oracle verifies the post-typing checkpoint before scrolling.
            # Scroll/navigation use their separate moved-field live pixel test;
            # geometry sampled after OCR must not be applied to an earlier
            # frame while a browser scroll is still changing its rendering.
            if (typed_verified and 'scroll' not in executed_types and
                    runtime.browser.origin(page.url) == 'https://httpbin.org'):
                assert server.state['browser']['active_tab_id'] == form_tab_id, 'Pixel oracle is not the captured tab'
                current_box = await field.bounding_box()
                if (current_box and current_box['y'] >= 0 and
                        current_box['y'] + current_box['height'] <= viewport[1]):
                    actual = Image.open(io.BytesIO(base64.b64decode(server.state['raw_frame']))).convert('RGB')
                    protected = Image.open(io.BytesIO(base64.b64decode(server.state['protected_frame']))).convert('RGB')
                    current_rectangle = field_pixel_box(current_box, actual.size, viewport)
                    assert (current_rectangle[2]-current_rectangle[0], current_rectangle[3]-current_rectangle[1]) == (rectangle[2]-rectangle[0], rectangle[3]-rectangle[1]), 'Actual field dimensions changed'
                    coverage = Image.new('1', actual.size)
                    draw = ImageDraw.Draw(coverage)
                    for mask in runtime.cached_protected['masks']:
                        if mask['kind'] == 'EMAIL':
                            x,y,w,h = (mask[k] for k in ('x','y','width','height'))
                            draw.rectangle((x,y,x+w-1,y+h-1), fill=1)
                    # The complete original changed-field glyph set is checked;
                    # no glyph is removed because focus/caret styling changed.
                    for dx,dy,pixel in glyph_points:
                        point = (current_rectangle[0]+dx, current_rectangle[1]+dy)
                        assert actual.getpixel(point) == pixel, 'Actual private glyph differs from original oracle'
                        assert coverage.getpixel(point), 'Post-type private glyph is outside email mask'
                        assert protected.getpixel(point) != pixel, 'Post-type private glyph retained upstream'
                    post_type_checks.append({'frame_hash':server.state['frame_hash'],
                                             'audit_start_index':len(server.requests),
                                             'tab_id':form_tab_id,
                                             'masked_glyph_pixels':len(glyph_points)})
            return result

        async def checked_execute(action, privacy):
            nonlocal typed_verified
            result = await original_execute(action, privacy)
            executed_types.append(action['type'])
            if (result or {}).get('resolved'):
                assert await field.input_value() == email, 'Locally typed email differs from the oracle'
                typed_verified = True
            return result

        runtime.browser.execute = checked_execute
        runtime.observe = checked_observe
        task = ('On this test form, actually re-enter the existing private email: click the Email '
                'input, select all its contents, and type the exact token '+token+' into the SAME '
                'Email input. This retyping action is required even though the value is unchanged. '
                'Do not submit the form. After typing, press Tab and take a screenshot before '
                'scrolling. Then scroll down once and use navigate_browser to open '
                'https://example.com/. Report its visible heading and finish. Do not type tokens '
                'anywhere else or submit anything.')
        server.state.update(status='running', source='web', mode='astra', task=task)
        await runtime.command('run', task, server.load_api_key())
        if server.state['status'] != 'completed':
            output = Path('.plva-evidence')
            output.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            failed_path = output/f'httpbin-astra-token-failed-{stamp}.json'
            failure = {'status':server.state['status'], 'error':runtime.scrub(server.state.get('error')),
                       'requests':server.requests, 'events':server.state['events'],
                       'post_type_pixel_checks':post_type_checks,
                       'executed_action_types':executed_types}
            failure_text = json.dumps(failure, indent=2)
            assert email not in failure_text and server.load_api_key() not in failure_text
            failed_path.write_text(failure_text, encoding='utf-8')
            print(json.dumps({'stage':'failed', 'error':failure['error'],
                              'export':str(failed_path.resolve())}), flush=True)
        assert server.state['status'] == 'completed', 'Live agent run did not complete'
        assert server.state['stats']['resolved'] >= 1, 'Astra did not execute local token typing'
        assert typed_verified, 'Local field equality was not verified'
        assert runtime.browser.origin(runtime.browser.page.url) == 'https://example.com', 'Final origin mismatch'
        audit = server.requests
        result = validate_audit(audit, [email, server.load_api_key()], minimum_frames=2)
        assert 'scroll' in executed_types, 'No successfully executed scroll'
        post_type_sent = []
        for check in post_type_checks:
            for index in range(check['audit_start_index'], len(audit)):
                entry = audit[index]
                if entry['status'] == 'responded' and entry['frame_hash'] == check['frame_hash']:
                    post_type_sent.append(dict(check, request_index=index,
                                               request_id=entry['request_id'],
                                               response_id=entry['response_id']))
                    break
        assert post_type_sent, 'No independently pixel-checked post-type frame was submitted'
        output = Path('.plva-evidence')
        output.mkdir(exist_ok=True)
        bundle = {'schema':'plva.demo.evidence.v1', 'source':'web', 'mode':'astra',
                  'status':server.state['status'], 'requests':audit, 'events':server.state['events'],
                  'verification':dict(result, masked_glyph_pixels=glyphs,
                                      post_type_submitted_pixel_checks=post_type_sent,
                                      executed_action_types=executed_types,
                                      locally_resolved=server.state['stats']['resolved'])}
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        path = output/f'httpbin-astra-token-live-{stamp}.json'
        path.write_text(json.dumps(bundle, indent=2), encoding='utf-8')
        print(json.dumps({'stage':'passed', **bundle['verification'],
                          'export':str(path.resolve()),
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                          'receipts':[r['response_id'] for r in audit]}), flush=True)
    finally:
        await runtime.browser.close()


def main():
    server.reset('astra', '')
    server.stop.clear()
    runtime = WebRuntime()
    try:
        with tempfile.TemporaryDirectory(prefix='plva-live-astra-') as profile:
            future = asyncio.run_coroutine_threadsafe(exercise(runtime, profile), runtime.loop)
            future.result(timeout=600)
    finally:
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        runtime.thread.join(timeout=5)
        runtime.loop.close()


if __name__ == '__main__':
    main()
