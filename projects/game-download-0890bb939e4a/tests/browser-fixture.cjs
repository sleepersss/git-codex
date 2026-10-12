const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium}=require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<main><article id="first"><img width="300" src="https://images.example/first.jpg"><section><h2>【SLG/动态】中文游戏（PC）</h2><p id="click">介绍正文</p><a href="https://yun.139.com/shareweb/#/w/i/abc123">下载</a></section></article><article><h2>【ACT/动态】第二个游戏（PC）</h2><a href="https://yun.139.com/shareweb/#/w/i/def456">下载</a></article></main>');
  await page.evaluate(()=>globalThis.chrome={runtime:{onMessage:{addListener(){}},sendMessage:async()=>({ok:true})}});
  await page.addScriptTag({path:path.resolve('extension/core.js')});
  await page.addScriptTag({path:path.resolve('extension/capture.js')});
  const captured=await page.evaluate(()=>gameCaptureFromElement(document.getElementById('click')));
  assert.equal(captured.title,'中文游戏');assert.equal(captured.category,'SLG');assert.equal(captured.imageUrls.length,1);assert.ok(!captured.text.includes('第二个游戏'));
  console.log('PASS: 卡片文字与图片同归属，不串入下一游戏');
  await page.setContent('<div id="storyroot"><div class="container list"><div class="container cursorPointer focusable"><img width="300" src="https://images.example/one.jpg"><div class="text_wrapper"><p>【SLG】很长的游戏名称（PC/Mtool/joi）</p></div></div><div class="container"><div class="text_wrapper"><p>介绍</p><a id="split" href="https://yun.139.com/shareweb/#/w/i/abc123">下载</a></div></div><div class="container cursorPointer focusable"><img width="300" src="https://images.example/two.jpg"><div class="text_wrapper"><p>【ACT】第二游戏（PC）</p></div></div><div class="container"><a href="https://yun.139.com/shareweb/#/w/i/def456">下载</a></div></div></div>');
  const split=await page.evaluate(()=>gameCaptureFromElement(document.getElementById('split')));
  assert.equal(split.title,'很长的游戏名称');assert.deepEqual(split.imageUrls,['https://images.example/one.jpg']);assert.ok(!split.text.includes('第二游戏'));
  console.log('PASS: Sway标题图片卡片与正文卡片配对');
  await page.setContent('<div id="storyroot"><div class="container list"><div class="container"><p>【SLG】上一游戏（PC）</p><a href="https://yun.139.com/shareweb/#/w/i/aaa111">下载</a></div><div class="container cursorPointer focusable"><img id="image-next" width="300" src="https://images.example/next.jpg"></div><div class="container"><div class="text_wrapper"><p>【ACT】当前游戏（PC）</p><a href="https://yun.139.com/shareweb/#/w/i/bbb222">下载</a></div></div></div></div>');
  const nextGame=await page.evaluate(()=>gameCaptureFromElement(document.getElementById('image-next')));
  assert.equal(nextGame.title,'当前游戏');assert.equal(nextGame.category,'ACT');
  console.log('PASS: 点击图片时不误选上一个游戏');
  const ui=await browser.newPage();
  await ui.addInitScript(()=>{globalThis.chrome={runtime:{id:'a'.repeat(32),sendMessage:async m=>({jobs:[],settings:{root:'E:\\test',password:'',sevenZip:'7z.exe'},extensionId:'a'.repeat(32)}),openOptionsPage:async()=>{}},storage:{onChanged:{addListener(){}}}};});
  const errors=[];ui.on('pageerror',e=>errors.push(e.message));
  await ui.goto('file:///'+path.resolve('extension/options.html').replaceAll('\\','/'));
  assert.equal(await ui.locator('#root').inputValue(),'E:\\test');
  await ui.screenshot({path:'docs/settings-preview.png'});
  await ui.goto('file:///'+path.resolve('extension/tasks.html').replaceAll('\\','/'));
  assert.ok((await ui.locator('#jobs').innerText()).includes('还没有任务'));
  assert.deepEqual(errors,[]);
  console.log('PASS: 设置与任务页面加载，没有脚本错误');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
