# 正式用例产物、身份与归档规则

## 权威内容源

- 每个正式需求版本以 `testcases.md` 作为唯一权威用例内容源。
- XMind 必须从 Markdown 重新生成，不允许两份产物独立维护。
- Oracle 独立保存，来源于需求和业务规则，不从用例预期复制。
- Manifest 负责版本账本、完整用例身份快照和产物指纹；不保存完整用例正文，不另存重复的完整用例 JSON。

## Case ID 与 Revision

- 每条用例首次创建时生成永久唯一的内部 Case ID；新用例的 Revision 从 `1` 开始，由 Manifest 记录，不写入用例正文。
- 格式：`QA-<需求编号>-<10位小写十六进制标识>`，示例结构：`QA-<需求编号>-<标识>`。
- Case ID 不依赖用例顺序、版本或日期；正式交付后永不改变、不得复用。
- 每条用例在 Markdown 内容中使用 HTML 注释保存身份：`<!-- qa_case_id: QA-<需求编号>-<标识> -->`。
- Revision 由 Manifest 管理，不重复写入用例正文；只有测试目标对应的业务语义发生实质变化时才递增。
- 测试目标一致时，标题有意义的修正、操作步骤/预期内容修订、优先级修改，保留原 Case ID 并递增 Revision；其他字段变化只有实际改变该测试目标的业务语义时才递增。
- 仅业务分组或排序变化可以形成新的正式展示版本，但未变化用例的 Revision 不增加；纯排版、空白、标点等不影响语义的调整，不单独产生正式版本或 Revision。
- 新增独立测试目标时分配新 Case ID，Revision 从 `1` 开始；拆分/合并形成新目标时分配新 ID 并保留来源关系。
- 业务功能明确取消时，退役原 Case ID 并保留历史；退役本身不强制增加原用例 Revision。
- 身份或退役依据不明确时，保留旧用例并列出待核对事项；如果已有用例的 Case ID 缺失、重复，且无法通过上一正式版本及 Manifest 确定身份，不得擅自分配新 ID 或发布该版本。
- 内部 Case ID 与禅道远端 ID、ACE MindMap ID/Node UID 分离。

## 用例正文与展示

- 标题表达“业务场景 + 核心验证目标”，不使用连续编号作为稳定身份。
- 优先级采用 P0–P4，保留在 Markdown 权威数据中。
- 前置条件、测试数据按需出现；不需要时不创建空区块。
- 页面路径通常写入第一条实际操作步骤。
- 每一步操作对应一个或多个预期结果。
- 设计依据、关键业务确认、待确认事项或范围排除按实际情况放在文末；不存在的区块省略。
- Case ID、Revision、来源和 Oracle 等内部管理信息不得进入普通展示节点。

### 首批可执行 Markdown 结构（testcases/testcases.md）

以普通 Markdown 和单行可识别标签为权威用例结构，不引入中间用例 JSON，也不对标题、步骤、预期设置长度上限。完整结构示意（内容仅为格式示例）：

```markdown
# <需求编号>｜<需求名称>

## 一、核心业务
### 按筛选条件查询并正确展示结果
<!-- qa_case_id: QA-<需求编号>-<标识> -->
- **优先级**：P1
- **前置条件**：存在符合当前条件的数据
- **测试数据**：条件 A 对应数据集
1. **操作**：进入对应业务页面，选择条件 A 并查询
   - **预期**：结果仅包含满足条件 A 的数据
   - **预期**：汇总口径与当前条件一致
2. **操作**：清空条件并重新查询
   - **预期**：结果恢复默认范围

## 二、异常业务
### 无匹配记录时展示空结果
<!-- qa_case_id: QA-<需求编号>-<标识> -->
- **优先级**：P2
1. **操作**：在业务页面选择无匹配记录的条件并查询
   - **预期**：列表展示空结果

## 附录：设计依据与待确认事项
- 有真实内容时记录，不进入 XMind 正常用例树
```

