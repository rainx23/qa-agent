---
name: api-autotesting
description: 以 AI 为决策主体，基于前后端源码发现接口隐藏场景、建立和维护覆盖基线并保护历史回归；按需识别真实业务数据准确性验证。
---

# API Autotesting（接口自动化）

## 能力定位与边界

- 本 Skill 是独立、按需触发的接口自动化能力，负责接口身份识别、源码分析、场景与断言设计、覆盖审查、增量影响判断、ZeroRunner 协作及结果分析。
- 一期定位是**源码驱动的隐藏场景发现与持续回归保护**，不是只验证一个成功请求的接口冒烟，也不是重复人工页面测试。
- AI 负责业务理解和所有测试决策；Python/Node 与 MCP 只提供可复核事实或执行能力。不得把业务规则、场景选择、参数组合和覆盖判断固化成脚本规则。
- 本能力不替代 P1 测试用例设计、P2 代码影响分析、P3 SQL 设计或 P4 知识管理；它们均不是强制前置。相关产物可作为线索或证据，但 AI 必须独立核对当前接口和源码。
- 若接口自动化任务同时处于 P2 开发提测影响分析流程，P2 对真实业务数据验证目标的 F+V SQL 义务仍按 P2/P3 规则执行；本 Skill 所述 P3 非前置，仅表示接口自动化不要求先完成独立 P3 任务，不覆盖 P2 专属规则。
- 一期不以真实业务数据准确性为通用前置条件。需要真实记录、独立数据 Oracle 或金额/数量/过滤/聚合结果核验时，按 references/data-validation.md 的二期边界识别，不得用接口成功代替数据正确。
- 只读源码分析、场景设计与覆盖审查不等于平台执行或业务验收；必须明确区分已设计、已保存、Debug、正式 Run、真实数据验证等证据状态。

## 自然语言任务识别

先结合用户当前表达和对话上下文，判断本次目标、接口范围、目标环境和已有基线，再识别接口生命周期。不要要求用户使用固定命令或填写模式表单。

- **新增接口**：用户提供 API Code/路由/接口标识，或需求、P2/P3 线索及源码变化提示可能新增接口。AI 核实前后端实现、真实路由/API Code、本地索引和 ZeroRunner 现有 Case，区分真正新增、已有接口改名/封装/版本变化及重复登记；不能仅凭新文件或新方法认定新接口。
- **存量接口首次初始化**：接口已经存在，但本地没有可信的自动化覆盖基线。首次初始化必须独立分析前端实际调用与后端实际处理，建立全部有测试价值的场景基线；不依赖用户提供人工测试记录，也不假设某参数以前已经测过。
- **已有接口增量更新**：接口已有覆盖基线，本次需求或代码变化可能影响接口行为。对照已记录源码 SHA 与本次目标版本，结合前后端差异、调用/依赖关系、历史场景和可用需求线索，判断新增、更新、保留、退役及需复核的场景，并决定回归范围。
- 同一任务可能包含多个接口或多种生命周期；由 AI 按真实接口身份分别判断。接口身份或关键基线无法确认时，说明证据缺口，必要时只询问最关键的信息，不猜测。

## 强制规则加载与按需路由

SKILL.md 是唯一入口；references 是分职责规则正文。每次执行任务都必须先读取本文件，再按下表实际读取所需 references。不得仅凭历史记忆、文件名或目录存在就声称已加载规则；不得默认一次性读取全部 references。

| 当前任务 | 必须读取的 references |
|---|---|
| 新接口初始化 / 存量接口首次初始化 | references/source-analysis.md、references/scenario-design.md、references/request-assertions.md、references/archive-maintenance.md |
| 已有接口增量更新 | references/source-analysis.md、references/scenario-design.md、references/request-assertions.md、references/archive-maintenance.md |
| ZeroRunner 只读查询（Case/Step、历史记录、报告原文查看） | references/platform-execution.md；若需判定或复盘执行结果，再读取 references/failure-diagnosis.md |
| ZeroRunner Case/Step 创建或更新、Debug、正式 Run | references/platform-execution.md + references/request-assertions.md；若需判定或复盘执行结果，再追加 references/failure-diagnosis.md |
| 通用失败诊断 / 参数、操作符支持性判断 / 人工核对分流 | references/failure-diagnosis.md；涉及请求契约时追加 references/request-assertions.md；需要追踪前后端实现时追加 references/source-analysis.md；若需从平台读取报告，再追加 references/platform-execution.md |
| 跨接口影响分析 | references/failure-diagnosis.md + references/source-analysis.md；需要设计/调整回归场景时再追加 references/scenario-design.md |
| 诊断经验沉淀 | references/failure-diagnosis.md；若同步更新接口 JSON/本地索引，再追加 references/archive-maintenance.md |
| 真实业务数据准确性验证 | references/data-validation.md，并按需读取 references/source-analysis.md、references/request-assertions.md |
| 本地接口索引/项目索引/历史 Case-Step 映射查询、维护或产物归档 | references/archive-maintenance.md |
| 平台操作同时更新本地索引或历史映射 | references/platform-execution.md + references/archive-maintenance.md；若还涉及 Case/Step 创建或更新、Debug、正式 Run，再同时加载 references/request-assertions.md |
| 组合任务 | 读取各任务对应文件的并集，只加载本次真正需要的规则 |

