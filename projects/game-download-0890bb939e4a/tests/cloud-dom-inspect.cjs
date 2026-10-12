const fs=require('node:fs');const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const page=await browser.newPage();await page.goto('https://yun.139.com/shareweb/#/w/i/2ygb6EhpGuPti',{waitUntil:'domcontentloaded'});await page.getByText('P5248',{exact:true}).first().dblclick();await page.locator('.touch-div span').filter({hasText:'PC-官中.exe'}).waitFor();
 await page.locator('.document_table_list_hover').first().hover();
 const data=await page.evaluate(()=>{
  const item=[...document.querySelectorAll('.touch-div span')].find(e=>e.textContent==='PC-官中.exe');
  const ancestors=[];for(let n=item,i=0;n&&i<6;n=n.parentElement,i++)ancestors.push({tag:n.tagName,cls:n.className,html:n.outerHTML.slice(0,9000)});
  return {ancestors,checkboxes:[...document.querySelectorAll('input[type=checkbox],[role=checkbox],.el-checkbox,[class*=check]')].map(n=>({cls:n.className,html:n.outerHTML.replace(/src="data:[^"]*"/g,'src="omitted"')})),row:item.closest('.document_table_list_hover').parentElement.outerHTML.replace(/src="data:[^"]*"/g,'src="omitted"'),downloads:[...document.querySelectorAll('span,button,a')].filter(n=>n.textContent.trim()==='下载').map(n=>({html:n.outerHTML,parent:n.parentElement.outerHTML.slice(0,5000)}))};
 });fs.writeFileSync('docs/cloud-checkbox-dom.json',JSON.stringify(data,null,2));
 const urls=await page.evaluate(()=>performance.getEntriesByType('resource').map(e=>e.name).filter(u=>/\.js(?:\?|$)/.test(u)));
 const snippets=[];
 for(const url of [...new Set(urls)]){const response=await page.request.get(url);const script=await response.text();for(const needle of ['document_table_list_check_hover','document_table_header_check','已选择']){const index=script.indexOf(needle);if(index>=0)snippets.push({url,needle,text:script.slice(Math.max(0,index-900),index+1800)});}}
 fs.writeFileSync('docs/cloud-checkbox-source.json',JSON.stringify(snippets,null,2));console.log(JSON.stringify(snippets));
}finally{await browser.close();}})().catch(e=>{console.error(e.message);process.exitCode=1;});
