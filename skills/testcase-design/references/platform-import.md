# 平台导入与目标匹配规则

## 触发与范围

- 只有用户明确提出“导入禅道”“导入 ACE”或“导入禅道和 ACE”才进入平台写入流程。明确导入请求本身就是本次对应平台写入授权，不再重复询问是否导入。
- 只选择当前需求最新有效的正式 Manifest 和 Markdown；按现有 Manifest 校验确认需求身份、版本、delivery_status、Case ID/Revision、Markdown 文件指纹及历史产物一致性。`partial`、`PARTIAL_DESIGN_READY`、草稿或非最新有效正式版本一律禁止导入。
- 导入只消费 testcases/testcases.md。Markdown 是唯一用例内容源；不得从 XMind 反向取数，不另造第二份权威用例 JSON，不重新分析/生成用例，不拉 Git，不生成 SQL。
- 禅道与 ACE 是两个独立适配器。用户要求两边都导入时，分别完成目标解析和写入，并分别返回结果；不能把一边成功推断为另一边成功。
- 平台写入、临时请求载荷和同步状态不得写入正式需求版本目录；不得修改历史 Markdown/XMind/Manifest。

## 需求来源身份与路径选择

导入前读取当前需求详情并核对来源身份，优先使用 getNeedDetailById 的真实返回字段：

- 需求：id、title
- 产品：product、productName
- 需求模块：module、moduleName
- 迭代：project、projectName
- 产品线/平台归属：productLine、productLineName
- 辅助路径信息：systemName

需求编号必须与正式 Markdown、Manifest 一致。当前需求详情中的模块或迭代与正式交付时冻结的来源不一致时，停止并重新核对，不得直接使用旧目标。

### 禅道目标

- 当前 createCasesByStoryId 的请求以 story 需求 ID 关联用例；模块、产品和迭代应以该需求当前真实关联信息为准。
- 创建接口当前 Schema 没有独立的 module、project 或目录路径参数，不得自行添加这些字段，也不得把 ACE 的 product_id/dir_id/project_id 传给禅道。
- 写入前核对需求的产品、模块、迭代名称及 ID；用例通过 story 关联到正确需求，不能只凭需求标题或相似名称选目标。

### ACE 目标

ACE 导入只需要取得正确的项目、目录路径以及需求/迭代关联信息，不要求额外建设目录导图清单查询。创建回执若包含明确成功状态和唯一 MindMap ID，按回执记录成功；若当前 MCP 回执仅返回 Schema 声明的 id/name/url、缺少成功状态，则使用唯一 ID 调用现有 get-mind-map 做一次只读回读，核对导图 ID、标题、产品 ID 和完整节点树。

必传关联字段：

- product_id：ACE 创建接口要求的项目 ID，取 ace_get_all_project 项目记录的 id 字段；不是该记录自身的 product_id 字段。
- dir_id：用户目标路径在 ACE 目录树中对应的目录 ID。
- project_id、project_name：禅道需求真实关联的迭代 ID、名称。
- story_id、story_name：禅道需求 ID、完整需求名称。

目标解析顺序：

1. 从禅道需求详情读取 project/projectName、module/moduleName、productLine/productLineName 等真实字段。
2. 从 ACE 当前项目/目录数据匹配业务归属和目标路径；目录路径明确时直接使用。
3. 如果无法获取或无法确定 ACE 目标路径，停止 ACE 导入并向用户说明无法确定保存路径，请用户提供完整路径；不猜测、不反复调用。用户提供路径后继续解析目录 ID 并导入。
4. 不要求用户重复提供可自动取得的需求名称、需求 ID、迭代名称或迭代 ID。
5. 需求关联信息缺失时，明确指出缺失字段；不伪造或猜测平台 ID。

## 权威内容到平台载荷

