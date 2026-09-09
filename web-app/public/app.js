const $=id=>document.getElementById(id);
let authenticated=false,state=null,connected=false,busy=false,polling=false,attached=null,skills=[],history=[],tabSignature='',lastFrame='';
const text=(id,value)=>{$(id).textContent=value??'';};
function notice(message=''){text('notice',message);}
function showLogin(){authenticated=false;if(!$('login-dialog').open)$('login-dialog').showModal();}
async function api(path,body,method=body===undefined?'GET':'POST'){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),130000);
  try{
    const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:body===undefined?{}:{'content-type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
    let result={};try{result=await response.json();}catch{}
    if(response.status===401){showLogin();throw Error('Unlock your workspace to continue.');}
    if(!response.ok)throw Error(result.error||result.detail||`Request failed (${response.status})`);
    return result;
  }catch(error){if(error.name==='AbortError')throw Error('The operation timed out. Check its status before trying again.');throw error;}finally{clearTimeout(timeout);}
}
function currentTab(){return state?.browser?.tabs?.find(tab=>String(tab.id)===String(state.browser.active_tab_id));}
function controls(){
  const running=state?.status==='running',hasTab=!!state?.browser?.active_tab_id,ready=state?.detector?.status==='ready'&&!state?.detector?.error;
  $('run').disabled=!authenticated||!connected||busy||running||!hasTab||!ready||!state?.can_run_astra||!state?.protected_frame;
  for(const id of ['open','browser-url','tabs'])$(id).disabled=!connected||busy||running;
  for(const id of ['refresh','close-browser'])$(id).disabled=!connected||busy||running||!hasTab;
  $('stop').hidden=!running;$('new-task').disabled=running||busy;
  text('task-hint',running?'Astra is working in the managed browser':!connected?'Start your computer’s PLVA connector':!hasTab?'Open a website to begin':!ready?'Waiting for local protection':!state.can_run_astra?'Configure Astra in local settings':'Protected preview ready · Enter uses a new line');
  text('settings-status',connected?'Your Windows computer is connected.':'Your computer is offline. Start the connector there.');
  text('key-status',state?.can_run_astra?'Astra API key is configured locally.':'No Astra API key is configured locally.');
}
function node(tag,content,className){const el=document.createElement(tag);if(content!==undefined)el.textContent=content;if(className)el.className=className;return el;}
function setView(view){$('task-view').hidden=view!=='tasks';$('skills-view').hidden=view!=='skills';$('nav-tasks').classList.toggle('selected',view==='tasks');$('nav-skills').classList.toggle('selected',view==='skills');text('page-title',view==='skills'?'Skills':'New task');}
function render(next){
  state=next;const hasTask=!!next.task,active=next.status==='running';
  $('welcome').hidden=hasTask;$('task-message').hidden=!hasTask;text('task-message',next.task);
  $('activity').hidden=!hasTask;text('run-heading',({running:'Working on your task',completed:'Your task has finished',stopped:'Task stopped',error:'Your attention is needed'})[next.status]||'Ready for your task');
  const events=next.events||[];$('events').replaceChildren();
  for(const event of events.slice(-7)){const row=node('div',undefined,'event '+(event.kind==='error'?'error':''));row.append(node('span',event.kind==='error'?'!':event.kind==='model'&&active?'◌':'✓'),node('p',event.message));$('events').append(row);}
  $('result').hidden=next.status!=='completed';text('result-text',next.result?.message||'');
  if(next.error)notice(next.error);
  const tabs=next.browser?.tabs||[],signature=JSON.stringify([tabs,next.browser?.active_tab_id]);
  if(signature!==tabSignature){$('tabs').replaceChildren();if(!tabs.length)$('tabs').append(new Option('No managed tab',''));for(const tab of tabs)$('tabs').append(new Option(tab.title||tab.url||'Managed tab',String(tab.id)));$('tabs').value=String(next.browser?.active_tab_id||'');tabSignature=signature;}
  const validFrame=typeof next.protected_frame==='string'&&/^[A-Za-z0-9+/=]+$/.test(next.protected_frame);
  $('preview').hidden=!validFrame;$('preview-empty').hidden=validFrame;
  if(validFrame&&next.protected_frame!==lastFrame){$('preview').src='data:image/png;base64,'+next.protected_frame;lastFrame=next.protected_frame;}
  if(!validFrame){$('preview').removeAttribute('src');lastFrame='';}
  text('preview-state',validFrame?'Protected preview':next.detector?.status==='loading'?'Protecting the screenshot…':'No protected preview');
  text('detector',next.detector?.error?'Protection unavailable':next.detector?.status==='ready'?'Protected on your computer':'Local screenshot protection');
  text('frame-info',next.detector?.latency_ms!==null&&next.detector?.latency_ms!==undefined?`${next.detector.latency_ms} ms`:'');
  text('mask-count',next.manifest?.length??0);text('call-count',next.stats?.model_calls||0);text('resolved-count',next.stats?.resolved||0);
  $('tokens').replaceChildren();for(const token of next.manifest||[])$('tokens').append(node('span',token.token,'token'));
  controls();
}
async function refreshConnection(){
  const connection=await api('/api/connection');connected=connection.connected;
  $('connection').classList.toggle('offline',!connected);$('connection').replaceChildren(node('i'),node('span',connected?'Computer connected':'Computer offline'));
  if(connected)render(await api('/api/state'));else controls();
}
async function poll(){
  if(!authenticated||polling||document.hidden)return;polling=true;
  try{await refreshConnection();if(state?.status==='completed')await loadHistory();}catch(error){if(authenticated){connected=false;controls();notice(error.message);}}finally{polling=false;}
}
async function action(path,body={}){
  if(busy)return;busy=true;notice();controls();
  try{const result=await api(path,body);await refreshConnection();return result;}catch(error){notice(error.message);throw error;}finally{busy=false;controls();}
}
async function unlock(key){
  const response=await fetch('/auth/session',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({key})});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Could not unlock workspace');
  authenticated=true;$('workspace-key').value='';$('login-dialog').close();await Promise.all([poll(),loadSkills(),loadHistory()]);
}
$('login-dialog').addEventListener('cancel',event=>event.preventDefault());
$('login-form').addEventListener('submit',async event=>{event.preventDefault();try{await unlock($('workspace-key').value.trim());text('login-error','');}catch(error){text('login-error',error.message);}});
$('browser-form').addEventListener('submit',event=>{event.preventDefault();action('/api/browser/open',{url:$('browser-url').value.trim()}).catch(()=>{});});
$('refresh').onclick=()=>action('/api/browser/preview').catch(()=>{});
$('close-browser').onclick=()=>action('/api/browser/close').catch(()=>{});
$('tabs').onchange=()=>action('/api/browser/select',{tab_id:$('tabs').value}).catch(()=>{});
$('task-form').addEventListener('submit',async event=>{
  event.preventDefault();if($('run').disabled)return;
  const request=$('task-input').value.trim();if(!request)return;
  const task=attached?`Use the following reviewed procedure as guidance, adapting to the current website and fresh inputs.\n\nProcedure: ${attached.name}\n${attached.instructions}\n\nNew task: ${request}`:request;
  try{await action('/api/run',{mode:'astra',source:'web',task});$('task-input').value='';}catch{}
});
$('stop').onclick=async()=>{try{await api('/api/stop',{});notice('Stop requested. Waiting for the current operation to finish.');await poll();}catch(error){notice(error.message);}};
$('new-task').onclick=()=>{setView('tasks');$('task-input').value='';$('task-input').focus();notice();};
$('nav-tasks').onclick=()=>setView('tasks');$('nav-skills').onclick=()=>{setView('skills');loadSkills().catch(error=>notice(error.message));};
$('settings-button').onclick=()=>{$('settings-dialog').showModal();controls();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
$('logout').onclick=async()=>{try{if(state?.status==='running')await api('/api/stop',{});await api('/auth/logout',{});$('settings-dialog').close();state=null;connected=false;render({});showLogin();}catch(error){notice(error.message);}};
function attach(skill){attached=skill;$('selected-skill').hidden=!skill;text('selected-skill-name',skill?'▤ '+skill.name:'');setView('tasks');$('task-input').focus();}
$('clear-skill').onclick=()=>attach(null);
async function loadSkills(){
  if(!authenticated)return;skills=(await api('/api/skills')).skills;text('skill-count',skills.length);$('skills-list').replaceChildren();
  if(!skills.length){const empty=node('div',undefined,'skill-card');empty.append(node('h3','Your first procedure starts here.'),node('p','After a task, save the steps and checks you want Astra to reuse. You can also write a procedure yourself.'));$('skills-list').append(empty);}
  for(const skill of skills){const card=node('article',undefined,'skill-card');card.append(node('h3',skill.name),node('p',skill.instructions));const actions=node('div',undefined,'skill-actions'),use=node('button','Use in a new task →','primary'),remove=node('button','Delete','text-button');use.onclick=()=>attach(skill);remove.onclick=async()=>{if(!confirm(`Delete “${skill.name}”?`))return;try{await api('/api/skills/'+skill.id,undefined,'DELETE');if(attached?.id===skill.id)attach(null);await loadSkills();}catch(error){notice(error.message);}};actions.append(use,remove);card.append(actions);$('skills-list').append(card);}
}
function editSkill(fromTask=false){
  $('skill-name').value='';$('skill-instructions').value=fromTask&&state?.task?`Task pattern:\n${state.task}\n\nReusable steps:\n1. Inspect the current page and identify the new inputs.\n2. [Write the steps you want to repeat.]\n3. Check the result against the new task.\n\nUse fresh private references from the current session.`:'';
  text('skill-error','');$('skill-dialog').showModal();
}
$('add-skill').onclick=()=>editSkill();$('save-procedure').onclick=()=>editSkill(true);
$('skill-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/skills',{name:$('skill-name').value,instructions:$('skill-instructions').value});$('skill-dialog').close();await loadSkills();setView('skills');}catch(error){text('skill-error',error.message);}});
async function loadHistory(){
  if(!authenticated)return;history=(await api('/api/history')).history;$('recent').replaceChildren();
  if(!history.length)$('recent').append(node('p','Your completed tasks appear here.','quiet'));
  for(const run of history){const button=node('button',run.task||'Completed task');button.title=run.task;button.onclick=()=>{setView('tasks');$('task-input').value=run.task||'';notice('Previous task loaded into the composer. Running it starts a new task on the current website.');};$('recent').append(button);}
}
$('evidence-button').onclick=async()=>{
  $('evidence-dialog').showModal();$('evidence-list').replaceChildren(node('p','Loading provider receipts…','quiet'));
  try{const {requests}=await api('/api/audit');$('evidence-list').replaceChildren();if(!requests.length)$('evidence-list').append(node('p','No provider request has been recorded. Opening and previewing a website do not call Astra.','quiet'));
    for(const item of requests.slice(-20).reverse()){const card=node('section',undefined,'evidence-card');card.append(node('h3',`${item.status||'Recorded'} · ${item.response_model||'Provider request'}`));const facts=node('dl');for(const [label,value] of [['Response ID',item.response_id],['Frame hash',item.frame_hash],['HTTP status',item.http_status],['Source',item.source]])facts.append(node('dt',label),node('dd',value||'Not recorded'));card.append(facts);const details=node('details');details.append(node('summary','Recorded actions and usage'),node('pre',JSON.stringify({actions:item.actions,usage:item.usage,error:item.error},null,2)));card.append(details);$('evidence-list').append(card);}
  }catch(error){$('evidence-list').replaceChildren(node('p',error.message,'error'));}
};
$('export').onclick=async()=>{try{const data=await api('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=node('a');link.href=url;link.download='plva-protected-evidence.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message);}};
async function initialize(){
  const key=new URLSearchParams(location.hash.slice(1)).get('access');
  if(key){historyReplace();try{await unlock(key);return;}catch(error){text('login-error',error.message);showLogin();return;}}
  try{const session=await api('/auth/session');authenticated=session.authenticated;await Promise.all([poll(),loadSkills(),loadHistory()]);}catch{showLogin();}
}
function historyReplace(){window.history.replaceState(null,'',location.pathname+location.search);}
const context=document.modelContext;
if(context?.registerTool){
  const lifecycle=new AbortController();
  for(const tool of [
    {name:'read_plva_status',description:'Read connection status and the current protected browser task. Does not start a task.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:async()=>{await poll();return {connected,status:state?.status,task:state?.task,modelCalls:state?.stats?.model_calls||0};}},
    {name:'stage_plva_task',description:'Fill the visible task composer for operator review. Does not run Astra.',inputSchema:{type:'object',properties:{task:{type:'string',minLength:1,maxLength:6000}},required:['task'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},execute:async input=>{if(!input||typeof input.task!=='string'||!input.task.trim()||input.task.length>6000)throw Error('Provide a task of 1–6000 characters');setView('tasks');$('task-input').value=input.task;return {staged:true,started:false};}}
  ])try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}
  addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
controls();initialize();setInterval(poll,2000);
