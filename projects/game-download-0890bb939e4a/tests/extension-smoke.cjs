const fs=require('node:fs');const path=require('node:path');
const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const profile=fs.mkdtempSync(path.resolve('tests/profile-'));const extension=path.resolve('extension');const context=await chromium.launchPersistentContext(profile,{executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,args:['--disable-extensions-except='+extension,'--load-extension='+extension],ignoreDefaultArgs:['--disable-extensions']});try{
 const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker',{timeout:10000});
 const state=await worker.evaluate(async()=>({id:chrome.runtime.id,manifest:chrome.runtime.getManifest().name,stateType:typeof state,local:await chrome.storage.local.get(null)}));
 console.log('EXTENSION_LOADED',JSON.stringify(state));
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('chrome-extension://'+state.id+'/options.html');await page.waitForTimeout(1000);console.log('OPTIONS_STATUS',await page.locator('#status').innerText());const root=await page.locator('#root').inputValue();console.log('OPTIONS_ROOT',root);if(!root)throw new Error('实际插件设置未加载');if(errors.length)throw new Error(errors.join('\n'));
 console.log('PASS: Edge实际加载插件与设置页');
 const idmFolder=await page.locator('#idmFolder').inputValue();if(idmFolder!=='D:\\8_Temporary files\\IDM\\programs')throw new Error('IDM目录默认值不正确');
 if(await page.locator('#downloadMode').inputValue()!=='idm' || !await page.locator('#deleteArchive').isChecked())throw new Error('IDM接入与清理默认值不正确');
 console.log('PASS: 实际设置页默认IDM目录与成功后清理开关');
 const share='https://yun.139.com/shareweb/#/w/i/closefixture';
 await context.route('https://yun.139.com/shareweb/',route=>route.fulfill({contentType:'text/html',body:'<h1>share fixture</h1>'}));
 const tabId=await worker.evaluate(async share=>{
  const tab=await chrome.tabs.create({url:share,active:false});
  const job={id:'close-fixture',status:'processing',tabId:tab.id,ownsShareTab:true,metadata:{share}};
  await chrome.storage.local.set({jobs:[job]});return tab.id;
 },share);
 await new Promise(r=>setTimeout(r,150));
 const closed=await worker.evaluate(async tabId=>{
  const {jobs}=await chrome.storage.local.get('jobs');await closeCompletedShareTab(jobs[0]);
  try{await chrome.tabs.get(tabId);return false;}catch{return true;}
 },tabId);
 if(!closed)throw new Error('已完成任务的实际云盘标签未关闭');
 await worker.evaluate(()=>chrome.storage.local.set({jobs:[]}));
 console.log('PASS: 实际Edge关闭本任务的移动云盘分享标签');
 await context.route('https://sway.cloud.microsoft/reload-fixture',route=>route.fulfill({contentType:'text/html',body:'<h1>fixture</h1>'}));
 const sway=await context.newPage();await sway.goto('https://sway.cloud.microsoft/reload-fixture');
 const refreshed=sway.waitForEvent('framenavigated',{predicate:frame=>frame===sway.mainFrame(),timeout:15000});
 await worker.evaluate(()=>chrome.runtime.reload()).catch(()=>{});
 await refreshed;
 console.log('PASS: 实际扩展重载后自动刷新已打开的Sway页面');
 if(process.argv.includes('--native')){await page.locator('#ping').click();await page.waitForFunction(()=>document.getElementById('status').textContent.includes('助手已连接')||document.getElementById('status').textContent.includes('助手未连接'));const message=await page.locator('#status').innerText();console.log('NATIVE_PING',message);if(!message.includes('助手已连接'))throw new Error(message);}
}finally{await context.close();fs.rmSync(profile,{recursive:true,force:true});}})().catch(e=>{console.error(e.message);process.exitCode=1;});
