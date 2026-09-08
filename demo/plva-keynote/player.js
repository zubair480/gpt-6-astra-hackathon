(()=>{
  'use strict';
  const $=id=>document.getElementById(id), data=PLVA.scenes;
  const starts=data.map((_,i)=>data.slice(0,i).reduce((n,s)=>n+s.duration,0));
  const total=data.reduce((n,s)=>n+s.duration,0);
  const beats=[
    {from:1,to:1,label:'Enter prompt',running:'Typing prompt…',ready:'Prompt ready'},
    {from:2,to:5,label:'Run task',running:'Running task…',ready:'First draft ready'},
    {from:6,to:7,label:'Create skill',running:'Creating skill…',ready:'Skill ready'},
    {from:8,to:11,label:'Reuse skill',running:'Reusing skill…',ready:'Final result'}
  ];
  const endOf=beat=>starts[beat.to]+data[beat.to].duration;
  const beatAt=scene=>beats.findIndex(beat=>scene>=beat.from&&scene<=beat.to);
  let index=0,playing=false,elapsed=0,start=0,raf=0,typeRaf=0;
  let mode=null,targetBeat=null;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function clock(s){s=Math.min(total,Math.floor(s));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
  function controls(){
    const beatIndex=beatAt(index), beat=beats[beatIndex];
    const atStop=beat&&index===beat.to;
    const finished=index===data.length-1&&!playing&&!mode;
    const nextBeat=index===0?beats[0]:atStop?beats[beatIndex+1]:beat;
    $('back').disabled=index===0;
    $('next').disabled=playing||finished;
    $('next').textContent=playing?(mode==='step'?beats[targetBeat].running:'Playing…'):
      mode?'Continue →':finished?'Complete':nextBeat?`${atStop||index===0?nextBeat.label:'Continue'} →`:'Complete';
    $('play').textContent=playing?'Pause':mode?'Resume':'Play 60s';
    $('chapter').textContent=index===0?'Ready · Four clicks to present':
      `${beatIndex+1} / 4 · ${atStop&&!playing?beat.ready:data[index].title}`;
  }
  function updateClock(){ $('time').textContent=`${clock(elapsed)} / 01:00`;$('progress').style.width=`${elapsed/total*100}%`; }
  function render(animate=true){
    cancelAnimationFrame(typeRaf);
    $('screen').innerHTML=PLVA.svg(index);
    $('note-text').textContent=data[index].note;
    $('note-time').textContent=`${clock(starts[index])}–${clock(starts[index]+data[index].duration)}`;
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
    controls();updateClock();
  }
  function pause(){playing=false;cancelAnimationFrame(raf);controls();}
  function stop(){playing=false;cancelAnimationFrame(raf);mode=null;targetBeat=null;controls();}
  function go(i){stop();index=Math.max(0,Math.min(data.length-1,i));elapsed=starts[index];render(false);}
  function tick(now){
    const limit=mode==='step'?endOf(beats[targetBeat]):total;
    elapsed=Math.min(limit,(now-start)/1000);
    if(elapsed>=limit){
      const last=mode==='step'?beats[targetBeat].to:data.length-1;
      if(index!==last){index=last;render();}
      stop();updateClock();return;
    }
    const next=data.findIndex((scene,i)=>elapsed<starts[i]+scene.duration);
    if(next>=0&&next!==index){index=next;render();}
    updateClock();raf=requestAnimationFrame(tick);
  }
  function resume(){playing=true;start=performance.now()-elapsed*1000;controls();raf=requestAnimationFrame(tick);}
  function advance(){
    if(playing)return;
    if(mode){resume();return;}
    const current=beatAt(index);
    const next=index===0?0:index===beats[current].to?current+1:current;
    if(next>=beats.length)return;
    const beat=beats[next];
    mode='step';targetBeat=next;
    if(index<beat.from){index=beat.from;elapsed=starts[index];render();}
    resume();
  }
  function back(){
    const current=beatAt(index);
    go(current>0?beats[current-1].to:0);
  }
  function play(){
    if(playing){pause();return;}
    if(mode){resume();return;}
    if(index===data.length-1||elapsed>=total)go(0);
    mode='all';resume();
  }
  function stage(){const entering=!document.body.classList.contains('stage-mode');document.body.classList.toggle('stage-mode');$('notes').classList.remove('show');if(entering&&document.documentElement.requestFullscreen){document.documentElement.requestFullscreen().catch(()=>{});}else if(!entering&&document.fullscreenElement){document.exitFullscreen().catch(()=>{});}}
  $('next').onclick=advance;$('back').onclick=back;$('play').onclick=play;$('reset').onclick=()=>go(0);$('stage').onclick=stage;
  $('notes-button').onclick=()=>$('notes').classList.toggle('show');$('help-button').onclick=()=>$('help').classList.add('show');$('close-help').onclick=()=>$('help').classList.remove('show');
  document.addEventListener('keydown',e=>{
    if(e.ctrlKey||e.metaKey||e.altKey||e.repeat)return;
    if(e.target?.closest('input,textarea,select,[contenteditable="true"]'))return;
    const k=e.key.toLowerCase();
    if(k==='escape'){$('help').classList.remove('show');$('notes').classList.remove('show');document.body.classList.remove('stage-mode');return;}
    if($('help').classList.contains('show'))return;
    // Let focused buttons and links keep their native Enter/Space behavior.
    if((k==='enter'||k===' ')&&e.target?.closest('button,a'))return;
    if(['arrowright',' ','pagedown','enter'].includes(k)){e.preventDefault();advance();}
    else if(['arrowleft','pageup'].includes(k)){e.preventDefault();back();}
    else if(k==='p')play();else if(k==='r')go(0);else if(k==='n')$('notes').classList.toggle('show');else if(k==='f')stage();else if(k==='?')$('help').classList.add('show');
  });
  const initial=Number(location.hash.slice(1));if(Number.isInteger(initial)&&initial>=1&&initial<=data.length)index=initial-1;
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)document.body.classList.remove('stage-mode');});
  elapsed=starts[index];render(false);
  // Four presenter actions, with automatic transitions inside each action.
  // Presentation-only: no model calls, customer data access, or form submissions.
})();
