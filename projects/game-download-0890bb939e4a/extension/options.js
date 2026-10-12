const $=id=>document.getElementById(id);
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
async function send(message){const r=await chrome.runtime.sendMessage(message);if(r?.ok===false)throw new Error(r.error);return r;}
async function saveSettings(){try{await send({type:'SETTINGS',settings:{root:$('root').value.trim(),password:$('password').value,sevenZip:$('sevenZip').value.trim(),autoHandle:$('autoHandle').checked,downloadMode:$('downloadMode').value,idmFolder:$('idmFolder').value.trim(),deleteArchive:$('deleteArchive').checked}});status('设置已保存');}catch(e){status(e.message,true);}}
$('save').onclick=saveSettings;$('saveDownload').onclick=saveSettings;
$('ping').onclick=async()=>{try{const r=await send({type:'PING'});status('助手已连接 · 版本 '+r.version);}catch(e){status('助手未连接：'+e.message,true);}};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(chrome.runtime.id);status('插件 ID 已复制');}catch(e){status('请选中插件 ID 手动复制',true);}};
send({type:'STATE'}).then(s=>{for(const k of ['root','password','sevenZip','idmFolder'])$(k).value=s.settings[k]||'';$('downloadMode').value=s.settings.downloadMode||'idm';$('deleteArchive').checked=s.settings.deleteArchive!==false;$('autoHandle').checked=s.settings.autoHandle!==false;$('extensionId').textContent=s.extensionId;}).catch(e=>status(e.message,true));
