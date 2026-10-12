const fs=require('node:fs');const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const page=await browser.newPage();
 await page.addInitScript({content:"globalThis.chrome={runtime:{onMessage:{addListener(fn){globalThis.cloudHandler=fn;}},sendMessage:async message=>{if(message.type==='CLOUD_STAGE')return {ok:true};if(message.type==='ARM'){globalThis.detectedPC=message.filename;return {ok:false,error:'PROBE_STOP_BEFORE_DOWNLOAD'};}throw new Error('Unexpected side effect');}}};"+fs.readFileSync('extension/core.js','utf8')+fs.readFileSync('extension/cloud.js','utf8')});
 await page.goto('https://yun.139.com/shareweb/#/w/i/2ygb6EhpGuPti',{waitUntil:'domcontentloaded',timeout:45000});
 const result=await page.evaluate(()=>new Promise(resolve=>cloudHandler({type:'AUTO_PC',jobId:'safe-probe'},null,resolve)));
 assert.equal(result.error,'PROBE_STOP_BEFORE_DOWNLOAD',result.error);assert.equal(await page.evaluate(()=>detectedPC),'PC-官中.exe');
 assert.equal(await page.locator('.document_table_list_checked').count(),1);assert.match(await page.locator('.document_table_header').innerText(),/已选择\s*1\s*项/);
 assert.equal(await page.locator('.document_table_header .fileName-button-two:visible').filter({hasText:'下载'}).count(),1);
 console.log('PASS: 实际P5248页面进入目录、勾选PC、确认已选择1项和专用下载按钮；点击下载前停止');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