- 首行固定 `# 需求编号｜需求名称`；`##` 为按业务动态确定的非空分组；`###` 为自然语言用例标题；每条用例标题下紧接唯一 `<!-- qa_case_id: ... -->`。
- `- **优先级**：P0..P4` 必填；`- **前置条件**：...` 和 `- **测试数据**：...` 可选，放在第一步之前，无内容不填写；Revision 只在 Manifest 中记录。
- 操作使用 `1. **操作**：...` 从 1 顺序编号，每步下直接放一个或多个 `   - **预期**：...`。每步必须有预期；没有额外的步骤父节点，也不重复导航动作。
- 业务正文只使用上述可解析结构。设计依据、风险和未决事项在必要时放到文末专用 `## 附录` 或 `## 附录：说明`（英文冒号亦可）之后；该部分不属于用例树。`## 附录查询业务` 等并非附录标题，必须作为正常业务分组完整解析。附录一旦开始，后续不得再出现任何 Markdown 标题、Case ID、优先级/前置条件/测试数据标签、操作步骤或预期结构；发现则报错，不允许静默跳过可能误放的用例。附录只放普通说明文字或普通列表，不能在用例内部插入自由格式段落导致转换时丢失信息。
- 格式解析可以拒绝缺 ID、重复 ID、步骤跳号、预期缺失等确定性错误；需求真实、业务预期与场景覆盖由 AI 判断，不能因为结构校验通过而宣称质量或业务 PASS。
- 独立结构诊断入口（按需）：`python skills/testcase-design/tools/artifacts.py <testcases.md> <oracle.json>`。标准输出为 ASCII 转义 JSON，不依赖 Windows GBK/UTF-8 终端编码；JSON 解析后中文和 Unicode 原文保持不变。该命令可用于单独定位 Markdown/Oracle 结构问题，`STRUCTURE_PASS` 只表示 Markdown/Oracle 结构一致性通过；**它不是正常正式发布的必经步骤**，正式交付由 `manifest.py publish` 内置的 Markdown 解析、Markdown/Oracle 结构校验及 XMind 回读完成。第一批 Markdown/Oracle、第二批 XMind 和第三批 Manifest 均已完成工程独立验收并关闭；第三批于 2026-10-31 经 Codex 第三轮 PASS、用户批准关闭。该状态仅代表相应工程批次关闭，不代表真实业务语义/覆盖、XMind 桌面渲染、ACE 平台导入、跨 Agent 实际运行或 P1 整体业务验收通过。

## XMind 结构

主体层级为：

`需求根节点 → AI 动态业务分组 → 用例标题 → 按需前置条件/测试数据 → 操作步骤 → 对应预期结果`

- 不额外创建统一的“操作步骤”父节点。
- 步骤直接挂在用例标题下，预期结果挂在对应步骤下。
- 无前置条件或测试数据时不创建空节点。
- 保留必要的业务分组语义，不用 TC001 等序号充当稳定身份。
- 优先级作为用例属性处理，不额外创建优先级子节点或人为拼接标题标记。
- 右侧圆圈数字代表子节点数量，不是用例属性。
- XMind 生成后必须重新读取/解析实际文件结构，并逐项核对：需求名称、业务分组及顺序、用例标题及数量、优先级、按需前置条件/测试数据、操作步骤内容及顺序，以及每一步对应的预期结果内容和数量。
- Case ID、Revision、来源、Oracle 等内部管理信息不得进入普通展示节点；发布前上述结构核对必须全部通过。发现不一致时，修正权威 Markdown 或转换逻辑后重新生成并复核，不得以人工修改 XMind 掩盖差异。
- 本地 XMind 结构回读通过不等于 ACE 平台实际展示已验收；如需核实平台展示，应由用户另行授权开展单独的展示验收。正常导入以创建接口明确成功回执及唯一 MindMap ID 为成功依据，不增加创建后整图回读门禁。

### 第二批 XMind 生成、实际文件回读与优先级保真

