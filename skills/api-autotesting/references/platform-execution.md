# ZeroRunner 平台操作与执行

本文件承载 ZeroRunner Case 组织、MCP 使用、平台操作授权边界及正式报告回读规则。由 SKILL.md 按任务路由加载。

## ZeroRunner MCP 使用与执行边界

- ZeroRunner 是正式 Case 保存、请求执行、Step 结果、历史记录和正式报告的平台。使用前按当前 Agent 运行环境发现本项目配置的 MCP 服务，并读取本次所需工具的最新 Schema；服务配置名与工具名分开处理，具体发现及恢复规则见下文。不得硬编码 MCP 地址、凭据或某个 Agent 客户端 API。
- 只读查询 Case/Step、历史记录或查看报告原文时，不要求加载请求构造规则；创建/更新 Case/Step、Debug 或正式 Run 前，必须按入口路由实际读取 references/request-assertions.md，核对 UAT 目标、认证、请求契约和秘密保护后再操作。若需要判定报告结果，再加载 references/failure-diagnosis.md。

- 操作前先查询现有接口 Case/详情及必要历史记录，判断应复用、更新还是新增，避免重复创建。**默认一个 API Code 只维护一个当前有效的 ZeroRunner Case**，该 Case 收纳该接口所有有测试价值的场景 Step；不得按功能分组、参数类型、业务主题、调试批次或场景数量拆分多个 Case。
- 只有平台明确的硬性容量/执行限制，或同一 API 确实存在无法共用环境、认证或副作用安全边界的独立运行生命周期，且经用户确认后，才允许拆分；必须记录具体原因，不得仅因 Step 多或便于管理而拆分。
- 历史上同一 API 已拆出的多个 Case，优先选取已有稳定主 Case，合并仍有效的场景 Step；其他 Case 保留历史身份与执行报告，不删除历史。平台提供 Case 级停用/归档时按平台能力标记；若只支持 Step 级停用，则在用户授权后给历史 Case 名称加 `历史停用-` 前缀并禁用全部 Step，同时在本地台账明确 `enabled_flag` 可能仍为 true；不得声称 Case 级已禁用或物理归档。
- 本地接口索引中的当前/历史 Case 与 Step 字段结构、映射及维护规则统一由 references/archive-maintenance.md 负责；本次平台操作若需同步本地索引，必须在索引读取/写入前加载该文件。平台 Case/Step 本身的查询、组织和操作仍以本文件为准。
- Case 名称统一为 `{API Code}-{接口中文名称}`，不附加功能分组；Step 名称优先采用 `{业务字段Code}-{业务名称}-{场景行为/条件}`。无法对应单一字段时，用场景主题/业务对象描述，不虚构 Code。名称使用英文半角连字符 `-`，不放执行日期、版本、PASS/FAIL 或临时序号。
- 是否可直接执行必须看后端真实行为，不能只凭 POST 方法或接口名称判断。确认是无数据库写入、状态变更、任务触发、消息发送及其他外部副作用的只读查询接口时，按已确认决策可由 AI 直接维护并正式执行；发现副作用或无法判断时停止，说明影响和待确认事项，不按普通查询默认执行。
- `api_testcase_debug` 是同步调试，报告类型为 `report_type=20`，仅用于保存前验证或受控调试；不得把 Debug 当作正式执行或正式回归证据。
- 正式执行使用 `api_testcase_run(case_id, env_id?)` 触发 ZeroRunner 异步 Run；触发成功不代表用例通过。AI 必须继续通过 `api_testreport_list` 或 `api_testcase_get_latest_report` 查询并确认本次对应 Case 的新正式报告（`report_type=10`），核对可用的执行时间/模式/身份信息，再读取报告主信息、Step 明细和必要的单 Step 请求/响应详情。不能把历史报告误认成本次结果。

## MCP 服务发现与 Session 故障恢复

- **服务发现**：先读取可选本地 `config/organization-profile.json` 的 `integrations.api_testcase_mcp`；未配置时由用户/当前 Agent 实际提供的服务列表确认接口测试平台 MCP，不能假设所有环境使用同一名称。按已确认服务名定位已启用连接，再枚举实际工具及最新 Schema；服务配置名与工具名、客户端内部映射 ID/Runner ID 均需区分，不在通用 Skill 中固定连接地址、凭据、工具清单或参数。
- **错误分类**：
  - 服务未注册、已禁用或连接不可用：属于服务配置/连接层问题，不进入工具调用重试。
  - 工具不存在或参数 Schema 不匹配：重新发现工具并读取最新 Schema；不得归类为 Session 失效。
  - MCP 传输 Session 失效：只有错误明确来自 MCP/Streamable HTTP 协议层、且尚未形成正常工具结果时，才归为传输 Session 问题。
  - 平台业务 Session 失效：错误由工具正常返回，或出现在平台业务响应内容中时，归为业务会话/认证问题；按平台文档处理，不重建 MCP 连接。
  - 作用域不明：只看到 `Session not found` 文案、无法确认错误来源时，标记 `SESSION_SCOPE_UNKNOWN`，不得猜测属于哪一层。
- **传输 Session 恢复**：停止沿用失效 Session 的原请求；检查服务仍已注册、启用且可连接。仅使用当前 Agent 客户端明确支持的 MCP reconnect/reinitialize 能力重新建立会话；不得自行生成 Session ID、访问未公开端点或修改 MCP 配置。若客户端不提供恢复能力，明确报告并请用户在客户端重新连接 MCP，不转而要求用户手动点击 ZeroRunner Run。
- **恢复后探针**：重新建立连接后，重新枚举工具并读取本次所需工具的 Schema；只执行一次低成本只读探针（优先 list/get），确认工具可用后再继续。服务状态显示 healthy 不能单独证明旧 Session 仍有效；工具恢复成功也不代表平台业务 Session 已恢复。
- **业务 Session 处理**：仅按工具/平台文档明确提供的业务会话获取或续期流程处理。没有已记录的获取/续期方法时，停止并报告缺口，不把 MCP reconnect 当作业务 Session 修复。
- **不确定写操作结果**：创建/更新 Case/Step、Debug、正式 Run 等操作若在 Session 错误附近返回超时或结果不明，禁止直接重发。先用只读查询核对 Case/Step/报告/执行记录是否已产生；能确认已生效则继续后续只读步骤，能确认未生效且操作安全时才按授权重新执行；无法确认则标记 `UNKNOWN` 并停止。尤其不得因为 Run 报告暂时未出现而重复触发正式 Run。
- **重试上限**：一次故障最多执行一轮“检查→重连→重新发现→只读探针”。探针失败、恢复能力缺失或错误作用域不明时停止，不循环重试，不用本地 HTTP、脚本或 UI/Playwright 代替 ZeroRunner。
