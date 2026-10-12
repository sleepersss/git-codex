const { chromium } = require('C:/Users/xdw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
 const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
 try {
  const page = await browser.newPage({ acceptDownloads: false });
  await page.goto('https://yun.139.com/shareweb/#/w/i/2ygb7tkZkc35q', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(8000);
  await page.getByText('P6518', {exact: true}).first().dblclick();
  await page.waitForTimeout(3000);
  console.log('FILES:', await page.locator('body').innerText());
  page.on('download', async download => { console.log('DOWNLOAD_EVENT:', download.suggestedFilename()); await download.cancel(); });
  const pcFile = page.getByText(/PC-AI翻译/).first();
  await pcFile.click();
  await page.waitForTimeout(1000);
  console.log('AFTER_PC_CLICK:', await page.locator('body').innerText());
  if (await page.locator('.login-mask').isVisible()) {
   console.log('RESULT: LOGIN_REQUIRED');
   await page.screenshot({path: 'cloud-test-login.png', fullPage: true});
   return;
  }
  await page.getByText('下载', {exact:true}).first().click({timeout:5000});
  await page.waitForTimeout(5000);
  console.log('AFTER_DOWNLOAD:', await page.locator('body').innerText());
  await page.screenshot({path: 'cloud-test-page.png', fullPage: true});
 } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
