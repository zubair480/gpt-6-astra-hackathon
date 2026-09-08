"""Persistent browser loop: local observation first, cloud assistance explicitly started."""
import asyncio
import base64
import hashlib
import json
import threading
import time

from .privacy import PrivacySession


class WebRuntime:
    def __init__(self):
        self.loop = asyncio.ProactorEventLoop() if hasattr(asyncio, 'ProactorEventLoop') else asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.browser = None
        self.detector = None
        self.privacy = PrivacySession()
        self.guard = None
        self.stage = 'idle'
        self.cached_raw_hash = None
        self.cached_protected = None

    @property
    def s(self):
        from . import server
        return server

    def submit(self, operation, *args):
        return asyncio.run_coroutine_threadsafe(self.command(operation, *args), self.loop)

    def event(self, kind, message):
        clean = self.scrub(message)
        with self.s.lock:
            self.s.state['message'] = clean
            self.s.state['events'].append({'time':time.strftime('%H:%M:%S'), 'kind':kind, 'message':clean})

    def scrub(self, text):
        text = self.privacy.scrub(str(text))
        if self.detector and hasattr(self.detector, 'scrub_text'):
            text = self.detector.scrub_text(text)
        return text

    def check(self):
        if self.s.stop.is_set():
            raise InterruptedError('Stopped by operator')

    async def ensure(self):
        if self.browser is None:
            from .browser import BrowserSession
            browser = BrowserSession(stop_check=self.check)
            await browser.start()
            self.browser = browser
        if self.detector is None:
            from .detection import ScreenshotDetector
            with self.s.lock:
                self.s.state['detector'] = {'status':'loading', 'name':'Local screenshot OCR', 'latency_ms':None, 'error':None}
            self.detector = await asyncio.to_thread(ScreenshotDetector)

    async def metadata(self, frame=None):
        tabs = await self.browser.tabs()
        with self.s.lock:
            previous = self.s.state.get('browser', {})
            self.s.state['browser'] = {'status':'open', 'tabs':tabs,
                'active_tab_id':frame.get('tab_id') if frame else previous.get('active_tab_id')}

    async def observe(self):
        self.stage = 'capture'
        frame = await self.browser.capture()
        if frame.get('capture_recovery') == 'foreground':
            self.event('capture','Brought the selected PLVA page forward to recover capture')
        started = time.perf_counter()
        raw_hash = hashlib.sha256(frame['png']).hexdigest()
        if raw_hash == self.cached_raw_hash and self.cached_protected is not None:
            protected = self.cached_protected
        else:
            self.stage = 'detect'
            findings = await asyncio.to_thread(self.detector.detect, frame['png'])
            self.stage = 'protect'
            protected = self.privacy.protect(frame['png'], findings)
            self.cached_raw_hash, self.cached_protected = raw_hash, protected
        elapsed = round((time.perf_counter()-started)*1000)
        encoded = base64.b64encode(protected['png']).decode()
        frame_hash = hashlib.sha256(protected['png']).hexdigest()
        await self.metadata(frame)
        with self.s.lock:
            state = self.s.state
            state.update(raw_frame=base64.b64encode(frame['png']).decode(), protected_frame=encoded,
                         manifest=protected['manifest'], frame_hash=frame_hash, source='web')
            state['step'] += 1
            state['stats']['frames'] += 1
            state['stats']['masks'] += protected['count']
            state['detector'] = {'status':'ready', 'name':'Local screenshot OCR', 'latency_ms':elapsed, 'error':None}
        return encoded, protected['manifest']

    async def command(self, operation, *args):
        if self.guard is None:
            self.guard = asyncio.Lock()
        async with self.guard:
            try:
                if operation == 'close':
                    if self.browser:
                        await self.browser.close()
                    self.browser = self.detector = None
                    self.privacy = PrivacySession()
                    self.cached_raw_hash = self.cached_protected = None
                    with self.s.lock:
                        self.s.state.update(raw_frame=None, protected_frame=None, manifest=[], frame_hash=None,
                            browser={'status':'closed','tabs':[],'active_tab_id':None})
                    return {'closed':True}
                if operation in ('preview','select','run') and self.browser is None:
                    raise RuntimeError('Managed browser is closed; open a website first')
                await self.ensure()
                if operation == 'run':
                    await self.run(*args)
                else:
                    self.s.stop.clear()
                    with self.s.lock:
                        if self.s.state.get('source') != 'web':
                            self.s.reset('astra','')
                        self.s.state.update(source='web',mode='astra',error=None)
                        if operation == 'open' or self.s.state['status'] == 'error':
                            self.s.state['status'] = 'idle'
                    if operation == 'open':
                        await self.browser.open(args[0])
                    elif operation == 'select':
                        await self.browser.select_tab(args[0])
                    await self.observe()
                    self.event('preview', 'Local protected preview ready; no cloud request made')
                return {'ok':True}
            except InterruptedError:
                with self.s.lock:
                    self.s.state['status'] = 'stopped'
                self.event('stopped', 'Stopped by operator')
                return {'stopped':True}
            except Exception as exc:
                message = self.scrub(str(exc))
                with self.s.lock:
                    self.s.state.update(status='error', error=message, protected_frame=None, frame_hash=None)
                    if self.stage in ('detect','protect'):
                        self.s.state['detector'] = {'status':'error','name':'Local screenshot OCR','latency_ms':None,'error':message}
                self.event('error',message)
                if operation != 'run':
                    raise RuntimeError(message) from None
                return {'error':message}

    async def run(self, task, key):
        from .provider import AstraProvider
        self.check()
        provider = AstraProvider(key)
        previous = None
        outputs = None
        for _ in range(35):
            self.check()
            frame, manifest = await self.observe()
            self.check()
            if outputs:
                for output in outputs:
                    if output['type'] == 'computer_call_output':
                        output['output']['image_url'] = 'data:image/png;base64,'+frame
            self.event('model','Sending protected website observation to Astra')
            self.stage = 'model'
            with self.s.lock:
                self.s.state['stats']['model_calls'] += 1
            try:
                self.check()
                data, audit = await provider.respond(task=task, image_base64=frame, manifest=manifest,
                    previous_response_id=previous, call_outputs=outputs, scrub=self.scrub)
            except Exception as exc:
                failure_audit = getattr(exc,'audit',None)
                if failure_audit:
                    with self.s.lock:
                        failure_audit.update(step=self.s.state['step'],mode='astra',image_base64=frame,
                                             manifest=manifest,text=self.scrub(task),source='web',
                                             processing_ms=self.s.state['detector'].get('latency_ms'))
                        self.s.requests.append(failure_audit)
                raise
            with self.s.lock:
                audit.update(step=self.s.state['step'],mode='astra',image_base64=frame,manifest=manifest,
                             transmitted=True,text=self.scrub(task),source='web',
                             processing_ms=self.s.state['detector'].get('latency_ms'))
                self.s.requests.append(audit)
            self.check()
            calls = [item for item in data.get('output',[]) if item.get('type') in ('computer_call','function_call')]
            if not calls:
                answers = [part.get('text','') for item in data.get('output',[]) if item.get('type')=='message'
                           for part in item.get('content',[]) if part.get('type')=='output_text']
                message = self.scrub('\n'.join(answers)) or 'Astra ended its browser task.'
                with self.s.lock:
                    self.s.state.update(status='completed',result={'message':message,'verified':False,
                        'verification':'Agent finished; review the website outcome.'})
                self.event('completed',message)
                return
            outputs = []
            for call in calls:
                self.stage = 'action'
                if call['type'] == 'function_call':
                    if call.get('name') != 'navigate_browser':
                        raise RuntimeError('Unsupported browser function')
                    arguments = json.loads(call.get('arguments','{}'))
                    self.check()
                    await self.browser.execute({'type':'navigate','url':arguments['url']},self.privacy)
                    self.event('action','Navigated to '+self.scrub(arguments['url']))
                    outputs.append({'type':'function_call_output','call_id':call['call_id'],
                                    'output':'Navigation completed. See the protected screenshot.'})
                    continue
                if call.get('pending_safety_checks'):
                    raise RuntimeError('Astra requested confirmation; browser assistance stopped for review')
                for action in call.get('actions', [call['action']] if 'action' in call else []):
                    self.check()
                    result = await self.browser.execute(action,self.privacy)
                    with self.s.lock:
                        self.s.state['stats']['resolved'] += (result or {}).get('resolved',0)
                    self.event('action', 'Executed '+json.dumps(action))
                self.check()
                image, _ = await self.observe()
                outputs.append({'type':'computer_call_output','call_id':call['call_id'],
                    'output':{'type':'computer_screenshot','image_url':'data:image/png;base64,'+image,'detail':'original'}})
            previous = data['id']
        raise RuntimeError('Astra reached the 35-turn demo limit')
