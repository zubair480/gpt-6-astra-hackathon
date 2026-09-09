import {randomBytes} from 'node:crypto';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {homedir} from 'node:os';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const folder=join(process.env.LOCALAPPDATA||homedir(),'PLVA','CloudWorkspace');
await mkdir(folder,{recursive:true});
const target=join(folder,'secrets.json');
let secrets;
try{secrets=JSON.parse(await readFile(target,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;secrets={APP_ACCESS_KEY:randomBytes(32).toString('hex'),BRIDGE_KEY:randomBytes(32).toString('hex')};await writeFile(target,JSON.stringify(secrets),{mode:0o600});}
if(!/^[a-f0-9]{64}$/.test(secrets.APP_ACCESS_KEY)||!/^[a-f0-9]{64}$/.test(secrets.BRIDGE_KEY))throw Error('Invalid workspace credential file');
await writeFile(join(root,'.dev.vars'),Object.entries(secrets).map(([name,value])=>`${name}=${value}`).join('\n'),{mode:0o600});
const url='https://plva-app.zubairzafar480.workers.dev/#access='+secrets.APP_ACCESS_KEY;
await writeFile(join(folder,'Open PLVA.html'),`<!doctype html><meta charset="utf-8"><title>Open your PLVA workspace</title><script>location.replace(${JSON.stringify(url)})</script><a href="${url}">Open your private PLVA workspace</a>`,{mode:0o600});
console.log('Workspace credentials and private launcher are ready in '+folder+'. No credentials are stored in Git.');
