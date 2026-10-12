const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const core=require('../extension/core.js');
function environment(jobs) {
 let stored={jobs,settings:{root:'E:\\games',password:'secret',sevenZip:'7z.exe'}};
 let download={id:1,state:'complete',filename:'D:\\PC中文.exe',referrer:'https://yun.139.com/shareweb/'};
 const listeners={};let archiveCalls=0;
 const event=name=>({addListener:fn=>{listeners[name]=fn;}});
 const chrome={
  storage:{local:{get:async()=>structuredClone(stored),set:async patch=>{stored={...stored,...structuredClone(patch)};}}},
  runtime:{id:'test',onMessage:event('message'),onStartup:event('startup'),onInstalled:event('installed'),getPlatformInfo:async()=>({}),connectNative:()=>{
   let onMessage,onDisconnect;return {onMessage:{addListener:fn=>onMessage=fn},onDisconnect:{addListener:fn=>onDisconnect=fn},disconnect(){onDisconnect?.();},postMessage(request){if(request.action==='archive')archiveCalls++;setTimeout(()=>onMessage(request.action==='archive'?{ok:true,path:'E:\\games\\SLG\\测试',format:'7z',imageErrors:[]}:{ok:true}),30);}};
  }},
  tabs:{onUpdated:event('tabUpdated'),onRemoved:event('tabRemoved'),create:async()=>({id:11}),get:async()=>({status:'loading'}),update:async()=>({})},
  downloads:{onCreated:event('created'),onDeterminingFilename:event('filename'),onChanged:event('changed'),search:async()=>[structuredClone(download)]},
  alarms:{onAlarm:event('alarm'),create:async()=>{},clear:async()=>true},permissions:{contains:async()=>true}
 };
 chrome.webRequest={onBeforeRequest:event('request'),onBeforeRedirect:event('redirect')};
 const context=vm.createContext({chrome,GameCore:core,importScripts(){},URL,Date,Promise,crypto:require('node:crypto').webcrypto,TextEncoder,setTimeout,setInterval,clearInterval,console,structuredClone});
 vm.runInContext(fs.readFileSync('extension/background.js','utf8'),context);
 return {context,listeners,setDownload(value){download=value;},get stored(){return stored;},get archiveCalls(){return archiveCalls;}};
}
test('重复完成事件只能归档一次',async()=>{
 const env=environment([{id:'job',downloadId:1,status:'downloading',expected:'PC中文.exe',metadata:{category:'SLG',title:'测试',imageUrls:[]}}]);
 await Promise.all([vm.runInContext('completeDownload(1)',env.context),vm.runInContext('completeDownload(1)',env.context)]);
 assert.equal(env.archiveCalls,1);assert.equal(env.stored.jobs[0].status,'done');
});
test('并发队列启动只打开一个任务',async()=>{
 const env=environment([{id:'1',status:'queued',metadata:{share:'https://yun.139.com/shareweb/#/w/i/abc'}},{id:'2',status:'queued',metadata:{share:'https://yun.139.com/shareweb/#/w/i/def'}}]);
 await Promise.all([vm.runInContext('pump()',env.context),vm.runInContext('pump()',env.context)]);
 assert.equal(env.stored.jobs.filter(j=>j.status==='opening').length,1);
 assert.equal(env.stored.jobs.filter(j=>j.status==='queued').length,1);
});
test('页面不能获取设置密码',async()=>{
 const env=environment([]);
 const reply=await new Promise(resolve=>env.listeners.message({type:'STATE'},{id:'test',tab:{id:9},url:'https://sway.cloud.microsoft/test'},resolve));
 assert.equal(reply.ok,false);assert.ok(!JSON.stringify(reply).includes('secret'));
});
test('扩展自己的设置标签可以读取设置',async()=>{
 const env=environment([]);
 const reply=await new Promise(resolve=>env.listeners.message({type:'STATE'},{id:'test',tab:{id:9},url:'chrome-extension://test/options.html'},resolve));
 assert.equal(reply.settings.root,'E:\\games');
});
test('拒绝重复归档请求且保留processing状态',async()=>{
 const env=environment([{id:'job',status:'processing',archive:'D:\\PC.exe'}]);
 const reply=await new Promise(resolve=>env.listeners.message({type:'RETRY_ARCHIVE',id:'job'},{id:'test'},resolve));
 await new Promise(r=>setTimeout(r,10));
 assert.equal(reply.ok,false);assert.equal(env.stored.jobs[0].status,'processing');
});
test('标签创建失败继续下一个队列任务',async()=>{
 const env=environment([{id:'1',status:'queued',metadata:{share:'a'}},{id:'2',status:'queued',metadata:{share:'b'}}]);
 vm.runInContext('chrome.tabs.create=async()=>{throw new Error("窗口不可用")}',env.context);
 await vm.runInContext('pump()',env.context);
 assert.deepEqual(env.stored.jobs.map(j=>j.status),['error','error']);
});
test('IDM等待任务阻止后续下载队列且不被Edge取消事件打断',async()=>{
 const env=environment([{id:'idm',status:'idm_waiting',idm:true,downloadId:null},{id:'queued',status:'queued',metadata:{share:'a'}}]);
 await vm.runInContext('pump()',env.context);
 assert.equal(env.stored.jobs[1].status,'queued');
 env.listeners.changed({id:1,state:{current:'interrupted'},error:{current:'USER_CANCELED'}});
 await new Promise(r=>setTimeout(r,10));assert.equal(env.stored.jobs[0].status,'idm_waiting');
});
test('旧设置自动补齐用户指定IDM目录且保留密码',async()=>{
 const env=environment([]);const result=await vm.runInContext('state()',env.context);
 assert.equal(result.settings.idmFolder,'D:\\8_Temporary files\\IDM\\programs');assert.equal(result.settings.downloadMode,'idm');assert.equal(result.settings.password,'secret');assert.equal(result.settings.deleteArchive,true);
});
test('IDM触发后的网页错误释放等待任务',async()=>{
 const env=environment([{id:'job',idm:true,status:'idm_waiting',tabId:9}]);
 const reply=await new Promise(resolve=>env.listeners.message({type:'CLOUD_ERROR',jobId:'job',error:'需要登录'},{id:'test',tab:{id:9},url:'https://yun.139.com/shareweb/'},resolve));
 assert.equal(reply.ok,true);assert.equal(env.stored.jobs[0].status,'error');
});
test('IDM下载来源只保存摘要',async()=>{
 const env=environment([{id:'job',idm:true,status:'idm_waiting',tabId:9,armedAt:Date.now()}]);
 await vm.runInContext("recordNetwork({tabId:9,url:'https://download.example/PC.exe?token=secret-signature'})",env.context);
 await vm.runInContext('lock',env.context);
 assert.equal(env.stored.jobs[0].networkHashes.length,1);assert.ok(!JSON.stringify(env.stored.jobs).includes('secret-signature'));
});

