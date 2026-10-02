# Wallpaper Engine 开机归档插件

这是项目现有工具的启动编排层，不另造一套转换流程。它在 Wallpaper Engine
启动后、Workshop 源稳定后扫描一次；一天内不持续监听，也不判断用户临时看过
哪些壁纸。默认配置是 `dry_run`，不会修改数据库或归档。

## 安全启用条件

正式处理必须同时满足：

1. `config.json` 的 `activation_mode` 改为 `apply`；
2. 启动命令显式传入 `--apply`。

因此误运行入口文件只会生成计划。安装开机任务的脚本也会拒绝 dry-run 配置。

## 固定流程

1. 等待 `wallpaper32.exe` 或 `wallpaper64.exe`；
2. 等待 `431960` 源目录连续稳定；
3. 取得插件锁并确认本次 Windows 启动尚未完成扫描；
4. 只枚举 `431960` 的数字直属目录，读取 `project.json`；
5. 与 `database/wallpapers.json` 比较，形成新增、更新、待处理和缺失清单；
6. 先备份数据库，再原子写入扫描记录；缺失项目只报告，不删除历史记录；
7. video：把明确的 Workshop ID 交给现有 `process_wallpaper_videos.ps1`；
8. Scene：先运行循环依赖分析器，再运行现有静动态分类器；
9. Scene_Static：只复制 Scene 真正引用的原始图片，并用 SHA-256 验证；
10. Scene_Dynamic：按单个 ID 串行调用已验证的 MPKG 导出链；
11. 导出前核对分析结果 schema、阶段、`project.json` 与 `scene.pkg` 哈希；
12. 默认只使用作者的安全关闭选项；likely 选项默认不启用；
13. 完成 MPKG、RePKG、MP4、ffprobe、脚本恢复验证后再归档；
14. 各既有归档器维护其 CSV、XLSX 和 preview，最后从权威数据库重建 Markdown 索引；
15. 写入本次运行计划、分阶段结果和一次启动状态。

任何单项失败都记录在当前运行目录。配置默认继续处理下一项，但失败项不会被写成
成功。`web` 保留记录并跳过；未知类型保留原始类型并等待人工检查。

## 人工检查命令

仅生成计划：

```powershell
plugin\run_wallpaper_backup_plugin.ps1 -SkipStartupWait -ForceRescan -PlanOnly
```

正式处理（只有审核并切换配置后才可用）：

```powershell
plugin\run_wallpaper_backup_plugin.ps1 -Apply
```

预览开机任务安装内容：

```powershell
plugin\install_startup_task.ps1 -WhatIf
```

卸载任务必须显式确认；只删除任务，不删除项目文件或归档：

```powershell
plugin\uninstall_startup_task.ps1 -ConfirmRemoval
```

## 运行文件

每次计划与日志位于 `runtime/plugin/runs/<时间>/`。只有正式执行完成后才写
`runtime/plugin/state.json`，用于保证同一次 Windows 启动只执行一次。

## 当前验证边界

- 既有动态 Scene 链已经有 10 个连续成功案例，插件复用同一组入口和验证门。
- 循环依赖分析器、扫描规划、接口传递和静态资源解析有自动测试。
- 静态 Scene 归档目前只有隔离夹具验证；遇到首个真实静态样本时仍应复核结果。
- 开机任务脚本已生成但默认未安装，插件配置也保持 dry-run。
