import test from 'node:test';
import assert from 'node:assert/strict';
import {sameSecret,issueSession,validSession} from '../src/auth.mjs';
const key='c'.repeat(64),now=1788916000000;
const request=token=>new Request('https://example.com/api/state',{headers:{cookie:'plva_session='+token}});
test('workspace secrets require an exact match and a configured server key',async()=>{
  assert.equal(await sameSecret(key,key),true);
  assert.equal(await sameSecret(key,'d'.repeat(64)),false);
  assert.equal(await sameSecret(undefined,key),false);
  assert.equal(await sameSecret('',undefined),false);
});
test('session signature, expiry, and server-key rotation are enforced',async()=>{
  const token=await issueSession(key,now);
  assert.equal(await validSession(request(token),key,now),true);
  assert.equal(await validSession(request(token),key,now+8*60*60*1000),false);
  assert.equal(await validSession(request(token),'d'.repeat(64),now),false);
  assert.equal(await validSession(request(token.replace(/^\d/, '9')),key,now),false);
  assert.equal(await validSession(new Request('https://example.com/api/state'),key,now),false);
});