- `tools/xmind.py` 直接导入并调用首批 `tools/artifacts.py` 中的 Markdown 解析函数，再生成 XMind 2020+ 风格 ZIP 文件（`content.json`、`metadata.json`、XMind 包内部的 `manifest.json`）；这是代码复用，不要求单独执行 `artifacts.py` CLI。XMind ZIP 内部的 `manifest.json` **不是**需求级版本目录的正式 Manifest，不得混淆。
- 内容树严格按 `需求根节点（编号｜名称） → 动态分组 → 用例标题 → 按需前置条件/测试数据、直接步骤节点 → 本步骤多个预期节点` 构建。原始步骤和预期文本无静默截断；显示标题使用 `序号. 操作内容`、`预期：结果内容`，无统一步骤父节点。
- P0–P4 映射到 XMind 内置数字优先级图标 `priority-1` 至 `priority-5`（P0→1、P1→2、P2→3、P3→4、P4→5）；这是**本地 XMind 展示标记**，并非禅道/ACE `pri` 字段值映射，也不代表平台优先级的已验事实。用例不添加优先级子节点，不在标题文本拼接标记。XMind 节点临时 ID 仅供文件内部使用，不是永久 Case ID。
- 生成后必须从**磁盘上实际保存**的 `.xmind` ZIP 重新解析，逐项比对根节点名称、业务分组及顺序、用例标题及数量、优先级、按需前置条件与测试数据、操作步骤及顺序、每步预期的内容和数量；额外分支/缺失节点/非法或重复 ID/优先级缺失或异常均不得静默通过。内部 Case ID、Revision、来源和 Oracle 等不能进入展示树。
- `python skills/testcase-design/tools/xmind.py <testcases.md> <testcases.xmind>`：生成并立即实际回读验签；`python skills/testcase-design/tools/xmind.py <testcases.md> <testcases.xmind> --verify`：仅重新读取现有文件核对权威 Markdown，不修改产物。生成器拒绝覆盖已存在的 `.xmind`，以免覆盖历史文件。CLI 输出 ASCII 转义 JSON，支持 Windows GBK，`XMIND_READBACK_PASS` 仅代表本地结构完整。
- 格式解析和第三方库读取成功**不等于** XMind 桌面客户端真实打开/渲染通过，也不等于 ACE 导入展示通过；若没有相应实际证据，应记录 `desktop_open_verified=false`。真实业务覆盖仍由 AI 独立评审；需求级 Manifest、历史身份和正式版本发布已由第三批 `tools/manifest.py` 实现，第三批已于 2026-10-31 经 Codex 第三轮独立复审 PASS 并由用户批准关闭。该工程关闭状态不代表桌面渲染、平台导入、真实业务语义或 P1 整体业务验收通过。
- 故障处理：若实际 ZIP 的压缩数据损坏（包括 DEFLATE 解压异常），回读/CLI 应返回可控失败，不输出未处理 traceback；新建目标在写入中断、关闭失败或回读失败时，应尽可能清理**本次成功排他创建**的失败残留，允许重新生成。因目标已存在而排他创建失败时绝不删除或覆盖旧文件；若文件系统拒绝清理，必须显式报告失败，不能声称无残留。

## 需求级版本与目录

正式需求归档根目录：

`output/【<禅道 moduleName>】/<需求编号>-<需求名称>/`

- 一级模块目录必须使用禅道需求详情真实 `moduleName` 并在外层添加 `【】`；目录组件按 Windows 规则安全处理。不得从需求标题提取模块名或回退到“未分类”。
- 需求目录名继续使用完整的 `<需求编号>-<原始需求名称>`，保留标题中的全部 `【】`，不去掉括号、不改写需求标题。需求名称中的 Windows 非法字符仍按既有规则替换为下划线。
- 首次归档前按 `references/output-archive.md` 调用禅道 `getNeedDetailById` 并核对需求 ID、模块 ID、模块名称；通过 `manifest.py directory-name <需求编号> <需求名称> --module-id <module> --module-name "<moduleName>"` 获取 `module_id`、原始 `module_name`、安全目录组件 `module_directory_name`、`directory_name` 和 `archive_relative_path`。


版本按需求统一管理，不按产物类型分别编号。同一需求同一天首次正式交付从 v1 开始，当天后续独立正式交付递增；跨日期后重新从 v1 开始。一次正式交付任务（完整或部分）只产生一个版本。临时草稿、失败重试、交付前内部修正、仅查看/咨询及无实质内容变化的重复执行不产生新版本。正式产物发生实质新增、修改或废弃时创建新版本；历史版本不覆盖。若本次修改用例，当前版本的 Markdown 保存完整的当前有效用例集合，不只保存差异条目。未变化产物保留在原来源版本目录，由当前 Manifest 引用，不重复复制。正式历史文件永久保留；只清理临时草稿、失败残留和缓存。

