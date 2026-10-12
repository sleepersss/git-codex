importScripts('core.js');
const HOST='com.sleepersss.game_download';
const DEFAULTS={root:'E:\\1_Game\\some games',password:'',sevenZip:'D:\\1_Software\\50_routine\\RIME\\weasel-0.17.4\\7z.exe',autoHandle:true,downloadMode:'idm',idmFolder:'D:\\8_Temporary files\\IDM\\programs',deleteArchive:true};
const ACTIVE=['opening','armed','downloading','processing','idm_waiting'];
let lock=Promise.resolve();
const serial=fn=>{const result=lock.then(fn);lock=result.catch(()=>{});return result;};
async function state() {const saved=await chrome.storage.local.get(['jobs','settings','draft']);return {jobs:[],...saved,settings:{...DEFAULTS,...saved.settings}};}
async function update(id,patch) {return serial(async()=>{const {jobs}=await state(); const job=jobs.find(j=>j.id===id);if(job)Object.assign(job,patch,{updated:Date.now()});await chrome.storage.local.set({jobs});return job;});}
async function native(request,progress) {
 return new Promise((resolve,reject)=>{
  const port=chrome.runtime.connectNative(HOST);
  let done=false;
  port.onMessage.addListener(message=>{
   if(message.progress){progress?.(message.progress);return;}
   done=true;port.disconnect();message.ok?resolve(message):reject(new Error(message.error||'本地助手处理失败'));
  });
  port.onDisconnect.addListener(()=>{if(!done)reject(new Error(chrome.runtime.lastError?.message||'本地助手连接中断'));});
  port.postMessage(request);
 });
}
async function images(metadata) {
 const saved=[],errors=[];let total=0;
 for(const url of metadata.imageUrls||[]) {
  try {
   const parsed=new URL(url);
   if(parsed.protocol!=='https:') throw new Error('仅支持HTTPS图片');
   if(!await chrome.permissions.contains({origins:[parsed.origin+'/*']})) throw new Error('未授权图片域名');
   const response=await fetch(url,{credentials:'omit',signal:AbortSignal.timeout(20000)});
   const mime=(response.headers.get('content-type')||'').split(';')[0];
   if(!response.ok || !['image/png','image/jpeg','image/webp','image/gif'].includes(mime)) throw new Error('无法下载图片');
   const data=await response.arrayBuffer();
   if(data.byteLength>5*1024*1024 || total+data.byteLength>24*1024*1024) throw new Error('图片大小超过限制');
   total+=data.byteLength;
   let binary='';const bytes=new Uint8Array(data);
   for(let i=0;i<bytes.length;i+=8192) binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
   saved.push({mime,data:btoa(binary)});
  }catch(error){errors.push(url+'：'+error.message);}
 }
 return {...metadata,images:saved,imageErrors:errors};
}
async function closeCompletedShareTab(job) {
 if(job.status!=='processing' || !job.ownsShareTab || !Number.isInteger(job.tabId))return;
 try {
  const tab=await chrome.tabs.get(job.tabId);
  if(tab.url!==job.metadata.share || (tab.pendingUrl && tab.pendingUrl!==job.metadata.share))return;
  await chrome.tabs.remove(job.tabId);
  await update(job.id,{tabId:null,shareTabClosed:true});
 }catch{} // A closed or unavailable tab must not prevent archiving.
}
async function processArchive(id) {
 const job=await serial(async()=>{
  const {jobs}=await state();const current=jobs.find(j=>j.id===id);
  if(!current?.archive)throw new Error('还没有已完成的下载');
  if(current.status==='processing' || current.status==='done')throw new Error('任务已在处理或已完成');
  if(jobs.some(j=>j.id!==id && ACTIVE.includes(j.status)))throw new Error('另一个任务正在运行，请完成后重试');
  Object.assign(current,{status:'processing',note:'读取介绍图片',error:''});await chrome.storage.local.set({jobs});return current;
 });
 const keepalive=setInterval(()=>chrome.runtime.getPlatformInfo().catch(()=>{}),20000);
 try {
  await closeCompletedShareTab(job);
  const {settings}=await state();
  const metadata=await images(job.metadata);
  const operation=job.idm && job.watchToken && !job.manualIDM?'archive_idm':'archive';
  const result=await native({action:operation,token:job.watchToken,archive:job.archive,idm:!!job.idm,metadata,settings:{...settings,idmFolder:job.idmFolder||settings.idmFolder}},note=>update(id,{note}));
  await update(id,{status:'done',note:result.sourceDeleted?'游戏已归档并验证，本任务IDM源包已删除':'游戏已归档'+(result.cleanupWarning?'；'+result.cleanupWarning:''),path:result.path,format:result.format,imageErrors:result.imageErrors,sourceDeleted:!!result.sourceDeleted,cleanupWarning:result.cleanupWarning||''});
 }catch(error){await update(id,{status:'error',error:error.message,note:'归档失败，原下载包保留'});}
 finally {clearInterval(keepalive);await pump();}
}
async function autoPC(job) {
 const claimed=await serial(async()=>{const {jobs}=await state();const current=jobs.find(j=>j.id===job.id);if(current?.status!=='opening'||current.autoStarted)return false;current.autoStarted=true;await chrome.storage.local.set({jobs});return true;});
 if(!claimed)return;
 await chrome.scripting.executeScript({target:{tabId:job.tabId},files:['core.js','cloud.js']});
 const result=await chrome.tabs.sendMessage(job.tabId,{type:'AUTO_PC',jobId:job.id});
 if(!result?.ok) throw new Error(result?.error||'云盘页面未响应');
 const current=(await state()).jobs.find(j=>j.id===job.id);
 if(current?.idm){await update(job.id,{note:'已触发IDM下载，等待源包完成并落盘'});await pollIDM(job.id);}
 else {await update(job.id,{note:'已勾选PC包并点击工具栏下载；若Edge提示，请选择“保存”'});await chrome.alarms.create('download-'+job.id,{when:Date.now()+60000});}
}
async function pump() {
 const pending=(await state()).jobs.find(j=>j.status==='downloaded');
 if(pending){try{await processArchive(pending.id);}catch{}return;}
 const job=await serial(async()=>{const {jobs}=await state();if(jobs.some(j=>ACTIVE.includes(j.status)))return null;const next=jobs.find(j=>j.status==='queued');if(!next)return null;Object.assign(next,{status:'opening',note:'在后台打开云盘分享',autoStarted:false});await chrome.storage.local.set({jobs});return next;});
 if(!job)return;
 try {
  const tab=await chrome.tabs.create({url:job.metadata.share,active:false});
  await update(job.id,{tabId:tab.id,ownsShareTab:true});
  if((await chrome.tabs.get(tab.id)).status==='complete')await autoPC({...job,tabId:tab.id});
 }catch(error){await update(job.id,{status:'error',error:error.message});await pump();}
}
function recordNetwork(details) {
 serial(async()=>{
  const {jobs}=await state();const job=jobs.find(j=>j.tabId===details.tabId && ['armed','idm_waiting'].includes(j.status) && Date.now()-j.armedAt<300000);
  if(!job)return;
  const observed=[details.url,details.redirectUrl].filter(Boolean);
  if(job.idm){job.networkHashes=[...new Set([...(job.networkHashes||[]),...await Promise.all(observed.map(GameCore.hashURL))])].slice(-200);}
  else job.networkUrls=[...new Set([...(job.networkUrls||[]),...observed])].slice(-200);
  await chrome.storage.local.set({jobs});
 }).catch(()=>{});
}
chrome.webRequest.onBeforeRequest.addListener(recordNetwork,{urls:['https://*/*']});
chrome.webRequest.onBeforeRedirect.addListener(recordNetwork,{urls:['https://*/*']});
chrome.tabs.onUpdated.addListener((tabId,change)=>{
 if(change.status!=='complete')return;
 state().then(s=>s.jobs.find(j=>j.tabId===tabId && j.status==='opening')).then(async job=>{
  if(job)try{await autoPC(job);}catch(error){await update(job.id,{status:'error',error:error.message});await pump();}
 }).catch(()=>{});
});
chrome.tabs.onRemoved.addListener(tabId=>state().then(async s=>{
 for(const job of s.jobs.filter(j=>j.tabId===tabId && ['opening','armed'].includes(j.status))) await update(job.id,{status:'error',error:'分享标签已关闭，请重试下载'});
 await pump();
}));
chrome.alarms.onAlarm.addListener(alarm=>{
 if(alarm.name.startsWith('idm-')){pollIDM(alarm.name.slice(4)).catch(()=>{});return;}
 if(!alarm.name.startsWith('download-'))return;
 const id=alarm.name.slice(9);
 state().then(async s=>{const job=s.jobs.find(j=>j.id===id);if(job?.status==='armed'){await update(id,{status:'error',error:'未收到下载事件；请查看分享页是否要求客户端、登录或选择下载方式'});await chrome.tabs.update(job.tabId,{active:true}).catch(()=>{});await pump();}});
});
chrome.downloads.onCreated.addListener(item=>{
 bindAutomatic(item).catch(()=>{});
});
chrome.downloads.onDeterminingFilename.addListener((item,suggest)=>{
 suggest(); // Preserve the site's filename and normal browser conflict handling.
 bindAutomatic(item).catch(()=>{});
});
async function bindAutomatic(item) {
 await serial(async()=>{
  const {jobs}=await state();
  const job=jobs.find(j=>!j.idm && j.status==='armed' && GameCore.matchesDownload(item,j));
  if(!job)return;
  const observed=(item.filename||'').split(/[\\/]/).pop();
  // Early filenames can be empty. Reject only when an unrelated name is already known.
  if(observed && !GameCore.sameFilename(observed,job.expected)) {job.status='error';job.error='下载文件名与所选PC包不一致，拒绝归档';}
  else Object.assign(job,{downloadId:item.id,status:'downloading',note:'浏览器正在下载'});
  await chrome.storage.local.set({jobs});
 });
  // Catch files that completed before onCreated persisted the association.
  const [download]=await chrome.downloads.search({id:item.id});
  if(download?.state==='complete') await completeDownload(item.id);
}
async function completeDownload(downloadId) {
 const [download]=await chrome.downloads.search({id:downloadId});
 if(download?.state!=='complete')return;
 const job=await serial(async()=>{
  const {jobs}=await state();const current=jobs.find(j=>!j.idm && j.downloadId===downloadId && j.status==='downloading');if(!current)return null;
  if(!GameCore.sameFilename(download.filename,current.expected))Object.assign(current,{status:'error',error:'最终文件名与所选PC包不符，拒绝自动归档'});
  else Object.assign(current,{archive:download.filename,status:'downloaded',note:'下载完成'});
  await chrome.storage.local.set({jobs});return current;
 });
 if(!job)return;
 if(job.status==='error'){await pump();return;}
 await processArchive(job.id);
}
chrome.downloads.onChanged.addListener(delta=>{
 if(delta.filename)chrome.downloads.search({id:delta.id}).then(([item])=>item&&bindAutomatic(item)).catch(()=>{});
 if(delta.state?.current==='complete') completeDownload(delta.id).catch(()=>{});
 if(delta.state?.current==='interrupted')state().then(async s=>{const job=s.jobs.find(j=>!j.idm && j.downloadId===delta.id);if(job){await update(job.id,{status:'error',error:'下载中断：'+(delta.error?.current||'请检查下载列表')});await pump();}});
});
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
 (async()=>{
  if(sender.id!==chrome.runtime.id)throw new Error('消息来源不受支持');
  if(sender.tab && !sender.url?.startsWith('chrome-extension://'+chrome.runtime.id+'/')) {
   if(message.type==='CAPTURE' || message.type==='CAPTURE_START') {
    const m=message.metadata;
    if(!GameCore.isShare(m?.share)||!['ACT','ADV','GAL','RPG','SLG'].includes(m.category)||!m.title||m.source!==sender.url)throw new Error('介绍信息不完整');
    await chrome.storage.local.set({draft:m});
    if(message.type==='CAPTURE_START'){
     if(!(await state()).settings.autoHandle)return {ok:true,disabled:true};
     await startJob(m);
    }
    return {ok:true};
   }
   const {jobs}=await state();const job=jobs.find(j=>j.id===message.jobId && j.tabId===sender.tab.id && j.status!=='done');
   if(!job||!sender.url?.startsWith('https://yun.139.com/shareweb/'))throw new Error('未登记的云盘任务');
   if(message.type==='CLOUD_STAGE'){if(job.status!=='opening')throw new Error('任务状态不允许选择文件');await update(job.id,{note:String(message.note).slice(0,300)});return {ok:true};}
   if(message.type==='ARM') {
    if(job.status!=='opening')throw new Error('任务状态不允许下载');GameCore.selectPC([message.filename]);
    const {settings}=await state();const idm=settings.downloadMode==='idm';
    const watch=idm?await native({action:'prepare_idm',folder:settings.idmFolder,expected:message.filename,jobId:job.id}):null;
    await update(job.id,{status:idm?'idm_waiting':'armed',idm,idmFolder:settings.idmFolder,watchToken:watch?.token,manualIDM:false,expected:message.filename,armedAt:Date.now(),networkUrls:[],networkHashes:[],note:'已确认只勾选一个PC包，准备点击工具栏下载'});
    if(idm)await chrome.alarms.create('idm-'+job.id,{periodInMinutes:0.5});return {ok:true};
   }
   if(message.type==='HAS_DOWNLOAD')return {ok:true,started:['downloading','downloaded','processing'].includes(job.status)};
   if(message.type==='CLOUD_ERROR' && ['opening','armed','idm_waiting'].includes(job.status)){await chrome.alarms.clear('idm-'+job.id);await update(job.id,{status:'error',error:message.error});await pump();return {ok:true};}
   throw new Error('不支持的页面操作');
  }
  if(message.type==='STATE')return {...await state(),extensionId:chrome.runtime.id};
  if(message.type==='IDM_FILES'){
   const s=await state();const job=s.jobs.find(j=>j.id===message.id);if(!job?.expected)throw new Error('任务尚未识别PC文件名');
   return await native({action:'list_idm',folder:job.idmFolder||s.settings.idmFolder,expected:job.expected});
  }
  if(message.type==='BIND_IDM'){
   const s=await state();const job=s.jobs.find(j=>j.id===message.id);if(!job || !['error','idm_waiting'].includes(job.status))throw new Error('当前任务不能关联IDM文件');
   const candidates=await native({action:'list_idm',folder:job.idmFolder||s.settings.idmFolder,expected:job.expected});
   if(!candidates.files.some(f=>f.path===message.path))throw new Error('所选文件不属于本任务IDM目录或文件名不符');
   await chrome.alarms.clear('idm-'+job.id);await update(job.id,{idm:true,manualIDM:true,idmFolder:job.idmFolder||s.settings.idmFolder,archive:message.path,status:'downloaded',error:''});await pump();return {ok:true};
  }
  if(message.type==='RECENT_DOWNLOADS')return {ok:true,downloads:await chrome.downloads.search({state:'complete',limit:20,orderBy:['-startTime']})};
  if(message.type==='BIND_DOWNLOAD') {
   const job=(await state()).jobs.find(j=>j.id===message.id);
   if(!job || !['error','armed'].includes(job.status))throw new Error('任务状态不允许手动关联');
   const [download]=await chrome.downloads.search({id:Number(message.downloadId)});
   if(download?.state!=='complete'||download.exists===false)throw new Error('请选择已完成且仍存在的下载');
   await update(job.id,{archive:download.filename,downloadId:download.id,status:'downloaded',error:''});
   await pump();return {ok:true};
  }
  if(message.type==='PING')return await native({action:'ping'});
  if(message.type==='SETTINGS'){await chrome.storage.local.set({settings:message.settings});return {ok:true};}
  if(message.type==='START') {
   const s=await state();const metadata={...s.draft,title:message.title||s.draft?.title};
   if(!GameCore.isShare(metadata.share)||!metadata.title)throw new Error('请先选择一个游戏卡片');
   await startJob(metadata);return {ok:true};
  }
  if(message.type==='RETRY_ARCHIVE'){
   const job=(await state()).jobs.find(j=>j.id===message.id);
   if(!job?.archive || !['error','downloaded'].includes(job.status))throw new Error('任务正在处理或已完成，不能重复归档');
   processArchive(message.id).catch(()=>{});return {ok:true};
  }
  if(message.type==='RETRY_DOWNLOAD'){
   const job=(await state()).jobs.find(j=>j.id===message.id);if(!job||job.status!=='error'||job.archive)throw new Error('仅支持重试未完成下载的失败任务');
   await chrome.alarms.clear('idm-'+job.id);await update(job.id,{status:'queued',error:'',downloadId:null,archive:null,watchToken:null});await pump();return {ok:true};
  }
  throw new Error('未知请求');
 })().then(respond,error=>respond({ok:false,error:error.message}));
 return true;
});
async function startJob(metadata) {
 const host=await native({action:'ping'});if((await state()).settings.downloadMode==='idm' && !host.idm)throw new Error('本地助手尚未更新，请重试检查助手连接');
 await serial(async()=>{
  let {jobs}=await state();
  if(jobs.some(j=>j.metadata.share===metadata.share && !['done','error'].includes(j.status)))throw new Error('相同分享正在处理');
  if(jobs.length>=100){const index=jobs.findIndex(j=>j.status==='done');if(index<0)throw new Error('任务记录已满，请先处理未完成任务');jobs.splice(index,1);}
  jobs.push({id:crypto.randomUUID(),metadata,status:'queued',created:Date.now()});await chrome.storage.local.set({jobs});
 });
 await pump();
}
chrome.runtime.onStartup.addListener(()=>state().then(async s=>{
 for(const job of s.jobs){
  if(['processing','opening','armed'].includes(job.status))await update(job.id,{status:'error',error:'浏览器重启导致任务暂停，请检查目标后重试'});
  if(job.status==='idm_waiting'){await chrome.alarms.create('idm-'+job.id,{periodInMinutes:0.5});await pollIDM(job.id);}
  if(job.status==='downloading' && !job.idm) {const [d]=await chrome.downloads.search({id:job.downloadId});if(d?.state==='complete')await completeDownload(d.id);else if(!d||d.state==='interrupted')await update(job.id,{status:'error',error:'下载已中断'});}
 }
 await pump();
}));
const polling=new Set();
async function pollIDM(id){
 if(polling.has(id))return;polling.add(id);
 try{
  const job=(await state()).jobs.find(j=>j.id===id && j.status==='idm_waiting');if(!job)return;
  const result=await native({action:'poll_idm',token:job.watchToken,urlHashes:job.networkHashes||[]});
  if(result.ready){await chrome.alarms.clear('idm-'+id);await update(id,{archive:result.archive,status:'downloaded',note:'IDM完成已验证，准备解压'});await pump();}
  else await update(id,{note:result.note});
 }catch(e){await chrome.alarms.clear('idm-'+id);await update(id,{status:'error',error:e.message});await pump();}
 finally{polling.delete(id);}
}

// An extension update invalidates listeners still living in already open pages.
chrome.runtime.onInstalled.addListener(async details=>{
 if(!['install','update'].includes(details.reason))return;
 const tabs=await chrome.tabs.query({url:['https://sway.cloud.microsoft/*','https://sway.office.com/*','https://sway.com/*']});
 await Promise.allSettled(tabs.filter(tab=>Number.isInteger(tab.id)).map(tab=>chrome.tabs.reload(tab.id)));
});
