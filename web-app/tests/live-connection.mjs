import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {homedir} from 'node:os';
const base='https://plva-app.zubairzafar480.workers.dev';
const secrets=JSON.parse(await readFile(join(process.env.LOCALAPPDATA||homedir(),'PLVA','CloudWorkspace','secrets.json'),'utf8'));
const login=await fetch(base+'/auth/session',{method:'POST',headers:{origin:base,'content-type':'application/json'},body:JSON.stringify({key:secrets.APP_ACCESS_KEY})});
assert.equal(login.status,200);
const headers={cookie:login.headers.get('set-cookie').split(';')[0],origin:base,'content-type':'application/json'};
async function api(path,body){const response=await fetch(base+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});const result=await response.json();assert.equal(response.status,200,`${path}: ${result.error||result.detail||''}`);return result;}
assert.equal((await api('/api/connection')).connected,true);
await api('/api/browser/open',{url:'https://example.com'});
let state=await api('/api/state');
assert.equal(state.detector.status,'ready');
assert.ok(state.protected_frame.startsWith('iVBORw0KGgo'));
assert.ok(!('raw_frame' in state));assert.ok(!('api_key' in state));
assert.ok(state.browser.tabs.length>0);
console.log('Real browser connection verified: example.com opened in local Edge; protected screenshot returned through Cloudflare; raw frame and API key absent.');
if(process.argv.includes('--run-astra')){
  assert.equal(state.can_run_astra,true,'Astra key must be configured locally');
  await api('/api/run',{mode:'astra',source:'web',task:'Read the current example.com page and report its main heading in one sentence. Do not navigate, click, type, purchase, or submit anything.'});
  const deadline=Date.now()+120000;
  while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,2000));state=await api('/api/state');if(state.status!=='running')break;}
  assert.equal(state.status,'completed',state.error||state.message);
  const evidence=await api('/api/audit');
  const response=evidence.requests.find(item=>item.response_id&&item.transmitted===true);
  assert.ok(response,'A real provider response must be recorded');
  assert.ok(state.stats.model_calls>0);
  console.log(JSON.stringify({verified:'Actual Astra task completed through the deployed application',result:state.result?.message,modelCalls:state.stats.model_calls,returnedModel:response.response_model,responseId:response.response_id},null,2));
}
