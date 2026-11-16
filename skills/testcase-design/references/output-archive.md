# 需求 Output 归档定位规则

本文件是 P1/P2/P3/P5 及需求关联 Bug 归档的共同路径规则。任何工作流不得自行从需求标题推断一级模块目录。

## 一级模块来源

- **首次建立需求归档前**，必须通过公司禅道 MCP `kye.mcp.zentao` 调用 `getNeedDetailById({ id: <需求编号> })` 获取需求详情。
- 核对返回的 `data.id` 与当前需求编号一致；必须同时取得非空 `data.module`（模块 ID）和 `data.moduleName`（模块名称）。模块 ID 必须为数字。缺失、空值、ID 不一致或返回结构无法确认时停止，不创建目录、不从标题括号、产品名、产品线或其他字段猜测。
- 一级目录以 `data.moduleName` 的真实名称为依据，按 Windows 文件名规则清理后外层添加 `【】`，格式为 `【<禅道真实模块名>】`；**不得从需求标题的 `【】` 推断模块**。清理只影响目录组件；Manifest 保存禅道返回的原始 `module_id`、`module_name`。
- 二级需求目录继续使用 `<需求编号>-<完整原始需求标题>`，标题中的 `【】` 仅是标题正文，不再参与模块分组。
- 首次定位命令：`python -B skills/testcase-design/tools/manifest.py directory-name <需求编号> "<完整需求标题>" --module-id <module> --module-name "<moduleName>"`。命令返回 `module_id`、原始 `module_name`、安全目录组件 `module_directory_name`、`directory_name` 和 `archive_relative_path`。
- 正式路径：`output/【<禅道真实模块名>】/<directory_name>/`（以工具返回的 `module_directory_name` 安全组件为准）。
- 新需求首次执行 `manifest.py publish` 时，无论通过 CLI 还是 Python `publish_version()` 公开入口，都会在创建发布锁文件/模块父目录前预检模块信息和路径；必须匹配安全模块目录与需求目录，缺失或路径不匹配直接失败。锁内会再次校验冻结模块、基线和历史一致性。已有历史 Manifest 的根目录仍允许沿用旧路径，以兼容迁移前的需求，不会因新规则自动移动。

## 模块元数据冻结

- 首次正式发布的 publish spec 必须在 `requirement` 中写入 `module_id`、`module_name`；`manifest.py publish` 对新需求或缺少冻结模块元数据的历史需求强制校验这两个字段。
- Manifest 的 `requirement` 同时保存 `id`、`name`、`module_id`、`module_name`。后续增量优先继承最新有效 Manifest 中已冻结的模块元数据，不重复调用禅道 MCP；不得因需求标题括号变化而改变一级目录。
- 已有 Manifest 缺少模块元数据时，先定位现存需求根目录（优先当前工作上下文，其次 `output/legacy-path-map.json`；映射未覆盖时按需求编号精确查找唯一现存目录）。不得先按新模块路径创建第二份需求根目录。只读调用一次 `getNeedDetailById` 获取真实模块，在下一次正式 publish spec 中补入模块元数据；在补齐前不得新建另一个根目录。
- 若已有 Manifest 已冻结模块 ID/名称，而本次已可信取得的禅道详情与冻结值不一致，停止并报告模块归属变化；不得自动改写 Manifest、移动目录或创建新根目录。目录迁移必须走独立的历史迁移步骤。
- 已有需求的正式发布继续使用已定位的现存需求根目录；模块元数据补齐不代表本次自动迁移目录。

## 兼容与边界

- `output/legacy-path-map.json` 仅用于旧路径兼容定位；历史迁移时再更新映射。不能仅凭标题解析结果重建旧路径。
- `output/api-automation/` 是项目级接口索引/证据目录，始终独立保留，不跟随需求模块迁移。
- 目录名清理后为空、为 `.`/`..` 或 Windows 保留设备名时明确失败；不得回退到 `【未分类】`、标题模块或其他默认名称。
- 需求根目录内的版本序列、Manifest、产物类型目录、文件正文及 SHA-256 规则保持不变。历史迁移不得改写正式产物正文。
