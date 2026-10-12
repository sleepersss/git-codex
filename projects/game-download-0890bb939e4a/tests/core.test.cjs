const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../extension/core.js');
test('标题分类保留游戏名', () => {
 assert.deepEqual(core.parseTitle('【RPG/动态】游戏测试 v1.0（PC/安卓）'), {category:'RPG',title:'游戏测试 v1.0'});
 assert.throws(()=>core.parseTitle('普通标题'), /类型/);
});
test('长标题换行不截断且移除PC平台信息',()=>{
 assert.deepEqual(core.parseTitle('【SLG/动态】游戏名（日文译名\n后半部分）（PC/Mtool/joi）\n\n介绍'),{category:'SLG',title:'游戏名（日文译名 后半部分）'});
});
test('PC排除安卓且多候选停止', () => {
 assert.equal(core.selectPC(['安卓.exe','PC-AI翻译（工具启动）.exe']), 'PC-AI翻译（工具启动）.exe');
 assert.throws(()=>core.selectPC(['PC中文.exe','PC原版.exe']), /多个/);
 assert.throws(()=>core.selectPC(['安卓.exe']), /PC/);
});
test('只接受移动云盘分享链接', () => {
 assert.equal(core.isShare('https://yun.139.com/shareweb/#/w/i/abc123'),true);
 assert.equal(core.isShare('https://evil.example/shareweb/#/w/i/a'),false);
});
test('浏览器下载关联不依赖不存在的tabId且拒绝串包',()=>{
 const job={expected:'PC中文.exe',armedAt:Date.now(),networkUrls:['https://download.example/unique-token']};
 assert.equal(core.matchesDownload({filename:'D:\\下载\\PC中文 (1).exe',url:'https://download.example/unique-token',referrer:'https://yun.139.com/shareweb/'},job),true);
 assert.equal(core.matchesDownload({filename:'D:\\下载\\安卓.exe',referrer:'https://yun.139.com/shareweb/'},job),false);
 assert.equal(core.matchesDownload({filename:'D:\\下载\\PC中文.exe',referrer:'https://other.example/'},job),false);
 assert.equal(core.matchesDownload({filename:'D:\\下载\\PC中文.exe',url:'https://download.example/other-token',referrer:'https://yun.139.com/shareweb/'},job),false);
});
test('IDM来源摘要按相同规范化编码生成',async()=>{
 const expected=require('node:crypto').createHash('sha256').update('https://download.example/file?a=x%2Ay&b=one+two&t=~').digest('hex');
 assert.equal(await core.hashURL('https://DOWNLOAD.example/file?t=~&b=one%20two&a=x*y#ignored'),expected);
});
