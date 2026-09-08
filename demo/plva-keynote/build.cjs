const fs = require('node:fs/promises');
const path = require('node:path');
const { scenes } = require('./scenes.js');

(async () => {
  const root = __dirname;
  const dest = path.join(root, 'dist');
  await fs.mkdir(dest, {recursive:true});
  const source = await fs.readFile(path.join(root, 'index.html'), 'utf8');
  const portable = source
    .replace('<script src="scenes.js"></script>', `<script>${await fs.readFile(path.join(root, 'scenes.js'), 'utf8')}</script>`)
    .replace('<script src="player.js"></script>', `<script>${await fs.readFile(path.join(root, 'player.js'), 'utf8')}</script>`);
  await fs.writeFile(path.join(root, 'PLVA-DEMO.html'), portable);
  const files = ['index.html', 'PLVA-DEMO.html', 'scenes.js', 'player.js', 'favicon.svg',
    'README.md', 'NARRATION.md', 'STORYBOARD.png', 'images', 'editable'];
  for (const file of files) {
    await fs.cp(path.join(root, file), path.join(dest, file), {recursive:true});
  }
  const cards = scenes.map((scene, index) => {
    const name = String(index + 1).padStart(2, '0') + '-' + scene.id;
    return `<article><a href="${name}.png" download><img src="${name}.png" width="3840" height="2160" loading="lazy" alt="${scene.title}"></a><p>${index + 1}. ${scene.title}</p><a href="${name}.png" download>4K PNG</a> · <a href="../editable/${name}.svg" download>Editable SVG</a></article>`;
  }).join('');
  await fs.writeFile(path.join(dest, 'images', 'index.html'),
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PLVA · 4K screens</title><style>*{box-sizing:border-box}body{margin:0;padding:32px;font:16px/1.6 'Segoe UI',Arial,sans-serif;background:#f3f6f6;color:#172225}main{max-width:1400px;margin:auto}h1{font-weight:500}a{color:#087e67}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:24px}article{padding:16px;background:white;border:1px solid #e0e6e6;border-radius:12px}img{display:block;width:100%;height:auto}p{margin:10px 0}</style></head><body><main><a href="../">← Back to demo</a><h1>PLVA · 4K screens</h1><p>Twelve separate 3840 × 2160 screens from the scripted walkthrough.</p><div class="grid">${cards}</div></main></body></html>`);
  await fs.writeFile(path.join(dest, '_headers'),
    '/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n');
  await fs.writeFile(path.join(dest, '404.html'),
    '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PLVA</title><body style="font-family:Segoe UI,Arial,sans-serif;padding:48px;color:#172225"><h1>Page not found</h1><a href="/" style="color:#087e67">Open the PLVA demo</a></body></html>');
  console.log(`Built the complete PLVA demo in ${dest}`);
})().catch(error => { console.error(error); process.exitCode = 1; });
