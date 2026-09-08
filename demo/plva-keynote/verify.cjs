const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { scenes, svg } = require('./scenes.js');

assert.equal(scenes.length, 12);
assert.equal(scenes.reduce((seconds, scene) => seconds + scene.duration, 0), 60);
for (let i = 3; i <= 7; i++) {
  assert.doesNotMatch(svg(i), /\[(NAME|EMAIL|ADDRESS)_2\]/, `First customer scene ${i + 1}`);
}
for (let i = 8; i < 12; i++) {
  const screen = svg(i);
  assert.match(screen, /\[NAME_2\]/, `Second customer name in scene ${i + 1}`);
  assert.match(screen, /\[ADDRESS_2\]/, `Second customer destination in scene ${i + 1}`);
  assert.doesNotMatch(screen, /\[(NAME|EMAIL|ADDRESS)_1\]/, `No first-customer reference in scene ${i + 1}`);
}
for (const i of [3, 4]) {
  for (const label of ['NAME', 'EMAIL', 'ADDRESS']) assert.ok(svg(i).includes(`[${label}_1]`));
}
for (const i of [8, 9]) assert.ok(svg(i).includes('[EMAIL_2]'));
const portable = fs.readFileSync(path.join(__dirname, 'PLVA-DEMO.html'), 'utf8');
assert.ok(portable.includes(fs.readFileSync(path.join(__dirname, 'scenes.js'), 'utf8')));
assert.ok(portable.includes(fs.readFileSync(path.join(__dirname, 'player.js'), 'utf8')));
for (let i = 0; i < scenes.length; i++) {
  const name = String(i + 1).padStart(2, '0') + '-' + scenes[i].id;
  const png = fs.readFileSync(path.join(__dirname, 'images', name + '.png'));
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(png.readUInt32BE(16), 3840);
  assert.equal(png.readUInt32BE(20), 2160);
  assert.equal(fs.readFileSync(path.join(__dirname, 'editable', name + '.svg'), 'utf8'), svg(i));
}
for (const file of ['index.html', 'PLVA-DEMO.html', 'images/index.html', 'favicon.svg']) {
  assert.ok(fs.existsSync(path.join(__dirname, 'dist', file)), `Published asset: ${file}`);
}
console.log('Verified: 60-second timeline, distinct customer references, current portable demo, 12 current SVGs and 4K PNGs, and web entry points.');