历史归档正文中的旧路径引用不回写，避免改变历史正式文件 SHA；遇到旧需求根路径或旧版本/类型顺序时，按 `output/legacy-path-map.json` 定位现存路径。已有需求必须先定位现存根目录，不得因新模块名称不同而创建重复根目录。历史迁移完成后映射指向禅道真实模块目录；正式发布路径和模块元数据规则见 `references/output-archive.md`。

## 需求目录内部结构

Manifest 统一保存在需求根目录的 `versions/<YYYYMMDD-vN>/manifest.json`；业务产物按类型分目录，版本目录放在类型目录下面：

```text
<需求根目录>/
├── versions/
│   ├── <版本1>/manifest.json
│   └── <版本2>/manifest.json
├── testcases/
│   └── <版本号>/
│       ├── testcases.md
│       ├── testcases.xmind
│       └── oracle.json
├── sql/
│   └── <版本号>/
├── analysis/
│   └── <版本号>/
└── api-automation/
    └── <版本号>/
```

以上类型目录全部按需创建，没有该类型正式产物时不创建空目录。分类含义：
- `testcases/`：测试用例及独立 Oracle。
- `sql/`：仅用户明确要求 SQL 时创建。
- `analysis/`：P2 代码影响分析正式产物；Manifest 内部 `category` 仍使用 `test-impact-analysis`，不新增 category。历史 `test-impact-analysis/` 目录及旧的版本优先路径继续兼容读取。
- `api-automation/`：按需的需求关联接口自动化产物。

不默认创建 `test-execution/`。不把 WebCodex 会话 ID、运行批次 ID 等技术标识放入需求目录名。

## Manifest 数据契约（schema_version = "1"）

Manifest 是需求级正式版本账本和当前有效产物清单，不保存完整用例正文，不引入数据库。

必需字段：

- `schema_version`：当前为字符串 `"1"`。
- `requirement`：`id`、`name`；新归档必须同时保存禅道真实 `module_id`、`module_name`。历史 Manifest 可暂时缺少这两个兼容字段；后续首次正式发布时必须补齐，已冻结的模块元数据后续版本沿用。
- `version_id`：`YYYYMMDD-vN`，日期采用北京时间；同一需求同日递增，跨日从 v1 开始。
- `created_at`：ISO 8601 北京时间，必须保留 `+08:00`。
- `delivery_status`：`complete` 或 `partial`，描述本次声明交付范围及交付状态，不是业务语义验收结果。`complete` 不自动证明 Oracle 覆盖完整或业务验收通过；但发布前若已知声明范围内仍有重要业务义务未落实为可执行用例，不得将该范围宣称为完整交付。`partial` 仅用于明确限定的部分交付，并须说明已交付与未决范围，不能用来掩盖本可修正的设计遗漏。
- `artifacts`：当前有效正式产物的完整清单。每项含 `category`、`role`、相对需求根目录的 `path`、原始文件所在版本 `source_version`、本版本的 `change`（`added` / `updated` / `unchanged`）和文件 `sha256`。
- `case_snapshot`：当前需求全部有效及已退役用例的身份快照。每项含 `case_id`、`revision`、`status`（`added` / `updated` / `unchanged` / `retired`）、`content_sha256`；拆分/合并形成的新用例可附 `derived_from`，退役项保留 `retirement_reason`。
- `case_count`、`retired_case_count`：分别统计有效和退役用例。
- `validation`：记录实际执行的确定性检查结果。当前用例发布记录 Markdown/Oracle 结构校验、XMind 回读结果；`semantic_review: NOT_AUTOMATED` 明确表示业务语义不是 Python 自动验收。
- 可选 `case_changes`：仅在本次用例有变化时出现，字段为 `added`（Case ID 数组）、`updated`（含 `case_id`、`from_revision`、`to_revision` 的对象数组）、`retired`（含 `case_id`、`reason` 的对象数组）。

规则：