- 使用现有 artifacts.parse_markdown 解析正式 Markdown，保留业务分组、Case ID、优先级、前置条件、测试数据、步骤顺序和全部预期。
- Case ID 只用于本地同步映射，不写入平台用例标题、步骤或普通展示内容。
- 禅道按当前 MCP Schema 映射：story/title/pri/type/precondition/stepList；每个 Markdown 操作步骤对应一个 stepList 元素，每步的多个预期完整保留。当前 createCasesByStoryId 是单条用例创建接口，分组传输不等于平台批量 API。MCP 的 type 当前预览默认 feature；若要映射 interface/performance 等类型，必须先有明确来源规则，不能从分组名称猜测。
- ACE 优先级沿用当前适配器已有 P0–P4 映射；正常导入不再额外要求逐档 live 验真作为阻断条件。
- 禅道接口只有一个 precondition 字段时，前置条件和测试数据可合并，但平台页面已自带「前置条件」字段标题，因此 precondition 正文只传实际前置条件，不再添加「前置条件：」前缀；测试数据仍保留「测试数据：」标签以区分两类信息。不得丢弃其中任一内容。没有内容时不制造空前置条件。
- ACE 载荷由 `platform_payloads.build_ace_preview()` 从权威 Markdown 生成单张 MindNode；正常导入只调用新版内置 `tools/ace_cli.py` 执行一次 `zero-hub-cli ace-testcase import`。`get-mind-map` 仅按已知 ID 读取；正常创建回执已有明确成功状态和唯一 ID 时不额外调用，只有回执缺少明确成功状态但包含唯一 ID 时才用于兜底回读确认。CLI 使用参数数组、`shell=False`，导入载荷仅为单个 MindNode 根对象，临时文件在调用结束后清理。
- ACE 六项关联字段必须完整传递：`product_id`、`dir_id`、`project_id`、`project_name`、`story_id`、`story_name`。创建命令必须一次创建完整需求导图，不逐条创建、不拆批。

## 正常写入与结果返回

- 导入内容以正式 Markdown 为唯一权威来源；使用现有解析和平台载荷构建逻辑，不重新生成或改写用例内容。
- 禅道按现有 createCasesByStoryId 接口逐条顺序创建；ACE 按现有 CLI 一次创建完整需求 MindMap，不拆分。
- 写入时使用已取得的需求、迭代、ACE 项目及目录信息。若 ACE 路径无法确定，按「ACE 目标」章节询问用户提供路径后继续。
- 不要求导入前枚举 ACE 目录下所有 MindMap。创建接口明确返回成功及唯一 MindMap ID 时，按回执记录成功；若回执缺少明确成功状态但包含唯一 ID，则按 ID 只读回读一次，核对导图 ID、标题、产品 ID 和完整节点树后确认创建结果。回读未返回目录/迭代/需求关联字段时，将这些字段标记为 `NOT_PROVEN`，不得冒充已回读验证；这不影响对导图创建和内容的确认。
- ACE 创建明确成功且返回唯一 MindMap ID 后，即使本地临时目录清理失败，也保留 `SUCCESS` 和 ID，并附 `ACE_TEMP_CLEANUP_FAILED` 警告；清理异常不得覆盖创建失败或 `UNKNOWN_OUTCOME`，不得因此重试。
- 向用户汇总成功数量、失败数量及禅道 Case ID/ACE MindMap ID；失败项说明平台返回的原因。
- 对超时、断连或无唯一 MindMap ID 的写入，停止并报告 UNKNOWN_OUTCOME；不得自动重试或盲目重发。回执缺少成功状态但含唯一 ID 时，必须先按 ID 回读；回读失败报告带 MindMap ID 的 UNKNOWN_OUTCOME，内容或已返回关联信息不一致则报告 NEED_FIX，均不得重试。明确成功的记录不得再次创建。
- 不因缺少非必要的回读、目录导图枚举或额外验收证据阻断正常导入；不宣称执行过未实际进行的检查。

## 同步状态与轻量边界

- 内部 Case ID、禅道远端 Case ID、ACE MindMap ID/Node UID 分开记录；平台同步状态不得写入 Manifest 核心身份或 Markdown 正文。
- 不引入数据库；使用最小必要的文件化同步记录，记录平台、目标身份、冻结版本/载荷指纹、Case ID 与远端 ID、逐条状态及未知结果。同步记录放在正式需求版本目录之外，不保存第二份完整用例正文。
- 不迁移旧 Agent 的 SQLite 状态库、复杂宿主授权回调、临时单需求脚本或历史风险豁免。Zero Hub CLI 能力已在新版工程内独立实现；运行时只通过 PATH 或显式环境配置发现可执行文件，不读取、导入或调用其他 Skill 的文件。
- 平台适配器不可用或目标不唯一时，只阻断对应平台写入，不影响已完成的需求分析和正式用例设计。ACE 创建回执优先解析明确成功状态及唯一 MindMap ID；明确失败仍报告 `UNKNOWN_OUTCOME`。若成功状态缺失但存在唯一 MindMap ID，按 ID 回读核对；没有唯一 ID 或回读失败时报告 `UNKNOWN_OUTCOME`，不得自动重试。

## ACE CLI 接入与当前能力边界（2026-11-02 用户批准）

### 新版内置执行方式

