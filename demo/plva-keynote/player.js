(()=>{
  'use strict';
  const $=id=>document.getElementById(id), data=PLVA.scenes;
  let index=0,playing=false,elapsed=0,start=0,raf=0,typeRaf=0;
  const starts=data.map((_,i)=>data.slice(0,i).reduce((n,s)=>n+s.duration,0));
  const total=data.reduce((n,s)=>n+s.duration,0);
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function clock(s){s=Math.min(total,Math.floor(s));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
  function render(animate=true){
    cancelAnimationFrame(typeRaf);
    $('screen').innerHTML=PLVA.svg(index);
    $('chapter').textContent=`${String(index+1).padStart(2,'0')}  ${data[index].title}`;
    $('note-text').textContent=data[index].note;
    $('note-time').textContent=`${clock(starts[index])}–${clock(starts[index]+data[index].duration)}`;
    $('back').disabled=index===0;$('next').disabled=index===data.length-1;
    document.title=`PLVA · ${data[index].title}`;
    history.replaceState(null,'',`#${index+1}`);
    const fields=[...$('screen').querySelectorAll('[data-type]')];
    if(animate&&!reduced&&fields.length){
      const all=fields.map(e=>e.textContent),t0=performance.now();
      fields.forEach(e=>e.textContent='');
      const speed=index===1?26:13;
      function type(t){let offset=0,done=true;fields.forEach((e,k)=>{const count=Math.max(0,Math.floor((t-t0-offset)/speed));e.textContent=all[k].slice(0,count);if(count<all[k].length)done=false;offset+=all[k].length*speed+90;});if(!done)typeRaf=requestAnimationFrame(type);}
      typeRaf=requestAnimationFrame(type);
    }
    updateClock();
  }
  function updateClock(){ $('time').textContent=`${clock(elapsed)} / 01:00`;$('progress').style.width=`${elapsed/total*100}%`; }
  function pause(){playing=false;cancelAnimationFrame(raf);$('play').textContent='Play 60s';}
  function go(i){pause();index=Math.max(0,Math.min(data.length-1,i));elapsed=starts[index];render();}
  function tick(now){elapsed=Math.min(total,(now-start)/1000);const next=data.findIndex((s,i)=>elapsed<starts[i]+s.duration);if(next>=0&&next!==index){index=next;render();}updateClock();if(elapsed>=total){pause();return;}raf=requestAnimationFrame(tick);}
  function play(){if(playing){pause();return;}if(elapsed>=total){index=0;elapsed=0;render();}playing=true;start=performance.now()-elapsed*1000;$('play').textContent='Pause';raf=requestAnimationFrame(tick);}
  function stage(){const entering=!document.body.classList.contains('stage-mode');document.body.classList.toggle('stage-mode');$('notes').classList.remove('show');if(entering&&document.documentElement.requestFullscreen){document.documentElement.requestFullscreen().catch(()=>{});}else if(!entering&&document.fullscreenElement){document.exitFullscreen().catch(()=>{});}}
  $('next').onclick=()=>go(index+1);$('back').onclick=()=>go(index-1);$('play').onclick=play;$('reset').onclick=()=>go(0);$('stage').onclick=stage;
  $('notes-button').onclick=()=>$('notes').classList.toggle('show');$('help-button').onclick=()=>$('help').classList.add('show');$('close-help').onclick=()=>$('help').classList.remove('show');
  document.addEventListener('keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey)return;const k=e.key.toLowerCase();if(k==='escape'){$('help').classList.remove('show');$('notes').classList.remove('show');document.body.classList.remove('stage-mode');return;}if($('help').classList.contains('show'))return;if(['arrowright',' ','pagedown','enter'].includes(k)){e.preventDefault();go(index+1);}else if(['arrowleft','pageup'].includes(k)){e.preventDefault();go(index-1);}else if(k==='p')play();else if(k==='r')go(0);else if(k==='n')$('notes').classList.toggle('show');else if(k==='f')stage();else if(k==='?')$('help').classList.add('show');});
  const initial=Number(location.hash.slice(1));if(Number.isInteger(initial)&&initial>=1&&initial<=data.length)index=initial-1;
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)document.body.classList.remove('stage-mode');});
  elapsed=starts[index];render(false);
  // Presentation-only controls. No model calls, form submissions, or private data access.
})();
