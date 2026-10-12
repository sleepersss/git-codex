const fs=require('node:fs');
const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 for(const id of ['7dCyjJoKY8ZrqR1y','GIcksxXcx0CRCCbv']){
 const page=await browser.newPage();
 await page.addInitScript({content:"globalThis.chrome={runtime:{onMessage:{addListener(){}},sendMessage:async()=>({ok:true})}};"+fs.readFileSync('extension/core.js','utf8')+fs.readFileSync('extension/capture.js','utf8')});
 await page.goto('https://sway.cloud.microsoft/'+id,{waitUntil:'domcontentloaded',timeout:45000});await page.waitForTimeout(7000);
 await page.evaluate(()=>{[...document.querySelectorAll('a[href]')].find(a=>GameCore.isShare(a.href))?.scrollIntoView({block:'center'});});await page.waitForTimeout(2000);
 const result=await page.evaluate(()=>{
 const links=[...document.querySelectorAll('a[href]')].filter(a=>GameCore.isShare(a.href));
 return {url:location.href,text:document.body.innerText.slice(0,1200),shareCount:links.length,cards:links.slice(0,8).map(a=>{try{const m=gameCaptureFromElement(a);return {title:m.title,category:m.category,images:m.imageUrls.length,textLength:m.text.length,share:m.share};}catch(e){return {error:e.message,ancestors:[...function*(n){for(let i=0;n&&i<7;i++,n=n.parentElement)yield {tag:n.tagName,cls:n.className,text:n.innerText?.slice(0,160)};}(a)]};}})};});
 const structure=await page.evaluate(()=>{
  const a=[...document.querySelectorAll('a[href]')].find(a=>GameCore.isShare(a.href));const rows=[];
  for(let n=a;n&&n!==document.body;n=n.parentElement) rows.push({tag:n.tagName,id:n.id,cls:n.className,titles:(n.innerText?.match(/【(?:ACT|SLG|RPG)/g)||[]).length,links:[...n.querySelectorAll('a[href]')].filter(a=>GameCore.isShare(a.href)).length,imgs:n.querySelectorAll('img').length,imageRoles:n.querySelectorAll('[role=img]').length,backgrounds:[...n.querySelectorAll('[style]')].filter(e=>e.style.backgroundImage).slice(0,4).map(e=>({cls:e.className,bg:e.style.backgroundImage})),children:[...n.children].slice(0,6).map(e=>({tag:e.tagName,cls:e.className,text:e.innerText?.slice(0,80)}))});
  return rows;
 });
 fs.writeFileSync('docs/site-'+id+'.json',JSON.stringify({...result,structure},null,2));console.log(JSON.stringify({id,shareCount:result.shareCount,cards:result.cards}));await page.screenshot({path:'docs/site-'+id+'.png'});await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e.message);process.exitCode=1;});
