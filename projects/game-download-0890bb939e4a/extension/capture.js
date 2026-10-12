(() => {
 if (globalThis.gameCaptureInstalled) return;
 globalThis.gameCaptureInstalled=true;
 function capture(element) {
  let selectedNodes=[];
  // Sway renders each column as independent siblings in one long list.
  if(document.getElementById('storyroot')) {
   for(let parent=element.parentElement;parent && parent!==document.body;parent=parent.parentElement){
    const children=[...parent.children];const index=children.findIndex(n=>n===element||n.contains(element));
    if(index<0 || children.length<3 || children.filter(n=>/【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/i.test(n.innerText||'')).length<2)continue;
    let current=index;
    const own=children[current];
    if(!/【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/i.test(own.innerText||'')) {
     const previous=children[current-1];
     const next=children[current+1];
     if(own.classList.contains('cursorPointer') && !(own.innerText||'').trim() && next && /【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/i.test(next.innerText||''))selectedNodes=[own,next];
     else if(previous && /【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/i.test(previous.innerText||''))selectedNodes=[previous,own];
    }else {
     selectedNodes=[own];
     const previous=children[current-1];
     if(previous && !(previous.innerText||'').trim() && previous.classList.contains('cursorPointer'))selectedNodes.unshift(previous);
     if(![...own.querySelectorAll('a[href]')].some(a=>GameCore.isShare(a.href)) && children[current+1])selectedNodes.push(children[current+1]);
    }
    if(selectedNodes.length)break;
   }
  }
  let candidate=null;
  for(let node=element; node && node!==document.body; node=node.parentElement) {
   const text=node.innerText||'';
   const titles=text.match(/【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/ig)||[];
   const links=[...node.querySelectorAll('a[href]')].map(a=>a.href).filter(GameCore.isShare);
   if(titles.length===1 && links.length===1) candidate=node;
   if(candidate && titles.length>1) break;
  }
  if(!selectedNodes.length && candidate)selectedNodes=[candidate];
  if(!selectedNodes.length) throw new Error('未找到游戏标题和移动云盘链接，请点击游戏正文');
  const text=selectedNodes.map(n=>n.innerText||'').join('\n\n');
  const headings=selectedNodes.flatMap(n=>[...n.querySelectorAll('p,h1,h2,h3')]).filter(n=>/【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/i.test(n.textContent||''));
  const titleText=headings.length===1?headings[0].textContent:text;
  const parsed=GameCore.parseTitle(titleText);
  const images=selectedNodes.flatMap(n=>[...n.querySelectorAll('img')]).filter(i=>i.naturalWidth>=120 || i.width>=120).map(i=>i.currentSrc||i.src).filter(u=>/^https:\/\//.test(u));
  const links=[...new Set(selectedNodes.flatMap(n=>[...n.querySelectorAll('a[href]')]).map(a=>a.href).filter(GameCore.isShare))];
  if(links.length!==1 || (text.match(/【(?:ACT|ADV|GAL|RPG|SLG)[^】]*】/ig)||[]).length!==1)throw new Error('卡片包含多个游戏或分享链接，请重新选择');
  if(selectedNodes.some(n=>n.classList.contains('cursorPointer')) && !images.length)throw new Error('该游戏图片尚未加载，请先滚动让左侧图片显示，再点击下载链接');
  return {...parsed,text:text.slice(0,100000),source:location.href,share:links[0],imageUrls:[...new Set(images)].slice(0,30)};
 }
 globalThis.gameCaptureFromElement=capture;
 let choosing=false;
 let banner;
 function stop() {choosing=false; banner?.remove(); banner=null;}
 chrome.runtime.onMessage.addListener(message=>{
  if(message.type==='CHOOSE') {
   stop(); choosing=true;
   banner=document.createElement('div');
   banner.textContent='请点击要下载的游戏介绍卡片 · Esc 取消';
   Object.assign(banner.style,{position:'fixed',top:'14px',left:'50%',transform:'translateX(-50%)',zIndex:'2147483647',background:'#173b37',color:'white',padding:'16px 24px',borderRadius:'10px',font:'16px sans-serif',boxShadow:'0 4px 20px #0005'});
   document.body.append(banner);
  }
 });
 document.addEventListener('keydown',e=>{if(e.key==='Escape')stop();});
 document.addEventListener('click',async e=>{
  // A stale listener must not swallow normal clicks after extension reload.
  try {if(!chrome.runtime.id)return;}catch{return;}
  const link=e.target.closest?.('a[href]');
  if(!choosing && link && GameCore.isShare(link.href) && e.isTrusted && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button===0) {
   e.preventDefault();e.stopImmediatePropagation();
   try {const metadata=capture(link);const result=await chrome.runtime.sendMessage({type:'CAPTURE_START',metadata});if(result?.ok===false)throw new Error(result.error);if(result?.disabled)location.href=link.href;}
   catch(error){alert('自动下载未开始：'+error.message+'\n请打开插件检查设置。');}
   return;
  }
  if(!choosing || e.target===banner) return;
  e.preventDefault(); e.stopImmediatePropagation();
  try {const metadata=capture(e.target); await chrome.runtime.sendMessage({type:'CAPTURE',metadata}); stop(); alert('已读取：'+metadata.title+'\n请打开插件，检查名称后点击“下载并归档”。');}
  catch(error) {alert(error.message);}
 },true);
})();