- 新版独立维护 `tools/ace_cli.py`，不引用其他 Skill 的绝对路径、脚本或运行时目录；通过 PATH 中的 `zero-hub-cli` 或 `ZERO_HUB_CLI` 显式配置发现命令。
- 只读项目列表：`zero-hub-cli ace-testcase list-projects --json`。
- 只读目录树：`zero-hub-cli ace-testcase project-dir --project-id <ACE项目ID> --json`。新版将树展开为完整路径，目录匹配必须使用完整路径精确匹配；不以叶子名称猜测。
- 只读回读：`zero-hub-cli ace-testcase get-mind-map --case-id <MindMapID> --json`。正常回执明确成功时不额外调用；回执缺少成功状态但包含唯一 ID 时，必须调用一次确认导图是否存在及内容是否一致。
- 创建完整需求导图：`zero-hub-cli ace-testcase import --case <单根MindNode JSON> --title <需求名称> --product-id <ACE项目ID> --dir-id <目录ID> --project-id <真实迭代ID> --project-name <真实迭代名称> --story-id <需求ID> --story-name <完整需求名称> --json`。
- Python 使用参数数组、`shell=False` 和临时单根 MindNode 文件；不拼接 Shell 命令，不保存第二份权威用例 JSON，不把临时文件放进正式需求版本目录。
- ACE 导入只保留必要的来源检查：使用最新正式 Manifest，要求 delivery_status=complete，需求 ID/名称与 Markdown 一致，Markdown 文件与 Manifest 指纹一致；不额外做多层签名或重复完整性证明。
- 目标解析只需要 ACE 项目 ID 和目标目录 ID/路径；不要求枚举目录下已有 MindMap。自动无法确定保存路径时，直接向用户询问完整 ACE 路径，用户提供后继续。
- 优先级使用当前已配置的 P0–P4 映射，不因缺少额外 live 验真而阻断正常导入。
- 创建前再次确认正式 Manifest/Markdown 未变化；随后只调用一次 ACE import 创建完整需求 MindMap。创建接口明确返回成功和唯一 MindMap ID 时直接记录成功；若回执只有唯一 ID、缺少成功标志，则调用一次 get-mind-map 回读，核对 ID、标题、产品 ID 和完整节点树。回读缺少目录/迭代/需求关联字段时如实标记 `NOT_PROVEN`，不把缺失字段冒充 PASS。
- 创建超时、断连或无法解析唯一 MindMap ID 时返回 UNKNOWN_OUTCOME，禁止自动重试或盲目重发；回执缺少成功标志但包含唯一 ID 时，先回读确认，回读失败仍返回 UNKNOWN_OUTCOME 并保留该 ID。

### 已在新版执行环境完成的只读验证

- `zero-hub-cli` 可通过 PATH 发现；`list-projects` 成功返回项目列表。
- `project-dir --project-id <ACE项目ID>` 成功返回完整目录树；可按完整路径解析目标目录。目录返回的 `mind_count` 仅为计数信息，不能作为导图清单。
- `get-mind-map --case-id <MindMapID>` 曾成功按已知 ID 回读 id、name、product_id、version 和完整 content.root；该记录只证明按已知 ID 的只读查询能力可用，不代表正常导入会自动回读。
- 本轮没有调用 ACE 创建、补丁、删除或 UI 执行命令；只读集成验证不等于真实写入验收。
- 2026-11-02 实时 MCP 复核：ace-testcase 当前暴露项目列表、目录树、按已知 MindMap ID 回读及创建/更新能力；没有按目录列举或搜索 MindMap 的只读工具。`get_project_dir` 返回目录结构和 `mind_count`，不能作为真实导图清单。

### 简化后的实际导入规则

- 当前 ACE MCP/CLI 没有按目录枚举或按名称搜索 MindMap 的只读工具；这不阻断正常导入。目录树能解析目标目录时直接使用；不能确定路径时询问用户提供完整路径。
- 正常导入只要求六项关联字段正确、正式 Markdown 来源有效以及用户明确提出导入。无需提供 directory_inventory，也无需单独证明目录下已有导图清单完整。
- 使用当前 P0–P4 优先级映射生成 MindMap；不再要求单独的优先级 live 验真门禁。
- 创建接口明确返回成功及 MindMap ID 后，向用户报告成功数量和 MindMap ID；若成功状态缺失但 ID 唯一，则只在该分支执行一次整棵树回读与内容核对。回读缺失的关联字段标记 `NOT_PROVEN`，不扩大为额外导入门禁。
- 结果不明时停止并报告，不自动重试；其余情况按正常导入流程完成。
