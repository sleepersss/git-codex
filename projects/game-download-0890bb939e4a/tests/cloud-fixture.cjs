const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 for(const config of [{name:'延迟目录进入后勾选PC',folder:true},{name:'PC已选中不反复切换',selected:true},{name:'其他文件已选中必须停止',otherSelected:true}]){
 const page=await browser.newPage();
 await page.setContent('<style>.name-box{visibility:hidden}</style><button id="wrong-download">下载</button><div class="main_file_list"><div class="document_table_header"><div class="table-col-item item-1"><span id="count">文件名</span><div class="fileName-button" hidden><div class="fileName-button-two"><span>下载</span></div></div></div></div><div id="files"></div></div><div id="preview" hidden>该类型文件暂不支持预览<button>下载</button></div>');
 await page.evaluate(config=>{
  globalThis.sent=[];globalThis.fileClicks=0;globalThis.downloadClicks=0;globalThis.wrongClicks=0;globalThis.checkboxClicks=0;
  globalThis.chrome={runtime:{onMessage:{addListener(fn){globalThis.handler=fn;}},sendMessage:async m=>{sent.push(m);return {ok:true,started:false};}}};
  const row=(name,selected)=>`<div class="document_table_list"><div class="${selected?'document_table_list_checked':'document_table_list_check'}"></div><div class="document_table_list_name_text"><div class="touch-div"><span>${name}</span></div><span class="name-box">${name}</span></div></div>`;
  function update(){const count=document.querySelectorAll('.document_table_list_checked').length;document.getElementById('count').textContent=count?`已选择 ${count} 项`:'文件名';document.querySelector('.fileName-button').hidden=!count;}
  function files(){document.getElementById('files').innerHTML=row('PC-官中.exe',config.selected)+row('安卓.exe',config.otherSelected);update();}
  if(config.folder){document.getElementById('files').innerHTML=row('P5248',false);document.getElementById('files').addEventListener('dblclick',()=>setTimeout(files,2200),{once:true});}else files();
  document.getElementById('files').addEventListener('click',e=>{
   if(/^document_table_list_check(?:ed)?$/.test(e.target.className)){checkboxClicks++;e.target.className=e.target.className==='document_table_list_checked'?'document_table_list_check':'document_table_list_checked';update();}
   if(e.target.closest('.touch-div')){fileClicks++;document.getElementById('preview').hidden=false;}
  });
  document.querySelector('.fileName-button-two').onclick=()=>{if(document.getElementById('count').textContent==='已选择 1 项' && document.querySelector('.document_table_list_checked').parentElement.textContent.includes('PC-官中.exe'))downloadClicks++;else throw new Error('错误下载选择');};
  document.getElementById('wrong-download').onclick=()=>wrongClicks++;
 },config);
 await page.addScriptTag({path:'extension/core.js'});await page.addScriptTag({path:'extension/cloud.js'});
 const result=await page.evaluate(()=>new Promise(resolve=>handler({type:'AUTO_PC',jobId:'fixture'},null,resolve)));
 const actions=await page.evaluate(()=>({sent,fileClicks,downloadClicks,wrongClicks,checkboxClicks,preview:document.getElementById('preview').hidden}));
 assert.equal(actions.fileClicks,0,'不应点击文件名打开预览');assert.equal(actions.wrongClicks,0,'不应点击其他同名下载按钮');assert.equal(actions.preview,true);
 if(config.otherSelected){assert.equal(result.ok,false);assert.match(result.error,/其他|多|选中/);assert.equal(actions.downloadClicks,0);}
 else {assert.equal(result.ok,true,result.error);assert.equal(result.filename,'PC-官中.exe');assert.equal(actions.downloadClicks,1);assert.equal(actions.checkboxClicks,config.selected?0:1);assert.equal(actions.sent.find(m=>m.type==='ARM').filename,'PC-官中.exe');}
 console.log('PASS:',config.name);await page.close();
 }
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
