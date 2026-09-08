(function(root){
  'use strict';
  const C={ink:'#172225',muted:'#758184',line:'#e0e6e6',paper:'#ffffff',wash:'#f6f8f8',mint:'#d8f7ee',green:'#087e67',rail:'#f3f6f6',light:'#eff3f3'};
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const rect=(x,y,w,h,fill=C.paper,r=0,stroke='none',extra='')=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" ${extra}/>`;
  const line=(x,y,x2,y2,color=C.line)=>`<path d="M${x} ${y}L${x2} ${y2}" stroke="${color}"/>`;
  const txt=(x,y,t,size=22,color=C.ink,weight=400,extra='')=>`<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${color}" ${extra}>${esc(t)}</text>`;
  const lines=(x,y,a,size=22,color=C.ink,weight=400,gap=34)=>a.map((t,i)=>txt(x,y+i*gap,t,size,color,weight)).join('');
  const icon=(name,x,y,s=24,color=C.ink)=>{
    const p={check:'M5 12l4 4L19 6',arrow:'M5 12h14m-6-6 6 6-6 6',up:'M12 19V5m-6 6 6-6 6 6',lock:'M7 10V7a5 5 0 0 1 10 0v3M5 10h14v11H5z',plus:'M12 5v14M5 12h14',file:'M6 2h8l4 4v16H6zM14 2v5h5M9 12h6m-6 4h6',grid:'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',chev:'M9 5l7 7-7 7',close:'M6 6l12 12M18 6 6 18',shield:'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6',spark:'M12 2l3 7 7 3-7 3-3 7-3-7-7-3 7-3z',clock:'M12 5v7l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',chat:'M3 3h18v14H9l-6 4z',repeat:'M4 8h15l-4-4m5 12H5l4 4M4 8v5m16 3v-5'}[name]||'';
    return `<svg x="${x}" y="${y}" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${p}"/></svg>`;
  };
  const pill=(x,y,w,label,color=C.green,fill=C.mint,ico)=>rect(x,y,w,36,fill,18)+(ico?icon(ico,x+11,y+8,19,color):'')+txt(x+(ico?39:15),y+24,label,17,color,500);
  const mark=(x,y,s=36,color=C.green)=>`<g transform="translate(${x} ${y}) scale(${s/36})"><path d="M6 29V8a2 2 0 0 1 2-2h15a7 7 0 0 1 0 14H13m0 9V13h9" stroke="${color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></g>`;
  const scenes=[
    {id:'ready',title:'One task. Private by default.',duration:3,note:'A customer needs a replacement.'},
    {id:'prompt',title:'Describe the task',duration:5,note:'We ask PLVA to handle it while keeping their details private.'},
    {id:'working',title:'The task starts',duration:4,note:'Before Astra sees the screen, PLVA protects it.'},
    {id:'privacy',title:'Only the protected view leaves',duration:6,note:'Sensitive details become tokens. The original values stay on the device.'},
    {id:'execute',title:'Private values, useful actions',duration:6,note:'Astra works with those tokens. PLVA restores values only in the intended local fields.'},
    {id:'result',title:'A replacement draft, ready',duration:5,note:'The replacement draft is ready, with its details checked.'},
    {id:'learning',title:'Turn work into a procedure',duration:5,note:'That workflow becomes a procedure, with its source evidence.'},
    {id:'skill',title:'A skill you can inspect',duration:5,note:'You can inspect its steps and reuse the procedure.'},
    {id:'new-task',title:'A new customer. A changed form.',duration:5,note:'Now a new customer arrives, and the form changes.'},
    {id:'reuse',title:'Same procedure. Fresh inputs.',duration:6,note:'A fresh session loads the procedure and applies new inputs to the current screen.'},
    {id:'second-result',title:'The new draft is ready',duration:6,note:'The procedure carries over. The private records don’t.'},
    {id:'close',title:'Your work becomes reusable.',duration:4,note:'PLVA. Your computer work becomes reusable knowledge.'}
  ];
  const prompt='Prepare a replacement for order ORD-2048.';
  const prompt2='Keep the customer’s details private.';
  const sidebar=(i)=>rect(0,0,220,1080,C.rail)+mark(26,35,38,'#087e67')+txt(75,64,'PLVA',28,'#172225',600)+rect(20,113,180,48,'#e3ecea',8)+icon('plus',35,126,22,'#50736a')+txt(70,144,'New task',19,'#172225')+txt(30,224,'WORKSPACE',13,'#7d8c8e',600,'letter-spacing="1.8"')+icon('chat',30,251,21,'#7b9091')+txt(65,269,'Tasks',19,'#506569')+icon('grid',30,300,21,i>=6?'#087e67':'#7b9091')+txt(65,318,'Skills',19,i>=6?'#087e67':'#506569')+(i>=7?pill(153,295,37,'1','#087e67','#d8f7ee'):'')+txt(30,413,'RECENT',13,'#7d8c8e',600,'letter-spacing="1.8"')+rect(16,439,188,52,'#e3ecea',8)+txt(31,470,'Replacement draft',17,'#194739')+txt(31,518,'Monthly review',17,'#718589')+txt(31,564,'Investor follow-up',17,'#718589')+rect(20,955,180,83,'#e7efec',10)+icon('shield',33,971,21,'#087e67')+txt(64,988,'Private workspace',15,'#24493e')+txt(33,1016,'Local protection on',15,'#6e8980');
  const chrome=(i)=>sidebar(i)+rect(220,0,1700,1080,C.paper)+line(220,109,1920,109)+txt(264,65,i>=8?'Replacement · ORD-3091':'Replacement · ORD-2048',25,C.ink,500)+pill(1514,33,184,'Private session',C.green,C.mint,'lock')+txt(1731,59,'GPT-6 Astra',19,C.muted)+line(956,110,956,998)+txt(265,1035,'Scripted product walkthrough · synthetic data',16,C.muted)+txt(1570,1035,`${String(i+1).padStart(2,'0')} / 12`,17,C.muted)+rect(1740,1020,130,4,C.light,2)+rect(1740,1020,130*(i+1)/12,4,C.green,2);
  const composer=(i,hero=false)=>{
    const y=hero?484:874;
    const filled=i===1;
    return rect(265,y,645,hero?166:76,'#fff',18,filled?'#8bcab9':C.line)+
      (filled?`<g class="prompt-typed">${txt(290,y+43,prompt,22,C.ink,400,'data-type="1"')}${txt(290,y+80,prompt2,22,C.ink,400,'data-type="1"')}</g>`:txt(289,y+44,hero?'What would you like to get done?':'Message PLVA',21,'#96a1a3'))+
      (hero?icon('plus',289,y+118,22,C.muted):'')+
      rect(849,y+(hero?107:15),43,43,filled?C.ink:'#f0f3f3',12)+icon('up',860,y+(hero?118:26),21,filled?'#fff':'#91a0a1')+
      (hero?txt(330,y+140,'Support workspace attached',16,C.muted):'');
  };
  const userBubble=(i)=>rect(322,157,588,120,'#f1f4f4',15)+lines(348,197,i>=8?['Use my replacement skill for ORD-3091.','The form has changed.']:['Prepare a replacement for order ORD-2048.','Keep the customer’s details private.'],21,C.ink,400,34);
  const agentHead=(message,y=330)=>mark(267,y-28,31)+txt(313,y-4,message,23,C.ink,500);
  function step(y,label,state='done',detail=''){
    const col=state==='done'?C.green:C.muted;
    const lead=state==='done'?icon('check',275,y-19,22,col):state==='active'?`<g class="spinner" style="transform-origin:286px ${y-7}px"><circle cx="286" cy="${y-7}" r="8" stroke="#d7e5e1" fill="none" stroke-width="2.5"/><path d="M286 ${y-15}a8 8 0 0 1 8 8" stroke="${C.green}" fill="none" stroke-width="2.5" stroke-linecap="round"/></g>`:`<circle cx="286" cy="${y-7}" r="4" fill="#c9d3d3"/>`;
    return `<g class="activity-step" data-active="${state==='active'}">${lead}${txt(316,y,label,21,state==='pending'?'#9aa5a6':C.ink,state==='active'?500:400)}${detail?txt(316,y+30,detail,17,C.muted):''}</g>`;
  }
  const field=(x,y,w,label,value,token=false,animate=false)=>txt(x,y,label,16,C.muted,500)+rect(x,y+13,w,50,token?'#e9f8f2':'#fff',8,token?'#b4dfcf':C.line)+txt(x+15,y+46,value,20,token?C.green:C.ink,token?500:400,animate?'data-type="1"':'')+(token?icon('lock',x+w-36,y+29,18,C.green):'');
  function browserHead(i,section='Support ticket'){
    return rect(996,149,882,794,'#fff',16,C.line)+rect(997,150,880,54,'#f6f8f8',16)+rect(997,180,880,24,'#f6f8f8')+['#d2dadb','#d2dadb','#d2dadb'].map((c,k)=>`<circle cx="${1023+20*k}" cy="177" r="5" fill="${c}"/>`).join('')+icon('lock',1130,166,19,'#7d8c8e')+txt(1158,182,'northstar.local / '+(section==='Support ticket'?'support':'replacements'),17,'#79888b')+line(996,204,1878,204)+txt(1024,248,'northstar',28,C.ink,600)+txt(1644,246,section,18,C.muted)+line(996,270,1878,270);
  }
  function workspace(i){
    const b=i>=8,protectedView=i>=3;
    const privateToken=label=>`[${label}_${b?2:1}]`;
    const name=b?'Alex Rivera':'Mia Chen',email=b?'alex.rivera@example.test':'mia.chen@example.test',order=b?'ORD-3091':'ORD-2048',address=b?'46 Juniper Street, Austin':'184 Cedar Lane, Portland';
    let z=txt(997,128,i>=3?'PROTECTED AGENT WORKSPACE':'CONNECTED WORKSPACE',14,C.muted,600,'letter-spacing="1.6"');
    if([0,1,2,3,8].includes(i)){
      z+=browserHead(i)+txt(1030,311,'TICKET / '+order,15,C.muted,500,'letter-spacing="1"')+txt(1030,364,b?'Replacement requested':'Damaged item on arrival',36,C.ink,500)+pill(1680,291,166,'Replacement',C.green,'#edf7f3')+lines(1030,416,b?['The replacement form has moved.','Please arrange a replacement for this order.']:['My order arrived damaged. Could you arrange','a replacement to the same shipping address?'],22,'#5c6c70',400,34)+line(1030,491,1845,491)+txt(1030,534,'Customer details',21,C.ink,500)+pill(1576,508,270,protectedView?'3 fields protected locally':'Visible only on this device',C.green,protectedView?C.mint:C.light,protectedView?'shield':'lock');
      z+=field(1030,574,391,'Full name',protectedView?privateToken('NAME'):name,protectedView)+field(1453,574,391,'Email',protectedView?privateToken('EMAIL'):email,protectedView)+field(1030,676,814,'Shipping address',protectedView?privateToken('ADDRESS'):address,protectedView)+field(1030,777,391,'Order',order)+field(1453,777,391,'Item',b?'Summit Bottle':'Trail Mug');
      z+=txt(1030,911,protectedView?'Contact details replaced before the model sees this view.':'Synthetic customer record · no real account connected',16,C.muted);
      if(i===3)z+=`<rect class="scan-line" x="1018" y="552" width="838" height="3" rx="1" fill="#33ad8f" opacity=".65"/>`;
      return z;
    }
    if([4,9].includes(i)){
      z+=browserHead(i,'Replacement form')+txt(1030,320,b?'NEW LAYOUT / ORD-3091':'ORD-2048',15,C.muted,500,'letter-spacing="1"')+txt(1030,371,'Replacement draft',36,C.ink,500)+pill(1620,294,225,'Local value resolution',C.green,C.mint,'lock');
      if(b){
        z+=field(1030,431,814,'Item','Summit Bottle',false,true)+field(1030,536,390,'Order reference',order,false,true)+field(1453,536,391,'Customer',privateToken('NAME'),true,true)+field(1030,641,814,'Destination',privateToken('ADDRESS'),true,true)+field(1030,746,600,'Contact email',privateToken('EMAIL'),true,true)+rect(1660,759,184,50,C.green,9)+txt(1690,792,'Save draft',20,'#fff',500);
      }else{
        z+=field(1030,431,390,'Order reference',order,false,true)+field(1453,431,391,'Item','Trail Mug',false,true)+field(1030,536,390,'Customer',privateToken('NAME'),true,true)+field(1453,536,391,'Email',privateToken('EMAIL'),true,true)+field(1030,641,814,'Shipping address',privateToken('ADDRESS'),true,true)+rect(1612,779,233,54,C.green,9)+txt(1643,814,'Prepare draft',20,'#fff',500);
      }
      z+=txt(1030,909,'Private values are inserted only into the intended local fields.',16,C.muted);
      z+=`<g class="demo-cursor" style="transform-origin:1746px 814px">${icon('arrow',1734,b?805:826,32,'#142a24')}</g>`;
      return z;
    }
    if([5,10,11].includes(i)){
      z+=browserHead(i,'Replacement draft')+`<circle cx="1080" cy="360" r="42" fill="${C.mint}"/>`+icon('check',1055,335,50,C.green)+txt(1142,354,'Draft ready for review',33,C.ink,500)+txt(1142,393,b?'REP-3091 · Summit Bottle':'REP-2048 · Trail Mug',20,C.muted)+line(1030,439,1845,439)+txt(1030,490,'REPLACEMENT DETAILS',14,C.muted,600,'letter-spacing="1.5"');
      [['Order',order],['Replacement item',b?'Summit Bottle':'Trail Mug'],['Customer',privateToken('NAME')],['Destination',privateToken('ADDRESS')]].forEach((r,k)=>{z+=txt(1030,543+k*65,r[0],20,C.muted)+txt(1412,543+k*65,r[1],22,k>1?C.green:C.ink,500)+line(1030,565+k*65,1845,565+k*65);});
      z+=pill(1030,821,218,'Local draft only',C.green,C.mint,'check')+txt(1280,846,'Nothing purchased or sent',18,C.muted)+txt(1030,911,'Illustrated result for the scripted walkthrough',16,C.muted);
      return z;
    }
    return skillPane(i);
  }
  function skillPane(i){
    let z=rect(996,149,882,794,'#f9fbfa',16,C.line)+rect(997,150,880,79,'#fff',16)+rect(997,201,880,27,'#fff')+icon('file',1027,175,27,C.green)+txt(1070,199,'replacement-workflow / SKILL.md',22,C.ink,500)+pill(1690,169,158,i===6?'Extracting':'Candidate',i===6?C.muted:C.green,i===6?C.light:C.mint)+line(996,228,1878,228);
    z+=txt(1045,291,'REUSABLE PROCEDURE',14,C.muted,600,'letter-spacing="1.8"')+lines(1045,345,['Prepare a replacement','from a support ticket'],33,C.ink,500,43)+txt(1045,454,'Inputs are bound again for each run.',21,C.muted);
    const rs=[['01','Read the current order','Use the order reference from the new ticket.'],['02','Match the replacement item','Select the item before preparing the draft.'],['03','Use the current shipping destination','Resolve a fresh private reference locally.'],['04','Prepare and check the draft','Check the order, item, and destination.']];
    rs.forEach((r,k)=>z+=`<g class="skill-row" style="animation-delay:${k*.25}s">${txt(1046,533+k*86,r[0],17,'#92aaa2',500)}${txt(1095,533+k*86,r[1],22,C.ink,500)}${txt(1095,565+k*86,r[2],18,C.muted)}</g>`);
    z+=line(1045,856,1828,856)+icon('shield',1045,880,22,C.green)+txt(1081,900,'Procedure only. Private records stay local.',20,C.green,500);
    return z;
  }
  function conversation(i){
    if(i<=1)return mark(271,245,53)+lines(268,367,['What can I take','off your plate?'],48,C.ink,500,59)+composer(i,true)+pill(266,695,190,'Private by default',C.green,C.mint,'shield')+txt(267,793,'CONNECTED',13,C.muted,600,'letter-spacing="1.6"')+icon('grid',268,821,24,C.muted)+txt(307,842,'Northstar support',20,C.ink)+txt(267,902,'You decide the task. PLVA protects the view.',19,C.muted);
    let z=userBubble(i);
    if(i===2){z+=agentHead('Working on your replacement')+step(399,'Reading the support ticket','active')+step(478,'Protecting customer details','pending')+step(557,'Preparing the draft','pending')+txt(316,675,'Activity preview',16,C.muted);}
    if(i===3){z+=agentHead('Customer details stay on this device')+step(399,'Read the support ticket')+step(478,'Protected the customer fields')+step(557,'Sending the protected view','active')+rect(268,640,641,117,'#f2faf7',12)+icon('shield',289,663,27,C.green)+txt(333,683,'Astra sees tokens, not contact details.',20,C.green,500)+txt(291,721,'The local workspace keeps the original values.',18,C.muted);}
    if(i===4){z+=agentHead('Preparing the replacement')+step(399,'Matched order ORD-2048')+step(478,'Selected the replacement item')+step(557,'Filling the shipping destination','active')+txt(316,638,'Using the current field labels and private tokens.',18,C.muted)+pill(269,706,235,'Values resolved locally',C.green,C.mint,'lock');}
    if(i===5){z+=agentHead('Your replacement draft is ready')+step(399,'Order matches the ticket')+step(464,'Replacement item selected')+step(529,'Shipping destination matched')+rect(268,606,641,135,'#f6f8f8',13)+txt(291,645,'Save this workflow as a skill?',23,C.ink,500)+txt(291,681,'Keep the procedure for the next replacement.',19,C.muted)+rect(706,686,178,38,C.ink,9)+txt(730,712,'Create skill',17,'#fff',500);}
    if(i===6){z+=agentHead('Learning the workflow')+step(402,'Collecting completed steps')+step(489,'Linking the source evidence')+step(576,'Replacing run-specific inputs','active')+lines(316,673,['Keeping the procedure.','Leaving private records behind.'],24,C.ink,500,37);}
    if(i===7){z+=agentHead('A procedure you can inspect')+lines(269,415,['The important rule:'],22,C.muted)+rect(268,447,641,155,'#eaf7f1',12)+lines(293,491,['Choose the replacement item','before preparing the draft.'],29,C.green,500,41)+txt(269,659,'Fresh inputs on every run',23,C.ink,500)+txt(269,701,'Order reference · item · protected destination',19,C.muted)+pill(270,754,248,'Evidence-linked candidate',C.green,C.mint,'file');}
    if(i===8){z+=agentHead('Ready for a different customer')+pill(269,381,256,'Replacement skill attached',C.green,C.mint,'file')+lines(269,483,['New order.','New customer.','Different form layout.'],36,C.ink,500,58)+txt(269,727,'A fresh session with fresh private references.',20,C.muted);}
    if(i===9){z+=agentHead('Using the saved procedure')+step(399,'Loaded the replacement skill')+step(478,'Matched the new form labels')+step(557,'Preparing order ORD-3091','active')+rect(268,649,641,116,'#f2faf7',12)+icon('repeat',289,675,26,C.green)+txt(333,697,'Same procedure. Fresh inputs.',24,C.green,500)+txt(290,735,'Actions follow the current screen.',19,C.muted);}
    if(i===10){z+=agentHead('The new replacement is ready')+step(399,'New order: ORD-3091')+step(478,'New item: Summit Bottle')+step(557,'New destination matched')+lines(270,676,['The procedure carries over.','The private records don’t.'],31,C.ink,500,47);}
    if(i===11){z+=mark(265,340,66)+lines(267,495,['Your work becomes','reusable knowledge.'],44,C.ink,500,61)+txt(269,668,'Private computer use with GPT-6 Astra.',23,C.muted)+pill(269,738,204,'PLVA / Hackathon',C.green,C.mint);}
    return z+(i===11?'':composer(i));
  }
  function svg(index){
    const i=Math.max(0,Math.min(scenes.length-1,index));
    return `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080" role="img" aria-labelledby="screen-title" style="font-family:'Segoe UI',Arial,sans-serif"><title id="screen-title">${esc(scenes[i].title)} — scripted PLVA demo</title><rect width="1920" height="1080" fill="#fff"/>${chrome(i)}<g class="conversation">${conversation(i)}</g><g class="workspace">${workspace(i)}</g></svg>`;
  }
  root.PLVA={scenes,svg};
  if(typeof module!=='undefined')module.exports=root.PLVA;
})(typeof window!=='undefined'?window:globalThis);