- 先根据本次任务确定实际动作，再按路由计算必需 references 的并集；每份必需文件必须在对应分析、平台操作、结果判定或本地文件读写前实际读取。若某个必需文件不存在、读取失败或内容不完整，停止受影响的部分，明确报告 API_AUTOTEST_RULES_NOT_LOADED 和缺失路径；不得回退为凭记忆执行。其他不依赖该文件的工作可以继续，并明确范围。
- failure-diagnosis.md 与 archive-maintenance.md 是对应动作的前置依赖，不是事后补加载项：判定执行结果前读取 references/failure-diagnosis.md；查询/修改本地索引或归档前读取 references/archive-maintenance.md。任务中途新增相关动作时，先补读对应规则再操作；事后补读不能追溯证明此前操作遵循规则。
- references 文件之间不得复制维护同一套权威规则；如发现冲突，先按用户本次明确指令及最新业务来源核实，再以本 Skill 和按需加载的 references 为可移植执行依据。个人决策记录（如有）只用于本地工程维护，不是其他用户运行接口自动化的前置条件。

## 核心执行边界

- AI 自主负责业务理解、接口身份、场景选择、参数组合、断言设计、覆盖判断、影响分析和结果解释；确定性工具只提供可复核事实、文件处理及执行能力。
- 请求构造、UAT 环境、认证和敏感信息处理遵循 references/request-assertions.md；ZeroRunner 只读查询和报告读取遵循 references/platform-execution.md；创建/更新 Case/Step、Debug 或正式 Run 前必须实际加载 references/request-assertions.md；若同步维护本地索引，写入前还必须加载 references/archive-maintenance.md。
- 不得擅自修改业务代码、执行生产 SQL 或 Push；平台写操作必须遵循用户授权和业务副作用边界。
- 真实业务数据准确性按 references/data-validation.md 独立判断，不以接口执行成功代替数据正确。
- 执行状态、覆盖状态、根因状态和业务验收状态是不同维度，不得混用；失败诊断先核对测试请求、场景触发、预期依据和环境，再判断是否为业务缺陷。
- 参数/操作符是否支持缺乏充分源码、配置或契约证据时，按 failure-diagnosis.md 标记 MANUAL_VERIFY 并转人工核对，不猜测、不为追求请求成功擅自篡改契约，也不无证据重复 Debug。
- 发现共享组件/公共方法/公共配置可能影响多个接口时，按需追踪实际调用方；只沉淀已确认的通用经验，单接口特例留在接口自身产物。

## 交付要求

交付内容按本次任务类型和实际范围选择，不要求每次都提供所有维度：源码分析/场景设计任务说明接口身份、相关源码证据及 SHA、场景和覆盖结论；平台维护/执行任务说明 Case/Step 计划或实际关联、授权边界及真实执行结果；失败分析说明判定、证据和根因状态；索引/归档任务说明本次索引对象、映射变更、文件路径及验证状态。只维护索引或归档时，不要求补充无关源码证据、场景覆盖、请求断言或执行报告。简要结论优先，详细证据按需提供。
- **需求增量的强制速览**：每次已有接口的需求增量更新完成后，除总体结论外，必须告诉用户本次实际新增了哪些场景；逐条列出新增场景名称及一句话验证目的，并区分仅设计、平台已保存、Debug 成功、正式 Run 结果。若有 UPDATE/RETIRE/REVIEW，也简要列出实际变更；不得把计划新增混入已完成清单。同步生成需求版本内的 `api-automation/scenario-change-summary.md`，记录本次实际变更、接口/Case 版本、Step 映射和证据状态；聊天回复提供可快速浏览的新增场景速览及文件路径。若本次没有新增场景，明确写“本次无新增场景”，不得省略该项。

具体源码分析、场景设计、请求断言、ZeroRunner 操作、失败判定、数据验证和归档要求，分别以本文件路由的 references 为准。
