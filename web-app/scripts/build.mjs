import {mkdir, cp, readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
await mkdir(join(root,'dist'),{recursive:true});
await cp(join(root,'public'),join(root,'dist'),{recursive:true});
for(const file of ['index.html','app.js','app.css']) await readFile(join(root,'dist',file));
await writeFile(join(root,'dist','_headers'),'/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n  X-Frame-Options: DENY\n  Content-Security-Policy: default-src \'self\'; img-src \'self\' data:; style-src \'self\'; script-src \'self\'; connect-src \'self\'; frame-ancestors \'none\'; base-uri \'none\'; form-action \'self\'\n');
console.log('Built PLVA application assets.');