- 新增/更新产物保存在 `<category-directory>/<version_id>/`，`source_version` 指向当前版本；未变化产物继续留在原类型目录下的来源版本目录，由当前 Manifest 引用，不复制。
- `path` 相对需求根目录；第一层目录是产物类型，第二层是 `source_version`，例如 `testcases/20261113-v1/testcases.md`、`sql/20261113-v2/query.sql`、`analysis/20261113-v3/impact-analysis.md`。Manifest 内部 `test-impact-analysis` category 的正式目录固定为 `analysis/`；其他 category 的目录与 category 同名。旧版 `<source_version>/<category-directory>/...` 路径继续兼容读取。每个来源版本必须存在于正式版本历史中，且来源版本 Manifest 必须登记相同的 `category`、`role`、`path` 和 `sha256`；不能仅凭来源目录存在或文件哈希匹配建立追溯关系。
- 路径使用 POSIX 相对路径表达，但必须同时符合 Windows 文件名规则：拒绝路径穿越、尾随空格/点、Windows 非法字符及保留设备名；发布前还会核对规范化后的暂存目标仍位于临时版本目录内。
- 用例正式产物的 `testcases` 分类必须完整包含 `markdown`、`xmind`、`oracle` 三个角色；有效用例身份存在时必须保留完整用例产物。
- Case ID 永久唯一，历史退役 ID 也不能复用。新用例 Revision 从 1 开始；AI 判断为实质修改时 Python 将 Revision 精确递增 1；未变化用例保持原 Revision；退役不增加 Revision。
- 用例内容指纹基于标题、优先级、前置条件、测试数据、操作步骤及预期；不包含业务分组和顺序。Python 只计算指纹，不负责判断业务语义或决定哪些用例属于修改；`inspect`、`validate` 和正式发布前均须按 Case ID 从权威 Markdown 重算并核对全部历史 Manifest 中的有效用例指纹；首次退役及后续退役快照必须逐版本保持与上一版本相同的 `content_sha256`。
- Manifest 不存储完整用例正文或重复 JSON；Markdown 仍是唯一用例内容源。

## 增量与有效基线

- 使用 `manifest.py inspect <需求归档根目录>` 定位最新正式版本。先按北京时间日期排序，再按同日 `vN` 数字排序；不能仅按版本号大小或文件修改时间判断最新。一次增量任务只运行一次 inspect。
- `inspect` 返回最新 `manifest_path`、当前有效 `markdown_path` 和 `latest_version`，并核验 Manifest 历史结构/身份连续性、**全部历史有效用例指纹及退役快照连续性**、最新有效产物 SHA。每个历史版本都按其权威 Markdown 重算有效用例指纹；相同规范化 Markdown 路径在一次 inspect 中只读取/解析一次，再分别与各版本快照核对。inspect 不承诺校验所有历史产物文件 SHA；该项由 publish 预检和 validate 完成。
- 对已有需求，将最新 `manifest.json` 与当前有效 `testcases.md` 放在同一次批量读取中。最新 Manifest 的完整 `case_snapshot` 必须包含所有历史 Case ID（包括退役 ID）；不得为整理身份清单而逐个读取历史 Manifest 或旧版 Markdown。只有遇到具体来源追溯、拆分/合并疑点或验签失败，才定向读取对应历史文件。
- 沿最新 Manifest 的完整 `artifacts` 清单解析当前有效产物。若仍有有效用例，最新版本即使只交付 SQL 或提测分析，也必须继续引用最近有效的 `testcases.md` 和对应身份快照，不能从空集合开始。若全部用例已明确退役，则当前版本不再要求保留 Markdown，继续保留完整退役身份快照和历史正式文件即可。
- 增量前由 AI 按业务目标、业务对象及区分场景的关键业务条件，逐条分类为保留、修改、新增、明确退役或身份待核对。禁止用标题相似度、固定关键字或 Python 算法决定业务身份。
- 新增用例前运行 `manifest.py ids <需求归档根目录> <需求编号> --count N --baseline-manifest <inspect 返回的 manifest_path>`。该模式校验基线 Manifest 的需求编号、目录名及最新版本位置，并从完整 `case_snapshot` 读取所有历史身份（包括退役身份），不重新扫描全部历史 Manifest。首次交付或无历史时可使用不带 `--baseline-manifest` 的命令。正式发布前仍由 publish 全量复核历史和 Case ID 唯一性，发现历史快照缺失或损坏时拒绝提交。
- `case_changes` 输入中的 `added` 和 `updated` 是 Case ID 数组；`retired` 是包含 Case ID 和真实退役原因的对象数组。Python 校验身份关系并生成更新后的 `from_revision` / `to_revision`，不替 AI 做业务匹配。
- 旧用例没有充分退役依据或身份暂不明确时，仍保留在当前有效用例集合中并单独报告；不得因本次生成未写出而自动删除、合并或退役。身份缺失/重复且无法追溯时，不得擅自重分配 ID 或发布。
- 新版本 Markdown 保存完整的当前有效用例集合，不只保存差异；XMind 与之同步。部分版本不得丢弃此前仍有效的用例，也不能机械回退到最近 complete 版本而忽略已交付的合格增量。
- SQL、提测分析等独立交付不能擅自改变用例覆盖结论。Python 负责历史身份唯一性、版本/来源关系、用例数量、变化账本和 Manifest 一致性，不负责业务匹配或编造退役理由。
- 正常增量流程不在设计前额外运行全历史 `validate`；`manifest.py publish` 在正式提交前完整校验全部历史文件 SHA-256、历史内容指纹、来源 Manifest 追溯和身份变化关系。发布后的 `manifest.py validate` 必须保留，完成包含新版本在内的最终全历史验签。
- 常用命令：
  ```powershell
  python -B skills/testcase-design/tools/manifest.py directory-name <需求编号> "<需求名称>" --module-id <module> --module-name "<moduleName>"
  python -B skills/testcase-design/tools/manifest.py inspect output/<module_directory_name>/<需求编号>-<需求名称>
  python -B skills/testcase-design/tools/manifest.py ids output/<module_directory_name>/<需求编号>-<需求名称> <需求编号> --count 3 --baseline-manifest output/<module_directory_name>/<需求编号>-<需求名称>/versions/<最新版本>/manifest.json
  python -B skills/testcase-design/tools/manifest.py validate output/<module_directory_name>/<需求编号>-<需求名称>
  ```

