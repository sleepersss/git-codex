const fs=require('node:fs');
const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const page=await browser.newPage();let share;
 for(const id of ['GIcksxXcx0CRCCbv','7dCyjJoKY8ZrqR1y']){
  await page.goto('https://sway.cloud.microsoft/'+id,{waitUntil:'domcontentloaded'});await page.waitForTimeout(5000);
  share=await page.evaluate(()=>{
   const title=[...document.querySelectorAll('p')].find(n=>(n.textContent||'').includes('妹系罗盘'));
   if(!title)return null;
   for(let n=title;n&&n!==document.body;n=n.parentElement){
    const shares=[...n.querySelectorAll('a[href]')].filter(a=>a.href.startsWith('https://yun.139.com/shareweb/'));
    if(shares.length===1)return shares[0].href;
    const next=n.nextElementSibling;const nextShares=next?[...next.querySelectorAll('a[href]')].filter(a=>a.href.startsWith('https://yun.139.com/shareweb/')):[];
    if(nextShares.length===1)return nextShares[0].href;
   }
   return null;
  });if(share)break;
 }
 if(!share)throw new Error('没有定位到截图对应游戏');
 console.log('SHARE',share);await page.goto(share,{waitUntil:'domcontentloaded'});await page.waitForTimeout(5000);
 async function snapshot(){return page.evaluate(()=>({text:document.body.innerText,rows:[...document.querySelectorAll('span.name-box,p.name-box,.item-name-text')].filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden').map(e=>({text:e.textContent.trim(),tag:e.tagName,cls:e.className,html:e.outerHTML})),matches:[...document.querySelectorAll('span,p,a,div')].filter(e=>e.children.length===0 && /^(?:P5248|PC-官中\.exe)$/.test(e.textContent.trim())).map(e=>({text:e.textContent,html:e.outerHTML,parent:e.parentElement.outerHTML.slice(0,4000)}))}));}
 let initial=await snapshot();console.log('INITIAL',JSON.stringify(initial));
 await page.getByText('P5248',{exact:true}).first().dblclick();await page.waitForTimeout(3000);
 let folder=await snapshot();console.log('FOLDER',JSON.stringify(folder));fs.writeFileSync('docs/cloud-p5248.json',JSON.stringify({share,initial,folder},null,2));
}finally{await browser.close();}})().catch(e=>{console.error(e.message);process.exitCode=1;});
