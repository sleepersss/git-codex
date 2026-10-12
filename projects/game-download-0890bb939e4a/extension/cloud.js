(() => {
 if(globalThis.gameCloudInstalled) return;
 globalThis.gameCloudInstalled=true;
 const visible = element=>!!(element.getClientRects().length && getComputedStyle(element).visibility!=='hidden');
 const names=()=>[...new Map([...document.querySelectorAll('.document_table_list_name_text .touch-div span,span.name-box,p.name-box,.item-name-text')].filter(visible).map(e=>[e.textContent.trim(),e])).values()];
 const fingerprint=rows=>rows.map(e=>e.textContent.trim()).join('\n');
 async function waitForRows(previous) {
  const deadline=Date.now()+20000;
  let stable='',stableSince=0;
  while(Date.now()<deadline){
   const rows=names();const next=fingerprint(rows);
   if(next && next!==previous){
    if(next!==stable){stable=next;stableSince=Date.now();}
    if(Date.now()-stableSince>=500)return rows;
   }else {stable='';stableSince=0;}
   await new Promise(r=>setTimeout(r,150));
  }
  throw new Error(previous?'文件夹已点击，但未读到更新后的文件列表，请检查分享页':'未读到云盘文件列表，请等待页面加载后重试');
 }
 function assertLogin() {
  if([...document.querySelectorAll('.login-mask')].some(visible))throw new Error('移动云盘需要登录，请在分享页完成登录后重试');
 }
 function selectedState(row,list) {
  const selected=[...list.querySelectorAll('.document_table_list_checked')].filter(visible);
  if(selected.some(check=>check.closest('.document_table_list,.document_table_list_hover')!==row))throw new Error('其他文件已选中，请取消其他勾选后重试');
  const header=list.querySelector('.document_table_header');
  const count=(header?.textContent||'').match(/已选择\s*(\d+)\s*项/);
  if(count && Number(count[1])>1)throw new Error('页面选中了多个文件，已停止下载');
  return selected.length===1 && selected[0].closest('.document_table_list,.document_table_list_hover')===row && count && Number(count[1])===1;
 }
 async function selectFile(item) {
  const row=item.closest('.document_table_list,.document_table_list_hover');
  const list=row?.closest('.main_file_list');
  if(!row || !list)throw new Error('未找到文件行复选框，请切换云盘列表视图后重试');
  const check=row.querySelector(':scope > .document_table_list_check,:scope > .document_table_list_check_hover,:scope > .document_table_list_checked');
  if(!check)throw new Error('未找到该PC文件左侧复选框');
  assertLogin();
  selectedState(row,list); // Reject unrelated selections before changing anything.
  if(!check.classList.contains('document_table_list_checked'))check.click();
  const deadline=Date.now()+5000;
  while(Date.now()<deadline){
   assertLogin();
   if(selectedState(row,list)) {
    const buttons=[...list.querySelectorAll('.document_table_header .fileName-button-two')].filter(e=>visible(e) && e.textContent.trim()==='下载');
    if(buttons.length===1)return {row,list,button:buttons[0]};
   }
   await new Promise(r=>setTimeout(r,150));
  }
  throw new Error('未确认“已选择1项”及选中工具栏下载按钮，未触发下载');
 }
 let observer;
 chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(message.type!=='AUTO_PC') return;
  (async()=>{
   let rows=await waitForRows('');
   // A single folder is common in this share service; enter it, at most three levels.
   for(let depth=0;depth<3 && rows.length===1 && !/\.(exe|7z|zip|rar|apk)$/i.test(rows[0].textContent.trim());depth++) {
    const previous=fingerprint(rows);
    rows[0].dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true,view:window,detail:2}));
    rows=await waitForRows(previous);
   }
   const filename=GameCore.selectPC(rows.map(e=>e.textContent.trim()));
   const item=rows.find(e=>e.textContent.trim()===filename);
   const stage=await chrome.runtime.sendMessage({type:'CLOUD_STAGE',jobId:message.jobId,note:'已找到PC包，正在勾选左侧复选框'});
   if(stage?.ok===false)throw new Error(stage.error);
   const selection=await selectFile(item);
   const armed=await chrome.runtime.sendMessage({type:'ARM',filename,jobId:message.jobId});
   if(armed?.ok===false)throw new Error(armed.error);
   assertLogin();
   if(!selectedState(selection.row,selection.list))throw new Error('下载前选中状态发生变化，已停止');
   selection.button.click();
   // Delayed login/client prompts remain visible for the user.
   observer?.disconnect();
   observer=new MutationObserver(()=>{
    if([...document.querySelectorAll('.login-mask')].some(visible)) chrome.runtime.sendMessage({type:'CLOUD_ERROR',jobId:message.jobId,error:'下载需要登录，请完成登录后重试'}).catch(()=>{});
   });
   observer.observe(document.body,{childList:true,subtree:true});
   respond({ok:true,filename,stage:'downloadRequested'});
  })().catch(error=>respond({ok:false,error:error.message}));
  return true;
 });
})();
