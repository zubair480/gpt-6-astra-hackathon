import {DurableObject} from 'cloudflare:workers';
import {sameSecret,issueSession,validSession,json} from './auth.mjs';
const READ=new Set(['/api/state','/api/audit','/api/export']);
const WRITE=new Set(['/api/browser/open','/api/browser/select','/api/browser/preview','/api/browser/close','/api/run','/api/stop']);
const room=env=>env.WORKSPACE.get(env.WORKSPACE.idFromName('owner-workspace'));
export default {
  async fetch(request,env){
    const url=new URL(request.url),path=url.pathname;
    if(path==='/health')return json({service:'PLVA application',ok:true});
    if(path==='/bridge'||path==='/bridge/poll'||path==='/bridge/reply'){
      if(!await sameSecret(request.headers.get('authorization')?.replace(/^Bearer /,''),env.BRIDGE_KEY))return json({error:'Unauthorized'},401);
      if(request.method!=='POST'||path==='/bridge')return json({error:'Route not found'},404);
      return room(env).fetch(new Request('https://workspace'+path,request));
    }
    if(path==='/auth/session'&&request.method==='POST'){
      if(request.headers.get('origin')!==url.origin)return json({error:'Origin rejected'},403);
      if(!env.APP_ACCESS_KEY)return json({error:'Workspace setup is not complete'},503);
      let body;try{body=await request.json();}catch{return json({error:'Invalid request'},400);}
      if(!await sameSecret(body.key,env.APP_ACCESS_KEY))return json({error:'The workspace key is not valid'},401);
      return json({authenticated:true},200,{'set-cookie':`plva_session=${await issueSession(env.APP_ACCESS_KEY)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=28800`});
    }
    if(path.startsWith('/api/')||path.startsWith('/auth/')){
      if(!await validSession(request,env.APP_ACCESS_KEY))return json({error:'Unlock your workspace to continue'},401);
      if(!['GET','HEAD'].includes(request.method)&&request.headers.get('origin')!==url.origin)return json({error:'Origin rejected'},403);
      if(path==='/auth/session'&&request.method==='GET')return json({authenticated:true});
      if(path==='/auth/logout'&&request.method==='POST')return json({ok:true},200,{'set-cookie':'plva_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0'});
      if(path==='/api/connection')return room(env).fetch('https://workspace/connection');
      if(path==='/api/skills'||path==='/api/history'||/^\/api\/skills\/[a-f0-9-]+$/.test(path))return room(env).fetch(new Request('https://workspace'+path,request));
      if((request.method==='GET'&&READ.has(path))||(request.method==='POST'&&WRITE.has(path))){
        let body={};try{if(request.method==='POST')body=await request.json();}catch{return json({error:'Invalid request'},400);}
        if(JSON.stringify(body).length>16000)return json({error:'Request is too large'},413);
        if(path==='/api/run'&&(body.mode!=='astra'||body.source!=='web'||typeof body.task!=='string'||!body.task.trim()))return json({error:'Enter a task for the managed browser'},400);
        return room(env).fetch(new Request('https://workspace/rpc',{method:'POST',body:JSON.stringify({path,method:request.method,body})}));
      }
      return json({error:'Route not found'},404);
    }
    return env.ASSETS.fetch(request);
  }
};

export class Workspace extends DurableObject {
  constructor(ctx,env){super(ctx,env);this.pending=new Map();this.queue=[];this.lastSeen=0;}
  async fetch(request){
    const path=new URL(request.url).pathname;
    if(path==='/bridge/poll'){
      this.lastSeen=Date.now();
      const commands=this.queue.splice(0).filter(command=>this.pending.has(command.id));
      return json({commands});
    }
    if(path==='/bridge/reply'){
      let data;try{data=await request.json();}catch{return json({error:'Invalid reply'},400);}
      await this.receiveReply(data);return json({ok:true});
    }
    if(path==='/connection')return json({connected:Date.now()-this.lastSeen<10000});
    if(path==='/api/skills'){
      if(request.method==='GET')return json({skills:[...(await this.ctx.storage.list({prefix:'skill:'})).values()].sort((a,b)=>b.updatedAt-a.updatedAt)});
      if(request.method==='POST'){
        let body;try{body=await request.json();}catch{return json({error:'Invalid skill'},400);}
        if(typeof body.name!=='string'||!body.name.trim()||body.name.length>100||typeof body.instructions!=='string'||body.instructions.trim().length<10||body.instructions.length>8000)return json({error:'Add a name and a procedure of 10–8000 characters'},400);
        const existing=await this.ctx.storage.list({prefix:'skill:'});if(existing.size>=50)return json({error:'This workspace supports up to 50 saved skills'},409);
        const skill={id:crypto.randomUUID(),name:body.name.trim(),instructions:body.instructions.trim(),updatedAt:Date.now()};
        await this.ctx.storage.put('skill:'+skill.id,skill);return json({skill},201);
      }
    }
    if(path.startsWith('/api/skills/')&&request.method==='DELETE'){await this.ctx.storage.delete('skill:'+path.split('/').pop());return json({ok:true});}
    if(path==='/api/history'&&request.method==='GET')return json({history:[...(await this.ctx.storage.list({prefix:'run:',reverse:true,limit:20})).values()]});
    if(path==='/rpc'){
      if(Date.now()-this.lastSeen>=10000)return json({error:'Your computer is offline. Start the PLVA connector.'},503);
      if(this.pending.size>=12)return json({error:'The computer is busy. Please wait.'},429);
      const command=await request.json(),id=crypto.randomUUID();
      return new Promise(resolve=>{
        const timer=setTimeout(()=>{this.pending.delete(id);resolve(json({error:'The computer did not respond in time. Refresh its status before retrying.'},504));},125000);
        this.pending.set(id,{resolve,timer,path:command.path});
        this.queue.push({id,...command});
      });
    }
    return json({error:'Route not found'},404);
  }
  async receiveReply(data){
    const pending=this.pending.get(data.id);if(!pending)return;
    clearTimeout(pending.timer);this.pending.delete(data.id);
    const status=Number.isInteger(data.status)&&data.status>=200&&data.status<=599?data.status:502;
    if(pending.path==='/api/state'&&status===200&&data.body?.status==='completed'){
      const state=data.body,key='run:'+String(state.run_id||'');
      if(state.run_id&&!await this.ctx.storage.get(key)){
        await this.ctx.storage.put(key,{id:state.run_id,task:state.task,result:state.result,completedAt:Date.now(),calls:state.stats?.model_calls||0});
        const records=await this.ctx.storage.list({prefix:'run:',reverse:true});const old=[...records.keys()].slice(20);if(old.length)await this.ctx.storage.delete(old);
      }
    }
    pending.resolve(json(data.body,status));
  }
}
