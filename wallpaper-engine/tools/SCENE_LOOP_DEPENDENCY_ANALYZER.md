# Scene 循环依赖分析器

## 用途

`analyze_scene_loop_dependencies.mjs` 在动态 Scene 导出 MPKG 之前分析：

- 系统音频输入和音频响应；
- 鼠标、光标及交互效果；
- 现实时间、日期和时钟；
- Camera Parallax 和 Camera Shake；
- `engine.runtime`、随机状态等不能直接保证循环的脚本状态；
- 上述依赖与作者 User Property 的实际绑定关系。

分析器只读取 Workshop 源文件。需要读取 `scene.pkg` 时，使用 RePKG 解包到
`temp\extracted\scene_loop_analysis\`，不修改 `project.json`、`scene.pkg`、数据库或正式归档。

## 使用

分析单个或多个 Workshop ID：

```powershell
node tools\analyze_scene_loop_dependencies.mjs --workshop-id 2733091473
node tools\analyze_scene_loop_dependencies.mjs --workshop-id 2733091473,2938612768
```

分析当前 `431960` 中的全部 Scene：

```powershell
node tools\analyze_scene_loop_dependencies.mjs --all-scenes
```

默认结果：

```text
temp\extracted\scene_loop_analysis.json
```

## 决策值

- `NO_EXTERNAL_DEPENDENCY`：未发现本分析器支持的外部循环依赖。
- `AUTO_SAFE`：依赖均存在结构化作者开关或受支持的 Scene 设置覆盖。
- `AUTO_WITH_LIKELY_OVERRIDES`：包含基于作者属性名称与类型推断出的高概率开关。
- `REVIEW_REQUIRED`：仍有未找到安全控制项的依赖。

`REVIEW_REQUIRED` 不会丢弃已经找到的安全开关。插件仍可应用
`override_plan.auto_apply_user_properties`，但不得把该壁纸标记为已经完全净化。

## 覆盖规则

插件默认只能自动应用：

```text
override_plan.auto_apply_user_properties
override_plan.scene_settings
```

`likely_user_properties` 必须由插件的“宽松模式”显式启用或经过一次人工确认。

规则边界：

1. `bool` 使用真正的 `false`。
2. `combo` 使用作者选项中的真实 value，例如 `"1" = 关`，不能写布尔 `false`。
3. `slider` 只有在 `0` 位于 min/max 范围内且绑定字段具有关闭语义时才写 `0`。
4. `group`、`text`、`textinput`、`color` 不作为开关。
5. 优先使用与依赖对象直接绑定的属性；名称推断只进入 likely 结果。
6. 覆盖只进入本次导出请求，不写回 Workshop 源文件。

## 后续插件接入顺序

插件不要依赖加载顺序或脚本文件名排序，应按显式状态机调用：

```text
SCENE_CLASSIFIED_DYNAMIC
→ SOURCE_HASHED
→ SCENE_JSON_AVAILABLE
→ PRE_EXPORT_NORMALIZATION（本分析器）
→ 核对分析结果中的 project_json_sha256 / scene_pkg_sha256
→ 应用本次请求的覆盖计划
→ MPKG_EXPORT
→ MP4_VERIFY
→ LOOP_SEAM_AUDIT
→ ARCHIVE
```

分析核心位于：

```text
tools\lib\scene_loop_dependency_analyzer.mjs
```

它不访问文件系统，插件可以直接导入 `analyzeSceneLoopDependencies()`、
`validateSceneLoopAnalysisSource()` 和 `buildSceneLoopExportOverrides()`；如果插件使用其他
运行时，则调用命令行入口并读取 `schema_version = 1` 的 JSON。插件必须拒绝未知 schema，
并在源哈希变化后重新分析，禁止复用过期覆盖计划。

当前生产导出脚本尚未消费此 JSON。完成插件接入前，分析结果只作为分析和覆盖计划，不能
替代现有 MPKG、MP4、ffprobe 和 Save As 成功门槛。
