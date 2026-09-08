const fs=require('node:fs/promises');
const path=require('node:path');
const {scenes,svg}=require('./scenes.js');
const sharp=require(process.env.PLVA_SHARP_PATH||'sharp');
(async()=>{
  await fs.mkdir(path.join(__dirname,'images'),{recursive:true});
  await fs.mkdir(path.join(__dirname,'editable'),{recursive:true});
  const results=[];
  for(let i=0;i<scenes.length;i++){
    const name=String(i+1).padStart(2,'0')+'-'+scenes[i].id;
    const source=svg(i);
    await fs.writeFile(path.join(__dirname,'editable',name+'.svg'),source);
    await sharp(Buffer.from(source),{density:144}).resize(3840,2160).png().toFile(path.join(__dirname,'images',name+'.png'));
    results.push({scene:i+1,name,width:3840,height:2160,duration:scenes[i].duration});
  }
  const css=(await fs.readFile(path.join(__dirname,'index.html'),'utf8'));
  const standalone=css.replace('<script src="scenes.js"></script>',`<script>${await fs.readFile(path.join(__dirname,'scenes.js'),'utf8')}</script>`).replace('<script src="player.js"></script>',`<script>${await fs.readFile(path.join(__dirname,'player.js'),'utf8')}</script>`);
  await fs.writeFile(path.join(__dirname,'PLVA-DEMO.html'),standalone);
  await fs.writeFile(path.join(__dirname,'images','manifest.json'),JSON.stringify({total_seconds:scenes.reduce((s,x)=>s+x.duration,0),scenes:results},null,2));
  const thumbs=await Promise.all(scenes.map((_,i)=>sharp(path.join(__dirname,'images',results[i].name+'.png')).resize(640,360).toBuffer()));
  await sharp({create:{width:1920,height:1440,channels:3,background:'#152124'}}).composite(thumbs.map((input,i)=>({input,left:i%3*640,top:Math.floor(i/3)*360}))).png().toFile(path.join(__dirname,'STORYBOARD.png'));
  console.log(JSON.stringify({images:results.length,resolution:'3840x2160',seconds:60,standalone:path.join(__dirname,'PLVA-DEMO.html')},null,2));
})().catch(e=>{console.error(e);process.exitCode=1});
