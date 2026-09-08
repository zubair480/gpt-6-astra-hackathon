import asyncio
import copy
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title='PLVA demo')
lock = threading.RLock()
stop = threading.Event()
def load_api_key():
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY']
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            name, separator, value = line.partition('=')
            if separator and name.strip() == 'OPENAI_API_KEY':
                return value.strip().strip('\"\'')
    return ''

api_key = load_api_key()
state = {}
requests = []
receipt = None
web_runtime = None

def reset(mode='rehearsal', task=''):
    global receipt
    with lock:
        state.clear()
        state.update(status='idle', mode=mode, step=0, message='Ready', task=task,
                     raw_frame=None, protected_frame=None, manifest=[], events=[],
                     stats=dict(frames=0, masks=0, resolved=0, model_calls=0), result=None, error=None)
        state.update(source='fixture', frame_hash=None,
                     browser={'status':'closed','tabs':[],'active_tab_id':None},
                     detector={'status':'idle','name':'Local screenshot OCR','latency_ms':None,'error':None})
        requests.clear()
        receipt = None

reset()
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')

@app.get('/demo/{page}')
def demo(page: str):
    if page not in ('support', 'shipping'):
        raise HTTPException(404)
    return FileResponse(ROOT / f'static/{page}.html')

@app.get('/api/state')
def get_state():
    with lock:
        return dict(copy.deepcopy(state), can_run_astra=bool(api_key))

@app.get('/api/audit')
def audit():
    with lock:
        return {'requests': copy.deepcopy(requests)}

@app.get('/api/export')
def export():
    with lock:
        bundle = {'schema':'plva.demo.evidence.v1', 'mode':state['mode'],
                  'source':state.get('source','fixture'),
                  'status':state['status'], 'requests':copy.deepcopy(requests),
                  'events':copy.deepcopy(state['events'])}
    return JSONResponse(bundle, headers={'Content-Disposition':'attachment; filename="plva-evidence.json"'})

class Config(BaseModel):
    api_key: str

@app.post('/api/config')
def config(body: Config):
    global api_key
    api_key = body.api_key.strip()
    return {'can_run_astra': bool(api_key)}

class Run(BaseModel):
    mode: str = 'rehearsal'
    source: str = 'fixture'
    task: str = 'Prepare a replacement shipment for order ORD-2048 using the customer details on the support page.'

@app.post('/api/run')
def run(body: Run):
    if body.mode not in ('astra', 'rehearsal'):
        raise HTTPException(400, 'Unknown mode')
    if body.source not in ('web','fixture'):
        raise HTTPException(400, 'Unknown source')
    if body.source == 'web' and body.mode != 'astra':
        raise HTTPException(400, 'Rehearsal is only available for the prepared fixture')
    with lock:
        if state['status'] == 'running':
            raise HTTPException(409, 'A run is already active')
        if body.mode == 'astra' and not api_key:
            raise HTTPException(400, 'Enter your Astra API key locally first')
        browser_state = copy.deepcopy(state.get('browser'))
        if body.source == 'web' and (web_runtime is None or not browser_state.get('active_tab_id')):
            raise HTTPException(400, 'Open a website and preview it first')
        reset(body.mode, body.task)
        stop.clear()
        state['status'] = 'running'
        state['source'] = body.source
        if body.source == 'web':
            state['browser'] = browser_state
            web_runtime.submit('run',body.task,api_key)
            return {'started':True}
        from .runtime import run_worker
        threading.Thread(target=run_worker, args=(body.mode, body.task, api_key), daemon=True).start()
    return {'started': True}

def managed_browser():
    global web_runtime
    with lock:
        if state['status'] == 'running':
            raise HTTPException(409,'Pause Astra before manually changing the managed browser')
        if web_runtime is None:
            from .web_runtime import WebRuntime
            web_runtime = WebRuntime()
    return web_runtime

def browser_command(operation, *args):
    runtime = managed_browser()
    try:
        result = runtime.submit(operation,*args).result(timeout=120)
        return result
    except Exception as exc:
        raise HTTPException(400,runtime.scrub(str(exc))) from None

class OpenURL(BaseModel):
    url: str

class SelectTab(BaseModel):
    tab_id: str

@app.post('/api/browser/open')
def browser_open(body: OpenURL):
    return browser_command('open',body.url)

@app.post('/api/browser/select')
def browser_select(body: SelectTab):
    return browser_command('select',body.tab_id)

@app.post('/api/browser/preview')
def browser_preview():
    return browser_command('preview')

@app.post('/api/browser/close')
def browser_close():
    return browser_command('close')

@app.post('/api/stop')
def stop_run():
    stop.set()
    return {'stopping': True}

@app.post('/api/receipt')
def receive(body: dict):
    global receipt
    with lock:
        receipt = body
    return {'ok': True, 'reference': 'REP-2048'}
