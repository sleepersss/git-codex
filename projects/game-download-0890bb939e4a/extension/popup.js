const $=id=>document.getElementById(id);
const send=message=>chrome.runtime.sendMessage(message).then(r=>{if(r?.ok===false)throw new Error(r.error);return r;});
let draft;
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
async function refresh(){const s=await send({type:'STATE'});draft=s.draft;if(draft){$('draft').hidden=false;$('title').value=draft.title;$('category').textContent=draft.category;$('summary').textContent=`介绍 ${draft.text.length} 字 · ${draft.imageUrls.length} 张图片`;}}
$('choose').onclick=async()=>{try{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});await chrome.scripting.executeScript({target:{tabId:tab.id},files:['core.js','capture.js']});await chrome.tabs.sendMessage(tab.id,{type:'CHOOSE'});window.close();}catch(e){status('当前页面无法选择游戏：'+e.message,true);}};
$('start').onclick=async()=>{
 $('start').disabled=true;
 try{
  const origins=[...new Set((draft?.imageUrls||[]).map(url=>new URL(url).origin+'/*'))];
  // Request only the selected card's image hosts, within the click gesture.
  if(origins.length && !await chrome.permissions.request({origins}))status('图片权限未允许，仍保存文字；图片失败会记录。');
  await send({type:'START',title:$('title').value.trim()});status('已加入任务，将在后台打开云盘并选择 PC 包。');
 }catch(e){status(e.message,true);}finally{$('start').disabled=false;}
};
$('settings').onclick=()=>chrome.runtime.openOptionsPage();
$('tasks').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('tasks.html')});
refresh().catch(e=>status(e.message,true));
