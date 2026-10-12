(function(root) {
 const categories = ['ACT','ADV','GAL','RPG','SLG'];
 function parseTitle(text) {
  const match = String(text).match(/【([^】]+)】\s*([\s\S]+?)(?=\n\s*\n|$)/);
  if (!match) throw new Error('未找到【类型】游戏标题，请点击完整介绍卡片');
  const category = match[1].split(/[\/／\s]/)[0].toUpperCase();
  if (!categories.includes(category)) throw new Error('未知游戏类型：' + category);
  const title = match[2].replace(/\s*\n\s*/g,' ').replace(/[（(]\s*PC(?:\s*[\/／]\s*[^（）()]*)?\s*[）)]/ig,'').trim();
  if (!title) throw new Error('游戏名为空');
  return {category,title};
 }
 function selectPC(names) {
  const candidates = [...new Set(names)].filter(n=>/(?:\bPC\b|PC[-_]|windows|电脑版)/i.test(n) && !/(安卓|android|\.apk\b)/i.test(n) && /\.(exe|7z|zip|rar)(?:\s|$)/i.test(n));
  if (candidates.length > 1) throw new Error('发现多个 PC 包，请手动选择后再关联下载');
  if (!candidates.length) throw new Error('未找到唯一 PC 压缩包');
  return candidates[0];
 }
 function isShare(url) {
  try {const u=new URL(url); return u.protocol==='https:' && u.hostname==='yun.139.com' && u.pathname==='/shareweb/' && /^#\/w\/i\/[A-Za-z0-9]+$/.test(u.hash);} catch {return false;}
 }
 function sameFilename(path,expected) {
  const name=String(path||'').split(/[\\/]/).pop();
  return name===expected || name.replace(/ \(\d+\)(?=\.[^.]+$)/,'')===expected;
 }
 function matchesDownload(item,job) {
  const provenance=(job.networkUrls||[]).some(url=>url===item.url||url===item.finalUrl);
  return provenance && sameFilename(item.filename,job.expected) && Date.now()-job.armedAt<60000;
 }
 async function hashURL(url) {
  const u=new URL(url);
  const encode=value=>encodeURIComponent(value).replace(/[!'()*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase()).replace(/%20/g,'+');
  const pairs=[...u.searchParams.entries()].sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:a[1]<b[1]?-1:a[1]>b[1]?1:0);
  const normalized=u.protocol+'//'+u.host+u.pathname+'?'+pairs.map(([k,v])=>encode(k)+'='+encode(v)).join('&');
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(normalized)))].map(n=>n.toString(16).padStart(2,'0')).join('');
 }
 const api={parseTitle,selectPC,isShare,sameFilename,matchesDownload,hashURL};
 if(typeof module!=='undefined') module.exports=api;
 root.GameCore=api;
})(globalThis);
