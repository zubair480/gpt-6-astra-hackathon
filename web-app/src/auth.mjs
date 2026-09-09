const encoder=new TextEncoder();
const hex=bytes=>Array.from(new Uint8Array(bytes),byte=>byte.toString(16).padStart(2,'0')).join('');
export async function sameSecret(given,expected){
  if(typeof given!=='string'||typeof expected!=='string'||given.length>512||expected.length<32)return false;
  const [a,b]=await Promise.all([given,expected].map(value=>crypto.subtle.digest('SHA-256',encoder.encode(value))));
  const x=new Uint8Array(a),y=new Uint8Array(b);let diff=0;for(let i=0;i<x.length;i++)diff|=x[i]^y[i];return diff===0;
}
async function signingKey(secret){return crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign','verify']);}
export async function issueSession(secret,now=Date.now()){
  const expires=String(Math.floor(now/1000)+8*60*60);
  return expires+'.'+hex(await crypto.subtle.sign('HMAC',await signingKey(secret),encoder.encode('plva-owner:'+expires)));
}
export async function validSession(request,secret,now=Date.now()){
  if(!secret)return false;
  const token=(request.headers.get('cookie')||'').split(';').map(part=>part.trim()).find(part=>part.startsWith('plva_session='))?.slice(13);
  if(!token)return false;
  const [expires,signature]=token.split('.');
  if(!/^\d{10}$/.test(expires)||!/^([a-f0-9]{2}){32}$/.test(signature)||Number(expires)<=now/1000||Number(expires)>now/1000+8*60*60+5)return false;
  return crypto.subtle.verify('HMAC',await signingKey(secret),Uint8Array.from(signature.match(/../g),byte=>parseInt(byte,16)),encoder.encode('plva-owner:'+expires));
}
export function json(value,status=200,headers={}){return new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json','cache-control':'no-store','x-content-type-options':'nosniff',...headers}});}
