# 工作区入口

制作、接续或整理自制 Mod 时，先读 `create/AGENTS.md`。菲比 × 达妮娅项目的唯一当前版本指针是 `create/phoebe/project.json`，说明入口是 `create/phoebe/当前成果.md`。不要从聊天编号、文件修改时间或历史报告中的“最新”推断当前基线。

`model-library` 按其自己的 AGENTS.md 管理；`create/WWMIHashRepair` 是独立工具，不作为菲比测试垃圾清理。

## Shared Git source snapshots

When the user says "连接 Git", "提交到 Git", or "备份源码" in a local project, read C:/Users/xdw/.codex/skills/shared-git-sync/SKILL.md and use its unified tool. Default repository: https://github.com/sleepersss/git-codex.git; do not ask for the repository address again.

User-specified repositories take precedence. Preserve any explicitly configured different project remote and use its normal workflow. Shared snapshots must use the dedicated checkout and stable local-path mapping under C:/Users/xdw/.codex/git-sync-state, never push unrelated project histories directly into shared main.

Preview and inspect source/document scope, respect project ignore rules, exclude runtime data, media, databases, backups, caches, credentials and local sensitive settings. Add project-specific `.codex-sync-ignore` exclusions when needed. "连接 Git" prepares preview/mapping; submission/source backup requests authorize the reviewed snapshot push. Fetch latest before updating only the project's mapped subdirectory. Preserve local Git history, record project name and local revision, do not propagate deletions or force push. Preserve local results and report concrete reasons on conflicts, authentication failures or ambiguous scope.
