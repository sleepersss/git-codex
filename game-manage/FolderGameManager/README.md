# 文件夹游戏管理器

一个面向本地文件夹游戏库的 Playnite Library Plugin。

默认只扫描：

```text
E:\1_Game\some games
```

目录约定：

```text
游戏根目录\类型\游戏文件夹\游戏.exe
```

系列合集和多版本目录可以继续嵌套。插件会寻找包含可用 EXE 的游戏目录，过滤卸载器、崩溃报告器和常见安装程序。

## 字段映射

| Playnite 字段 | 内容 |
|---|---|
| 分类 | 一级类型目录，例如 ACT、ADV、RPG、SLG |
| 名称 | 游戏文件夹原名 |
| 完成状态 | 未玩 |
| 标签 | 未备份 |
| 版本 | 主 EXE 的原始文件名 |
| 安装目录 | 游戏文件夹完整路径 |

同一目录中的多个可信 EXE 会作为多个启动动作保存，评分、添加时间和游玩时间继续由 Playnite 管理。

## 构建

项目目标为 .NET Framework 4.6.2，并引用本机 Playnite 安装目录中的 `Playnite.SDK.dll`。当前版本固定扫描上述根目录，不提供设置页。本机可直接运行：

```powershell
.\build.ps1
```

如果 Playnite 安装在其他目录，可传入 `-PlayniteInstallDir "你的 Playnite 安装目录"`。

构建产物位于 `bin\Release`。将该目录放入 Playnite 的 `Extensions` 目录后重启 Playnite。
