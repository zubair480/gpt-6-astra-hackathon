"""Outbound, authenticated connector for the Cloudflare PLVA interface.

Only allowlisted browser commands are accepted. Raw frames, the token vault,
and API configuration never cross this bridge. No inbound tunnel is opened.
"""
import argparse
import asyncio
import copy
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn

READ = {'/api/state', '/api/audit', '/api/export'}
WRITE = {'/api/browser/open', '/api/browser/select', '/api/browser/preview', '/api/browser/close', '/api/run', '/api/stop'}

def scrub_tree(value, scrub):
    if isinstance(value, dict):
        return {key: scrub_tree(child, scrub) for key, child in value.items()
                if key not in {'raw_frame', 'api_key', 'authorization', 'local_known_values', '_values'}}
    if isinstance(value, list):
        return [scrub_tree(child, scrub) for child in value]
    if isinstance(value, str):
        if value.startswith('data:image/png;base64,'):
            return value
        # PNG fields are already protected by the runtime; do not corrupt base64.
        if len(value) > 1000 and value.startswith('iVBORw0KGgo'):
            return value
        return scrub(value)
    return value

def protected_state(server, run_id):
    from .privacy import PrivacySession
    scrub = server.web_runtime.scrub if server.web_runtime else PrivacySession().scrub
    with server.lock:
        source = copy.deepcopy(server.state)
    allowed = {'status','mode','step','message','task','protected_frame','manifest','events','stats','result','error','source','frame_hash','browser','detector'}
    result = {key:value for key,value in source.items() if key in allowed}
    result['events'] = result.get('events', [])[-80:]
    for tab in result.get('browser', {}).get('tabs', []):
        try:
            url = urlsplit(tab.get('url', ''))
            tab['url'] = f'{url.scheme}://{url.netloc}' if url.scheme in {'http','https'} else ''
        except ValueError:
            tab['url'] = ''
    result = scrub_tree(result, scrub)
    result.update(can_run_astra=bool(server.api_key), run_id=run_id)
    return result

async def execute(command, client, server, active_run):
    method, path = command.get('method'), command.get('path')
    if not ((method == 'GET' and path in READ) or (method == 'POST' and path in WRITE)):
        return 403, {'error':'Command is outside this connector’s scope'}
    body = command.get('body') or {}
    if path == '/api/run':
        if body.get('mode') != 'astra' or body.get('source') != 'web' or not isinstance(body.get('task'),str) or not body['task'].strip():
            return 400, {'error':'Only an explicit Astra browser task can run'}
    if path == '/api/state':
        return 200, protected_state(server, active_run[0])
    if path.startswith('/api/browser/') and server.state.get('status') != 'running':
        server.stop.clear()
    response = await client.request(method, path, json=body if method == 'POST' else None)
    try:
        result = response.json()
    except ValueError:
        return 502, {'error':'Unexpected local runtime response'}
    if path == '/api/run' and response.is_success:
        active_run[0] = str(time.time_ns())
    from .privacy import PrivacySession
    scrub = server.web_runtime.scrub if server.web_runtime else PrivacySession().scrub
    return response.status_code, scrub_tree(result, scrub)

async def bridge_loop(site, key, server):
    active_run = ['']
    jobs=set()
    online=False
    async with httpx.AsyncClient(base_url=site,headers={'Authorization':'Bearer '+key},timeout=10) as cloud:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='http://plva-local',timeout=120) as client:
            async def reply(command):
                try:
                    status,body=await execute(command,client,server,active_run)
                except Exception:
                    status,body=502,{'error':'The local operation failed. Inspect the computer’s runtime status.'}
                result={'id':command['id'],'status':status,'body':body}
                for attempt in range(3):
                    try:
                        response=await cloud.post('/bridge/reply',json=result)
                        response.raise_for_status()
                        return
                    except httpx.HTTPError:
                        await asyncio.sleep(attempt+1)
            try:
                while True:
                    try:
                        response=await cloud.post('/bridge/poll',json={})
                        response.raise_for_status()
                        if not online:
                            print('PLVA computer connected to the private Cloudflare workspace.',flush=True)
                            online=True
                        for command in response.json().get('commands',[]):
                            if not isinstance(command,dict) or not isinstance(command.get('id'),str):
                                continue
                            job=asyncio.create_task(reply(command));jobs.add(job);job.add_done_callback(jobs.discard)
                        await asyncio.sleep(1)
                    except httpx.HTTPError:
                        if online:
                            print('Cloud workspace disconnected; reconnecting shortly.',flush=True)
                        online=False
                        server.stop.set()
                        await asyncio.sleep(3)
            finally:
                server.stop.set()
                if jobs:
                    await asyncio.gather(*jobs,return_exceptions=True)

def load_key_file(path):
    if not path or os.environ.get('OPENAI_API_KEY'):
        return
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        name,sep,value=line.partition('=')
        if sep and name.strip()=='OPENAI_API_KEY':
            os.environ['OPENAI_API_KEY']=value.strip().strip('\"\'')
            return

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--site',default='https://plva-app.zubairzafar480.workers.dev')
    parser.add_argument('--secrets',default=str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PLVA'/'CloudWorkspace'/'secrets.json'))
    parser.add_argument('--key-file')
    args=parser.parse_args()
    if urlsplit(args.site).scheme!='https' or urlsplit(args.site).hostname!='plva-app.zubairzafar480.workers.dev':
        raise SystemExit('The connector only accepts the configured PLVA workspace origin')
    secrets=json.loads(Path(args.secrets).read_text())
    load_key_file(args.key_file)
    from . import server
    async def run():
        local=uvicorn.Server(uvicorn.Config(server.app,host='127.0.0.1',port=18080,log_level='warning',access_log=False))
        print('Local PLVA settings: http://127.0.0.1:18080. Keep this connector running to use the Cloudflare app.',flush=True)
        await asyncio.gather(local.serve(),bridge_loop(args.site,secrets['BRIDGE_KEY'],server))
    asyncio.run(run())

if __name__=='__main__':
    main()