- `inspect` 每次调用只加载一次历史 Manifest，并核对全部历史有效用例指纹；相同 Markdown 路径只解析一次。`publish` 在需求级操作系统锁内只加载一次历史 Manifest，并复用已读取记录进行版本分配及发布后链路检查；`validate` 每次调用只加载一次历史 Manifest。上述复用只消除同一操作内重复扫描，不减少规定的历史指纹、来源链、身份连续性和全历史 SHA 校验。历史文件损坏、来源未登记或快照不一致时明确 FAIL，不自动修复、不覆盖历史。

## 正式版本发布

正式发布由 `manifest.py publish <需求归档根目录> <publish-spec.json>` 完成。spec 是临时输入文件，放在 `.qa-work/`，任务收敛后清理。示意：

```json
{
  "requirement": {
    "id": "<需求编号>",
    "name": "<需求名称>",
    "module_id": "<禅道 module>",
    "module_name": "<禅道 moduleName>"
  },
  "expected_base_version": null,
  "delivery_status": "complete",
  "artifacts": [
    {"category": "testcases", "role": "markdown", "source_path": ".qa-work/testcases.md", "path": "testcases/testcases.md"},
    {"category": "testcases", "role": "xmind", "source_path": ".qa-work/testcases.xmind", "path": "testcases/testcases.xmind"},
    {"category": "testcases", "role": "oracle", "source_path": ".qa-work/oracle.json", "path": "testcases/oracle.json"}
  ],
  "case_changes": {
    "added": ["QA-<需求编号>-<标识>"],
    "updated": [],
    "retired": []
  },
  "lineage": {},
  "retire_artifacts": []
}
```

