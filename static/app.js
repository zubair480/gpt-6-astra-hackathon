const $ = id => document.getElementById(id);
let hiddenRaw = true, currentState = null, polling = false, browserBusy = false, actionBusy = false;
let lastPreviewAt = 0, connected = false;
function imgSrc(value) { return value?.startsWith('data:') ? value : `data:image/png;base64,${value}`; }
function setImage(id, value) {
  const element = $(id); element.hidden = !value;
  if (!value) { element.removeAttribute('src'); delete element.dataset.value; }
  else if (element.dataset.value !== value) { element.src = imgSrc(value); element.dataset.value = value; }
}
function activeRun() { return currentState?.status === 'running'; }
function tabsFor(state) { return Array.isArray(state?.browser?.tabs) ? state.browser.tabs : []; }
function updateControls() {
  const active = activeRun(), tabs = tabsFor(currentState), hasTab = tabs.length > 0;
  const detectorFailed = !currentState?.detector?.status || ['error','failed','unavailable','loading','initializing','not_initialized'].includes(currentState?.detector?.status) || !!currentState?.detector?.error;
  $('start').disabled = !connected || currentState?.status === 'error' || active || actionBusy || browserBusy || !hasTab || !currentState?.can_run_astra || detectorFailed || currentState?.source === 'fixture' || !currentState?.protected_frame;
  $('stop').disabled = !connected || !active;
  $('rehearse').disabled = !connected || active || actionBusy || browserBusy;
  for (const id of ['browser-open','browser-url']) $(id).disabled = !connected || active || browserBusy || actionBusy;
  for (const id of ['browser-tab','preview-refresh','browser-close']) $(id).disabled = !connected || active || browserBusy || actionBusy || !hasTab;
}
function render(state) {
  currentState = state;
  const active = state.status === 'running', fixture = state.source === 'fixture' || state.mode === 'rehearsal';
  $('status').textContent = ({idle:'Ready',running:'Working',completed:'Complete',error:'Paused on error',stopped:'Stopped'})[state.status] || state.status || 'Unknown';
  $('status-dot').className = 'status-dot ' + (state.status || '');
  $('message').textContent = state.error || state.message || '';
  $('mode').textContent = fixture ? 'OLD FIXTURE · ' + (state.mode === 'rehearsal' ? 'SCRIPTED / NO MODEL' : 'FIXTURE SOURCE') : active ? 'LIVE ASTRA · MANAGED BROWSER' : 'LOCAL PREVIEW · ASTRA PAUSED';
  $('availability').textContent = state.can_run_astra ? 'Astra is configured. Open a managed website and inspect its protected preview to start.' : 'Astra needs an API key. Local browser previews do not require a model call.';
  const tabs = tabsFor(state), selected = String(state.browser?.active_tab_id ?? '');
  const tabSignature = JSON.stringify([selected, tabs]);
  if ($('browser-tab').dataset.signature !== tabSignature) {
    $('browser-tab').replaceChildren();
    if (!tabs.length) { const option = document.createElement('option'); option.value=''; option.textContent='No managed browser tab'; $('browser-tab').append(option); }
    for (const tab of tabs) { const option=document.createElement('option'); option.value=String(tab.id); option.textContent=tab.title || tab.url || `Tab ${tab.id}`; $('browser-tab').append(option); }
    $('browser-tab').value=selected; $('browser-tab').dataset.signature=tabSignature;
  }
  const tab = tabs.find(item => String(item.id) === selected);
  let origin = 'No active origin'; try { origin = new URL(tab.url).origin; } catch (_) {}
  $('active-origin').textContent=origin;
  $('browser-status').textContent=`Managed browser: ${state.browser?.status || 'unavailable'}`;
  const recovery = state.capture_recovery ?? state.browser?.capture_recovery;
  $('capture-recovery').hidden = recovery !== 'foreground';
  $('capture-recovery').textContent = recovery === 'foreground' ? 'Capture recovered successfully by bringing the managed browser to the foreground.' : '';
  const detector = state.detector || {};
  $('detector-status').textContent=`Detector: ${detector.status || 'unavailable'}${detector.name ? ' · '+detector.name : ''}${Number.isFinite(detector.latency_ms) ? ' · '+Math.round(detector.latency_ms)+' ms' : ''}${detector.error ? ' · '+detector.error : ''}`;
  $('detector-status').classList.toggle('error', !!detector.error || ['error','failed','unavailable'].includes(detector.status));
  setImage('raw', hiddenRaw ? null : state.raw_frame);
  $('raw-empty').hidden = hiddenRaw || !!state.raw_frame; $('raw-hidden').hidden = !hiddenRaw;
  setImage('protected', state.protected_frame); $('protected-empty').hidden = !!state.protected_frame;
  $('frame-label').textContent = state.protected_frame ? `Preview · step ${state.step ?? 0}` : 'No frame yet';
  $('preview-hash').textContent = state.protected_frame && state.frame_hash ? `Frame SHA-256: ${state.frame_hash}` : 'Frame hash unavailable';
  $('protected-caption').textContent = fixture ? 'Old fixture preview · scripted rehearsal is not ordinary website or provider evidence.' : 'Latest local preview · not proof of sending. Inspect submitted frames below for exact request images and provider receipts.';
  if (state.status === 'error' || detector.error || ['error','failed','unavailable'].includes(detector.status)) $('protected-caption').textContent = 'Protection unavailable. Any image shown is the last available preview, not a fresh safe observation. Live Astra is blocked.';
  for (const [id,key] of [['frames','frames'],['masks','masks'],['resolved','resolved'],['calls','model_calls']]) $(id).textContent = state.stats?.[key] ?? 0;
  $('tokens').replaceChildren();
  const tokens = state.manifest || [];
  if (!tokens.length) { const n = document.createElement('div'); n.className='quiet'; n.textContent='No private references detected yet. This does not guarantee the page contains no private data.'; $('tokens').append(n); }
  for (const token of tokens) { const el=document.createElement('span'); el.className='token'; el.textContent=token.token; el.title=token.label || token.kind || ''; $('tokens').append(el); }
  const events = state.events || []; $('events').replaceChildren();
  for (const event of events.slice(-15).reverse()) { const row=document.createElement('div'); row.className='event '+(event.kind || ''); const time=document.createElement('time'); const date=new Date(event.time); time.textContent=Number.isNaN(date.valueOf()) ? String(event.time || '').slice(0,8) : date.toLocaleTimeString([], {hour12:false}); const dot=document.createElement('i'); const text=document.createElement('span'); text.textContent=event.message; row.append(time,dot,text); $('events').append(row); }
  if (!events.length) { const el=document.createElement('div');el.className='quiet';el.textContent='Open a website to begin local preview.';$('events').append(el); }
  $('result').hidden = state.status !== 'completed';
  $('result-title').textContent = fixture ? 'Fixture rehearsal complete' : 'Astra run complete';
  $('result-message').textContent = fixture ? 'Prepared synthetic fixture only. No ordinary website or live provider success is implied.' : (state.result?.message || 'Inspect the activity and provider receipts for the recorded outcome.');
  updateControls();
  window.PLVA_AUDIT?.refresh(state);
}
async function localFetch(path, options={}) {
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),30000);
  try { return await fetch(path,{...options,signal:controller.signal}); }
  catch(error) { if(error.name === 'AbortError') throw new Error('Local request timed out. Refresh state before retrying.'); throw error; }
  finally { clearTimeout(timer); }
}
async function request(path, body) {
  const response=await localFetch(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body || {})});
  let result = {}; try { result=await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Local request failed (${response.status}).`);
  return result;
}
async function poll() {
  if(polling)return; polling=true;
  try { const res=await localFetch('/api/state',{cache:'no-store'}); if(!res.ok)throw new Error('Cannot reach the local runtime.'); const state=await res.json(); connected=true; render(state); }
  catch(e) { connected=false; $('message').textContent=e.message; updateControls(); }
  finally{polling=false;}
}
async function browserAction(path, body, automatic=false) {
  if(browserBusy || actionBusy || activeRun())return;
  browserBusy=true; updateControls();
  try { await request(path,body); lastPreviewAt=Date.now(); if(!automatic)$('browser-message').textContent=path.endsWith('/close') ? 'Managed browser closed.' : 'Local preview refreshed. No model request was made.'; }
  catch(e) { $('browser-message').textContent=e.message; lastPreviewAt=Date.now(); }
  finally { browserBusy=false; await poll(); updateControls(); }
}
async function run(mode) {
  if(actionBusy || browserBusy || activeRun() || (mode === 'astra' && $('start').disabled))return;
  actionBusy=true; updateControls();
  try { await request('/api/run',{mode,source:mode === 'rehearsal' ? 'fixture' : 'web',task:mode === 'rehearsal' ? "Open the damaged-order ticket and prepare a replacement shipment using the customer's details." : $('task').value}); await poll(); }
  catch(e){$('message').textContent=e.message;}
  finally{actionBusy=false;updateControls();}
}
$('browser-form').addEventListener('submit',event=>{event.preventDefault();browserAction('/api/browser/open',{url:$('browser-url').value.trim()});});
$('browser-tab').addEventListener('change',()=>browserAction('/api/browser/select',{tab_id:$('browser-tab').value}));
$('preview-refresh').onclick=()=>browserAction('/api/browser/preview');
$('browser-close').onclick=()=>browserAction('/api/browser/close');
$('start').onclick=()=>run('astra');$('rehearse').onclick=()=>run('rehearsal');
$('stop').onclick=async()=>{ $('stop').disabled=true;try{await request('/api/stop');await poll();}catch(e){$('message').textContent=e.message;}finally{updateControls();} };
$('toggle-raw').onclick=()=>{hiddenRaw=!hiddenRaw;$('toggle-raw').textContent=hiddenRaw?'Show private view':'Hide private view';$('toggle-raw').setAttribute('aria-pressed',String(!hiddenRaw));if(currentState)render(currentState);};
$('config-form').addEventListener('submit',async event=>{event.preventDefault();const key=$('api-key').value.trim();if(!key)return;try{await request('/api/config',{api_key:key});$('api-key').value='';$('config-message').textContent='Key configured for the local runtime.';await poll();}catch(e){$('config-message').textContent=e.message;}});
poll();setInterval(poll,1000);
setInterval(()=>{if(connected && !document.hidden && !activeRun() && currentState?.status !== 'error' && !browserBusy && !actionBusy && tabsFor(currentState).length && Date.now()-lastPreviewAt>10000)browserAction('/api/browser/preview',{},true);},1000);