test('更新只刷新Sway介绍页以移除失效脚本',async()=>{
 const env=environment([]);const refreshed=[];
 env.context.chrome.tabs.query=async()=>[{id:10},{id:20}];
 env.context.chrome.tabs.reload=async id=>refreshed.push(id);
 await env.listeners.installed({reason:'update'});
 assert.deepEqual(refreshed,[10,20]);
});

for(const idm of [false,true])test((idm?'IDM':'Edge')+'下载完成后归档前关闭自己的分享页',async()=>{
 const share='https://yun.139.com/shareweb/#/w/i/testshare';
 const env=environment([{id:'job',idm,manualIDM:idm,status:'downloaded',archive:'D:\\PC.exe',tabId:9,ownsShareTab:true,metadata:{share,category:'SLG',title:'测试',imageUrls:[]}}]);
 const removed=[];env.context.chrome.tabs.get=async()=>({url:share});
 env.context.chrome.tabs.remove=async id=>{assert.equal(env.archiveCalls,0);removed.push(id);};
 await vm.runInContext("processArchive('job')",env.context);
 assert.deepEqual(removed,[9]);assert.equal(env.stored.jobs[0].status,'done');assert.equal(env.stored.jobs[0].tabId,null);
});
test('切换到其他网页的任务标签保留',async()=>{
 const env=environment([{id:'job',status:'downloaded',archive:'D:\\PC.exe',tabId:9,ownsShareTab:true,metadata:{share:'https://yun.139.com/shareweb/#/w/i/testshare',imageUrls:[]}}]);
 env.context.chrome.tabs.get=async()=>({url:'https://example.com/'});
 env.context.chrome.tabs.remove=async()=>{throw new Error('不应关闭其他网页');};
 await vm.runInContext("processArchive('job')",env.context);assert.equal(env.stored.jobs[0].status,'done');assert.equal(env.stored.jobs[0].tabId,9);
});
test('分享标签已被手动关闭也能继续归档',async()=>{
 const env=environment([{id:'job',status:'downloaded',archive:'D:\\PC.exe',tabId:9,ownsShareTab:true,metadata:{imageUrls:[]}}]);
 env.context.chrome.tabs.get=async()=>{throw new Error('标签不存在');};
 await vm.runInContext("processArchive('job')",env.context);assert.equal(env.stored.jobs[0].status,'done');
});

test('下载仍在进行时保留分享标签',async()=>{
 const env=environment([]);
 env.context.chrome.tabs.get=async()=>{throw new Error('不应读取未完成任务标签');};
 env.context.chrome.tabs.remove=async()=>assert.fail('下载完成前不能关闭');
 await vm.runInContext("closeCompletedShareTab({status:'idm_waiting',ownsShareTab:true,tabId:9})",env.context);
});
