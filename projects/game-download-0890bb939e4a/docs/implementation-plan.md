# Edge 游戏下载助手实施计划

Goal：交付可加载的 Edge 插件和可注册的本地解压助手。
Architecture：插件保留任务与浏览器下载关联；Python 助手按请求解压归档。
Tech Stack：原生 JS / Manifest V3 / Python 标准库 / 已有 7-Zip。
Spec：docs/design.md。

## 全局约束
保留原下载、不覆盖已有游戏、不执行包内程序、密码不写日志、未知或多候选必须提示。

## Review Focus
后台标签被关闭；下载事件串包；网页卡片选错；压缩包路径/链接；助手启动失败后的重试。

## 任务 1：可测试核心
- [x] 先写 JS 分类/PC 候选测试及 Python 路径、介绍、归档冲突测试，运行确认缺实现失败。
- [x] 实现 extension/core.js 与 native/archive_helper.py。
- [x] 跑全部测试，结合前轮本地 RAR5 校验证据与新小型加密7z伪装exe的真实归档联调验证。

## 任务 2：浏览器流程
- [x] 实现 manifest、后台队列、云盘 DOM 自动化、介绍卡片选择、设置和任务页面。
- [x] 以 Playwright DOM fixture 与两个真实Sway页面验证捕获和UI，语法检查所有JS。

## 任务 3：交付与联调
- [x] 实现 Native Messaging framing、安装/卸载注册器，写使用说明。
- [x] 真实 stdio 归档联调、独立审查后修复、隔离Edge插件加载测试。
- [x] 安装后的已登录云盘联调列为待验证；第一版交付不称完整下载链路已成功。

执行：用户已要求按方案开始；在当前会话直接实施，不额外创建 Git 仓库或推送。
