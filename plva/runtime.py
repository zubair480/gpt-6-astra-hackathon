"""A small Windows browser loop. All cloud observations pass through protect()."""
import asyncio
import base64
import json
import re
import time
from urllib.parse import urlparse

import httpx
from playwright.async_api import async_playwright

from .privacy import PrivacySession, PrivacyError

BASE = 'http://127.0.0.1:18080'
MODEL = 'gpt-6-astra'
INSTRUCTIONS = '''You operate a browser through PLVA. Screenshots contain private-value
tokens. Copy the exact tokens, including brackets, into the corresponding form fields.
The local runtime substitutes values. Never guess or request underlying private values.
SECRET tokens cannot be used. Complete the user's replacement shipment using the support
page and replacement form. Use ordinary click/type computer actions. Fill all required
fields, including order and item. Stay within the sample application. Stop after success.'''

def run_worker(mode, task, key):
    # Own a Proactor loop on Windows, independent of Uvicorn's event-loop policy.
    loop = asyncio.ProactorEventLoop() if hasattr(asyncio, 'ProactorEventLoop') else asyncio.new_event_loop()
    try:
        loop.run_until_complete(Runner(mode, task, key).run())
    finally:
        loop.close()

class Runner:
    def __init__(self, mode, task, key):
        from . import server
        self.s = server
        self.mode, self.task, self.key = mode, task, key
        self.privacy = PrivacySession()

    def event(self, kind, message):
        with self.s.lock:
            self.s.state['message'] = self.privacy.scrub(message)
            self.s.state['events'].append(dict(time=time.strftime('%H:%M:%S'), kind=kind, message=self.privacy.scrub(message)))

    def check(self):
        if self.s.stop.is_set():
            raise InterruptedError('Stopped by operator')

    async def observe(self):
        self.check()
        findings = await self.page.locator('[data-private]').evaluate_all('''els => els.map(el => {
            const r = el.getBoundingClientRect();
            return {kind:el.dataset.private, label:el.dataset.label || el.dataset.private,
              value:el.value === undefined ? el.textContent.trim() : el.value,
              x:Math.max(0,r.x), y:Math.max(0,r.y),
              width:Math.min(innerWidth,r.right)-Math.max(0,r.x),
              height:Math.min(innerHeight,r.bottom)-Math.max(0,r.y)};
        }).filter(f => f.value && f.width>0 && f.height>0)''')
        raw = await self.page.screenshot(animations='disabled')
        protected = self.privacy.protect(raw, findings)
        encoded = base64.b64encode(protected['png']).decode()
        with self.s.lock:
            st = self.s.state
            st['step'] += 1
            st['raw_frame'] = base64.b64encode(raw).decode()
            st['protected_frame'] = encoded
            st['manifest'] = protected['manifest']
            st['stats']['frames'] += 1
            st['stats']['masks'] += protected['count']
        self.event('protected', f"Frame protected locally: {protected['count']} private fields")
        return encoded, protected['manifest']

    async def action(self, action):
        self.check()
        parsed = urlparse(self.page.url)
        if parsed.netloc != '127.0.0.1:18080' or not parsed.path.startswith('/demo/'):
            raise PrivacyError('Action outside the sample application')
        kind = action['type']
        if kind in ('click', 'double_click'):
            await self.page.mouse.click(action['x'], action['y'], button=action.get('button', 'left'), click_count=2 if kind == 'double_click' else 1)
        elif kind == 'type':
            text = action['text']
            tokens = self.privacy.TOKEN.findall(text)
            if tokens:
                field = await self.page.evaluate('document.activeElement?.dataset.private || ""')
                if not field or any(not t.startswith('[' + field + '_') for t in tokens):
                    raise PrivacyError('Token does not match the destination field')
                text = self.privacy.resolve(text)
                with self.s.lock:
                    self.s.state['stats']['resolved'] += len(tokens)
            await self.page.keyboard.insert_text(text)
        elif kind == 'keypress':
            mapping = {'CTRL':'Control', 'CMD':'Meta', 'ENTER':'Enter', 'TAB':'Tab', 'BACKSPACE':'Backspace', 'ESC':'Escape', 'SPACE':'Space', 'ARROWDOWN':'ArrowDown', 'ARROWUP':'ArrowUp'}
            await self.page.keyboard.press('+'.join(mapping.get(k.upper(), k) for k in action['keys']))
        elif kind == 'scroll':
            await self.page.mouse.move(action.get('x', 600), action.get('y', 400))
            await self.page.mouse.wheel(action.get('scroll_x', 0), action.get('scroll_y', 0))
        elif kind == 'move':
            await self.page.mouse.move(action['x'], action['y'])
        elif kind in ('wait', 'screenshot'):
            await asyncio.sleep(.3)
        else:
            raise PrivacyError('Unsupported computer action: ' + kind)
        self.event('action', 'Executed ' + self.privacy.scrub(json.dumps(action)))
        await asyncio.sleep(.2)

    def record(self, body, frame, manifest):
        # Capture the actual sanitized JSON body, never authorization headers.
        with self.s.lock:
            self.s.requests.append(dict(step=self.s.state['step'], mode=self.mode,
                text=self.privacy.scrub(self.task), manifest=manifest, image_base64=frame,
                payload=body, transmitted=self.mode == 'astra'))

    async def rehearsal(self):
        frame, manifest = await self.observe()
        self.record({'rehearsal':True, 'note':'No cloud request made'}, frame, manifest)
        tokens = {m['kind']:m['token'] for m in manifest}
        await self.click_locator(self.page.locator('a[href="/demo/shipping"]'))
        for field, value in [('NAME',tokens['NAME']), ('EMAIL',tokens['EMAIL']), ('ADDRESS',tokens['ADDRESS']), ('PHONE',tokens['PHONE'])]:
            await self.click_locator(self.page.locator(f'input[data-private="{field}"]'))
            await self.action({'type':'type','text':value})
            frame, manifest = await self.observe()
            self.record({'rehearsal':True,'action':{'type':'type','text':value}},frame,manifest)
            await asyncio.sleep(.4)
        for name, value in [('order','ORD-2048'), ('item','Trail Mug')]:
            loc = self.page.locator(f'input[name="{name}"]')
            if await loc.count():
                await self.click_locator(loc)
                await self.action({'type':'keypress','keys':['CTRL','A']})
                await self.action({'type':'type','text':value})
        await self.click_locator(self.page.get_by_role('button', name='Prepare replacement', exact=True))
        await asyncio.sleep(.5)
        frame, manifest = await self.observe()
        self.record({'rehearsal':True,'note':'Protected result'}, frame, manifest)

    async def click_locator(self, locator):
        box = await locator.bounding_box()
        await self.action({'type':'click', 'x':box['x']+box['width']/2, 'y':box['y']+box['height']/2})

    async def astra(self):
        frame, manifest = await self.observe()
        body = dict(model=MODEL, tools=[{'type':'computer'}], instructions=INSTRUCTIONS,
            input=[{'role':'user','content':[{'type':'input_text','text':self.privacy.scrub(self.task)+'\nAvailable tokens: '+json.dumps(manifest)},
                    {'type':'input_image','image_url':'data:image/png;base64,'+frame,'detail':'original'}]}])
        async with httpx.AsyncClient(timeout=90) as client:
            for _ in range(35):
                self.check()
                self.record(body,frame,manifest)
                self.event('model', 'Sending protected observation to Astra')
                with self.s.lock:
                    self.s.state['stats']['model_calls'] += 1
                response = await client.post('https://api.openai.com/v1/responses',
                    headers={'Authorization':'Bearer '+self.key}, json=body)
                self.check()
                if response.status_code != 200:
                    raise RuntimeError(f'Astra API returned HTTP {response.status_code}: '+self.privacy.scrub(response.text[:500]))
                data = response.json()
                calls = [o for o in data.get('output',[]) if o.get('type')=='computer_call']
                if not calls:
                    return
                outputs = []
                for call in calls:
                    if call.get('pending_safety_checks'):
                        raise RuntimeError('Astra requested confirmation; this demo run has paused')
                    for action in call.get('actions', [call['action']] if 'action' in call else []):
                        await self.action(action)
                    frame, manifest = await self.observe()
                    outputs.append({'type':'computer_call_output','call_id':call['call_id'],
                        'output':{'type':'computer_screenshot','image_url':'data:image/png;base64,'+frame,'detail':'original'}})
                if self.s.receipt:
                    return
                body = dict(model=MODEL, tools=[{'type':'computer'}], instructions=INSTRUCTIONS,
                    previous_response_id=data['id'], input=outputs)
            raise RuntimeError('Demo reached its 35-turn limit')

    async def run(self):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='msedge', headless=True)
                try:
                    self.page = await browser.new_page(viewport={'width':1200,'height':900}, device_scale_factor=1)
                    await self.page.goto(BASE+'/demo/support')
                    self.event('started', 'Browser ready — '+ ('live Astra' if self.mode=='astra' else 'rehearsal, no model calls'))
                    await (self.astra() if self.mode=='astra' else self.rehearsal())
                    self.check()
                    receipt = self.s.receipt
                    expected = ['Mia Chen','mia.chen@example.test','184 Cedar Lane, Portland, OR 97205','+1 (503) 555-0148','ORD-2048','Trail Mug']
                    if not receipt or not all(v in receipt.values() for v in expected):
                        raise RuntimeError('Replacement form has not submitted the expected values')
                    with self.s.lock:
                        self.s.state.update(status='completed', result={'reference':'REP-2048','verified':True,'message':'All six submitted fields match the source.'})
                    self.event('completed','Replacement prepared; local receiver verified the real values')
                finally:
                    await browser.close()
        except InterruptedError:
            with self.s.lock:
                self.s.state['status']='stopped'
            self.event('stopped','Stopped by operator')
        except Exception as exc:
            with self.s.lock:
                self.s.state.update(status='error',error=self.privacy.scrub(str(exc)))
            self.event('error',str(exc))
