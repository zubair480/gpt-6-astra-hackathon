const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const PLVA = require('./scenes.js');

// Run the actual player with a controlled animation clock and its small DOM surface.
function player(hash = '#1', reduced = false) {
  let now = 0, id = 0;
  const frames = new Map(), elements = new Map(), listeners = new Map(), visited = [];
  const classList = () => {
    const classes = new Set();
    return {contains: name => classes.has(name), add: name => classes.add(name),
      remove: name => classes.delete(name), toggle(name) { if (classes.has(name)) classes.delete(name); else classes.add(name); }};
  };
  const element = name => {
    if (!elements.has(name)) {
      let html = '', fields = [];
      elements.set(name, {textContent:'', disabled:false, style:{}, classList:classList(),
        get innerHTML() { return html; },
        set innerHTML(value) { html = value; fields = [...value.matchAll(/<text\b([^>]*)>([^<]*)<\/text>/g)].filter(match => match[1].includes('data-type')).map(match => ({textContent:match[2]})); },
        querySelectorAll: () => fields});
    }
    return elements.get(name);
  };
  const location = {hash};
  const document = {getElementById:element, body:{classList:classList()}, documentElement:{},
    addEventListener: (name, callback) => listeners.set(name, callback)};
  const context = {PLVA, document, location, history:{replaceState(_state, _title, value) {location.hash=value;visited.push(value);}},
    performance:{now:()=>now}, matchMedia:()=>({matches:reduced}),
    requestAnimationFrame:callback=>{frames.set(++id,callback);return id;}, cancelAnimationFrame:frame=>frames.delete(frame)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'player.js'),'utf8'),context);
  return {element, visited,
    click(name) { const target=element(name); if (!target.disabled) target.onclick(); },
    key(key, options={}) {let prevented=false;listeners.get('keydown')({key,preventDefault(){prevented=true;},target:{closest:()=>false},...options});return prevented;},
    advance(ms) {const end=now+ms;while(now<end){now=Math.min(now+50,end);const batch=[...frames.values()];frames.clear();batch.forEach(callback=>callback(now));}},
    get scene(){return Number(location.hash.slice(1));},
    get pending(){return frames.size;}
  };
}

const manual = player();
assert.equal(manual.element('next').textContent,'Enter prompt →');
const clicks = [
  {time:5000, scene:2, label:'Run task →'},
  {time:21000, scene:6, label:'Create skill →'},
  {time:10000, scene:8, label:'Reuse skill →'},
  {time:21000, scene:12, label:'Complete'}
];
for (const step of clicks) {
  manual.click('next');
  assert.equal(manual.element('next').disabled,true);
  const current=manual.scene;
  manual.key('ArrowRight'); // accidental double-advance cannot skip the active action
  assert.equal(manual.scene,current);
  manual.advance(step.time);
  assert.equal(manual.scene,step.scene);
  assert.equal(manual.element('next').textContent,step.label);
  const clock=manual.element('time').textContent;
  manual.advance(2500); // each completed action waits indefinitely for narration
  assert.equal(manual.scene,step.scene);
  assert.equal(manual.element('time').textContent,clock);
}
assert.deepEqual(manual.visited,Array.from({length:12},(_,i)=>`#${i+1}`));
assert.equal(manual.element('time').textContent,'01:00 / 01:00');
assert.equal(manual.pending,0);
manual.click('back');assert.equal(manual.scene,8);
manual.click('back');assert.equal(manual.scene,6);
manual.click('back');assert.equal(manual.scene,2);
manual.click('back');assert.equal(manual.scene,1);

const interrupted=player('#2');
interrupted.key('ArrowRight');interrupted.advance(5000);
assert.equal(interrupted.scene,4);
interrupted.key('p');
const pausedTime=interrupted.element('time').textContent;
interrupted.advance(10000);
assert.equal(interrupted.element('time').textContent,pausedTime);
assert.equal(interrupted.element('play').textContent,'Resume');
interrupted.key('ArrowRight');interrupted.advance(16000);
assert.equal(interrupted.scene,6);
assert.equal(interrupted.element('next').textContent,'Create skill →');
interrupted.click('next');interrupted.advance(1000);interrupted.key('r');interrupted.advance(20000);
assert.equal(interrupted.scene,1);assert.equal(interrupted.pending,0);

const automatic=player();automatic.click('play');automatic.advance(59950);
assert.equal(automatic.element('play').textContent,'Pause');
automatic.advance(50);
assert.equal(automatic.scene,12);
assert.equal(automatic.element('time').textContent,'01:00 / 01:00');
assert.equal(automatic.element('play').textContent,'Play 60s');
assert.equal(automatic.pending,0);
automatic.click('play');assert.equal(automatic.scene,1);automatic.advance(3000);assert.equal(automatic.scene,2);

const linked=player('#10',true);linked.click('next');linked.advance(16000);
assert.equal(linked.scene,12);assert.equal(linked.element('next').disabled,true);
const keyboard=player();
assert.equal(keyboard.key('Enter',{target:{closest:selector=>selector==='button,a'}}),false);
assert.equal(keyboard.scene,1);
keyboard.key('ArrowRight',{repeat:true});assert.equal(keyboard.scene,1);
keyboard.key('ArrowRight');keyboard.advance(1000);
assert.ok(keyboard.element('screen').querySelectorAll('[data-type]')[0].textContent.length>0);
assert.ok(keyboard.element('screen').querySelectorAll('[data-type]')[0].textContent.length<45);
keyboard.advance(4000);assert.equal(keyboard.scene,2);

console.log('Verified four-click playback, all intermediate scenes, automatic pauses, duplicate-click protection, Back/Reset, pause/resume, keyboard controls, deep links, typing, and full 60-second autoplay.');