- `source_path` 可使用工程内相对路径或绝对路径；`path` 相对当前版本目录，必须以对应 `category` 目录开头。
- 首次正式交付时全部用例自动从 Revision 1 建立；有历史版本但尚无历史用例时，也按首次出现处理。后续新增用例必须明确列入 `added`。
- 每份 publish spec 必须显式包含 `expected_base_version`：首次发布为 `null`，增量发布填写本轮 inspect 返回的 `latest_version`。发布器在需求级操作系统锁内重新读取历史，并核对 `expected_base_version` 与实际最新版本一致；不一致时拒绝发布，要求重新 inspect 和重建基于新基线的完整输入。锁内同时核对正式版本目录集合；提交前目录集合必须与已读取历史完全相同，提交后必须恰好等于历史集合加本次版本。这样可防止并发发布及不经过本工具的外部目录写入造成缓存历史遗漏。随后校验全部历史正式文件 SHA-256、每个历史 Manifest 的用例内容指纹及来源追溯，再检查当前有效产物清单和历史身份；任一历史证据损坏或不一致时，在创建临时版本目录前拒绝发布。只复制新增/更新文件，未变化文件继续引用旧版本。若无实质内容或交付状态变化，不创建新版本。
- 有效用例发布时，Markdown/Oracle 结构校验和 XMind 实际文件回读必须通过，三个 testcases 角色必须完整。SQL-only 或提测分析-only 版本沿用现有用例产物和身份快照，不复制、不清空。若明确退役全部有效用例，必须逐条提供真实退役原因，并在同一版本中退役 Markdown、XMind、Oracle 三个 testcases 角色；新 Manifest 保留全部退役身份及原因，历史版本文件永久保留，当前版本仍须至少保留一项其他正式产物。
- **发布前先完成 AI 语义自审和全部草稿修正**：逐项确认 Oracle 业务义务已落实为具体、可执行且可判定的用例；按实际风险检查枚举值逐项覆盖或有依据的等价代表、二值条件两种取值的结果、不同页面/查询入口的独立覆盖，以及跨时间/跨对象关联筛选中应保留和应排除的数据；同时检查用例分组、标题/前置条件/测试数据/步骤/预期的一致性及无依据假设。快捷查询不能替代通用查询，不同页面也不能仅因代码复用而推定覆盖。发现范围内重要义务未覆盖时，先修正临时草稿；若因来源缺证无法完成，明确影响并按真实限定范围判断是否部分交付，不得以 `complete` 隐藏缺口。所有正式候选文件和 publish spec 均在 `.qa-work/` 准备完成后再发布；不要先发布再进行本可在发布前完成的内部修正。上述为 AI 语义自审，不是 Python 自动门禁或业务验收 PASS。
- `xmind.py` 是 XMind 文件生成入口，生成时会回读刚写入的文件；`manifest.py publish` 又会对最终暂存副本执行 Markdown 解析、Markdown/Oracle 结构校验和 XMind 回读。因此正常流程无需在 publish 前单独运行 `artifacts.py` 重复检查；遇到结构错误时可单独运行它进行定位。发布器内的校验不得跳过。
- **一次完整正式交付任务最多产生一个成功的正式版本**。发布前失败且确认没有版本提交时，可以修复临时文件后重试；收到 `MANIFEST_PUBLISH_PASS` 后不得为同一任务的内部自审遗漏或排版修正再次调用 publish。发布成功后的 `manifest.py validate` 若失败，先核查并保留现场，报告阻断，不自动创建 v2/v3；只有后续真实业务变更或用户明确要求的独立正式修订，才创建新版本。
- 发布先在需求目录内的临时目录准备全部文件和 Manifest，完成校验后再原子重命名为正式版本目录；失败时只清理本次临时目录，不覆盖或删除任何历史文件。若回执明确提示“版本目录已发布但发布后回读验签失败”，先核对该版本目录，禁止盲目重试。
- 发布时间必须在发布前检查：新版本日期不得早于当前最新正式版本日期；同日的 `created_at` 不得早于最新版本时间。若不满足，必须在创建临时目录前拒绝，不能先原子发布再依赖回读发现错误。
- `complete` / `partial` 描述本次声明交付范围，不是业务语义 PASS/FAIL，也不是用户业务验收结论。`complete` 不证明覆盖或业务验收已通过；发布前已知的重要范围内覆盖缺口必须先修正，或在真实、明确的部分交付范围中列为未决。`partial` 不代表可以导入平台；当前模块不执行禅道/ACE 导入，不执行 SQL，也不承担业务语义验收。
- Agent 只在确认存在实质正式变更后调用发布；纯排版、空白、标点等不影响语义的调整不应创建正式版本。Python 不判断语义，AI 必须先完成该判断。

## 临时工作区

允许使用 `.qa-work/` 存放生成期间的临时草稿、publish spec 和中间转换数据。任务完成后清理本次临时文件及中间目录，不长期保留重复完整 JSON、调试产物或临时 Markdown。需求归档根目录同级的 `.qa-publish-<hash>.lock` 是跨进程发布互斥锁文件，必须长期保留且不属于正式 Manifest 产物，不得删除或清理。中断恢复时先核对实际状态，再续作并在任务收敛后清理。
