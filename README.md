# QA Agent｜AI 驱动的测试工程

> 一个面向软件测试全流程的跨 Agent QA 工程。由 AI 负责业务理解、测试分析与测试决策，以 Markdown/JSON 维护可复用规则和产物，以轻量 Python、Git CLI 与外部 MCP 提供必要的确定性处理和执行能力。

**它不是一个需要启动 Web 服务的测试平台，而是一套可由 ChatGPT、Codex、CodeBuddy 等 Agent 共同读取和执行的测试能力工程。**

版本更新记录见 [CHANGELOG.md](CHANGELOG.md)；本地实施与验收原始日志不纳入公开仓库。

## 1. 项目主要做什么

QA Agent 将需求理解、测试设计、开发变更分析、数据核验、知识沉淀和接口自动化连接起来，帮助测试人员减少重复分析，发现容易遗漏的业务风险，并持续复用已确认的测试知识：

- **理解需求（P1）**：识别业务目标、规则、流程、数据口径和待确认事项。
- **设计测试（P1）**：从业务义务出发设计可执行、可判定的测试用例，并维护正式版本。
- **分析变更（P2）**：结合需求、实际代码和调用链，识别实现缺口、额外行为、影响范围和回归重点。
- **核验数据（P3）**：按独立业务预期设计只读 SQL，帮助定位真实样本并核对数据结果。
- **积累知识（P4）**：把已确认的业务规则、页面、接口、配置、数据入口和质量经验沉淀为可复用知识。
- **保护接口回归（P5）**：从前后端源码发现隐藏场景，建立接口覆盖基线，并在后续变更中维护和回归。

## 2. 能力地图：P1–P5

| 编号 | 能力 | 主要职责 | 常见触发方式 |
|---|---|---|---|
| **P1** | `testcase-design` 测试用例设计 | 需求分析、独立 Oracle、测试场景与用例设计、增量维护、Markdown/XMind 交付 | “分析这个需求”“根据需求设计正式测试用例” |
| **P2** | `code-impact-analysis` 代码影响分析 | 开发提测影响、BUG 根因、无需求代码变更分析，以及独立授权的 Bug 提交/回归/关闭 | “开发已提测，帮我分析影响”“排查这个问题” |
| **P3** | `sql-design` SQL 设计 | 识别必要的数据验证目标、找真实样本、按独立预期设计只读 SQL、按需协助 P2 | “为这个需求设计找数和验证 SQL” |
| **P4** | `knowledge-management` 知识管理 | 按需检索业务知识；在用户明确要求时发现、去重并增量维护知识 | “查询这个模块已有知识”“补充这个页面的业务规则” |
| **P5** | `api-autotesting` 接口自动化 | 源码驱动的隐藏场景发现、接口覆盖基线、增量更新、平台执行与回归结果分析 | “为这个接口初始化自动化”“分析接口变更并更新回归” |

> **P5 正式定位**：接口自动化是独立测试能力，拥有自己的 Skill、接口生命周期、项目级索引、需求关联归档和执行结果分析职责。它与 P1–P4 并列；P1–P4 仅作为按需辅助输入，不是 P5 的强制前置。

**编号代表能力分类，不代表必须依次执行的流水线。** 所有能力均可按当前任务独立触发：普通需求分析只需要 P1；开发提测分析走 P2；只有存在真实数据验证目标时才按需调用 P3；P4 是可选知识辅助；P5 可以独立开展接口自动化，无需先完成 P1–P4。

## 3. 整体架构与工作方式

```text
用户自然语言 / 需求材料 / 代码变更 / 接口信息
                    │
                    ▼
             AGENTS.md 全局入口
          识别任务意图，选择对应能力
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
      P1–P4         P5        按需辅助能力
    独立 Skill   接口自动化    P4 知识 / P3 SQL
        │           │           │
        └───────────┼───────────┘
                    ▼
        SKILL.md + 按任务加载 references
                    │
                    ▼
       AI 业务分析与测试决策（核心）
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
   Python 工具    Git CLI     外部 MCP
  确定性处理     代码证据     平台查询/执行
       └────────────┼────────────┘
                    ▼
       正式产物 / 知识 / 临时工作材料
```

### 核心设计原则

1. **AI-first**：需求理解、业务规则判断、场景选择、Oracle、影响分析和结果归因由 AI 负责；不把业务判断固化成大量脚本规则。
2. **Markdown-first**：全局规则、Skill 入口、工作流和业务说明以普通 Markdown 表达，便于不同 Agent 阅读、审查和维护。
3. **按需加载**：`AGENTS.md` 负责全局约束和能力路由；每个 Skill 通过 `SKILL.md` 作为唯一入口，再根据任务读取必要的 `references/`，不默认加载所有规则。
4. **工具只做确定性工作**：Python 处理文件、JSON、哈希、格式和结构校验等必要任务；Git 提供代码版本与差异证据；MCP 提供外部平台能力。工具不替代 AI 做业务决策。
5. **跨 Agent 可移植**：不依赖某个 Agent 的专有 API、插件、界面组件或自动 Skill Runtime。只要 Agent 能读取工程文件并具备所需工具权限，就可以按同一套规则工作。
6. **质量与证据分层**：设计完成、工程校验通过、平台保存、Debug、正式 Run、数据库执行和业务验收是不同状态，不能相互替代。

## 4. 技术框架与技术栈

本仓库采用轻量的 **Markdown + JSON + Python 工具** 结构，而不是传统前后端应用框架。

| 层次 | 使用方式 | 说明 |
|---|---|---|
| Agent 规则层 | Markdown、YAML front matter | `AGENTS.md` 负责全局路由；各 Skill 的 `SKILL.md` 定义职责、触发条件和执行方法 |
| 规则细节层 | Markdown `references/` | 按任务加载源码分析、场景设计、断言、平台执行、归档等细则 |
| 配置与索引层 | JSON | 保存本地仓库映射、组织可选配置、Manifest、接口索引和知识条目 |
| 确定性工具层 | Python 3.11+、标准库优先 | 处理文件、JSON、哈希、Manifest、结构检查等必要工作；不承担业务测试决策 |
| 代码证据层 | Git CLI | 仅在代码相关任务中按需获取分支、Commit、Diff 和源码证据；普通需求分析/用例设计不默认 Fetch |
| 外部执行层 | 当前 Agent 环境已连接的 MCP | 按需连接需求、缺陷、用例管理或接口测试平台；MCP 不随仓库自动安装或获得授权 |
| 产物层 | Markdown、JSON、SQL、XMind | 根据任务生成相应交付，不强制每种任务都产生所有格式 |

**不需要启动 FastAPI、Vue 或其他 Web 服务，也没有内置数据库、向量库、调度器或独立测试执行平台。** Agent 的模型推理和外部平台连接由使用者当前的 Agent 客户端及其授权环境提供。核心 Python 工具以标准库为主，仓库没有统一的前后端依赖安装流程。

### 常见术语

- **Oracle（独立业务预期）**：来自需求、产品规则或用户确认的判断依据，用来判定实际结果；不能从被测结果或用例预期反推。
- **Manifest**：需求版本清单，记录正式产物及其路径、身份和校验信息，用于支持增量维护与历史保护。
- **MCP**：Agent 与外部平台工具的连接方式；本仓库描述按需使用边界，不包含账号、密钥或服务部署。
- **Case / Step**：接口测试平台中的测试用例及其执行步骤。

## 5. 典型任务怎么工作

### P1｜需求分析与测试用例设计

1. 从用户提供的需求正文、附件或可用需求来源获取业务事实（含正文与备注）。
2. 识别业务目标、规则、操作流程、数据逻辑和待确认事项。
3. 用户只要求分析时输出分析结论；明确要求设计用例时，先建立独立 Oracle 再设计正式用例。
4. 按需生成 Markdown、XMind 和 Manifest，维护用例身份及增量版本，并在聊天末尾给出可选的 P4 知识沉淀建议。

### P2｜开发提测与代码影响分析

1. 根据任务类型选择开发提测、BUG 根因、代码变更、Bug 提交或 Bug 回归与关闭工作流。
2. 代码相关分析按实际目标获取相关仓库的最新代码证据，核对需求与实际实现、调用方和数据链路。
3. 识别实现缺口、额外行为、潜在影响和必要回归范围；能由源码证明的尽量先完成静态分析。
4. 开发提测分析存在必要数据验证目标时按规则委托 P3；完成后在报告末尾给出可选的 P5 接口自动化维护建议。
5. Bug 提交、关闭等平台写操作是独立动作，必须逐条预览并取得绑定当前 Draft ID 的明确人工授权后才执行。

### P3｜SQL 设计与数据验证

1. 从需求、正式用例、P2 变更证据及按需知识中识别必要的数据验证目标。
2. 为每个目标建立真实样本（F）与独立预期（V），核对对象粒度、有效条件、关联关系和计算口径，按来源、粒度与核心计算组织只读 SQL。
3. 输出只读 SQL 与场景清单（独立需求 SQL 默认交付工作稿，明确要求当前稿正式归档时才发布），供用户在获准环境手动执行并回传结果后对照判定。

### P4｜知识检索与增量维护

1. 根据模块、业务对象、页面/Tab、接口或字段定位相关知识，按问题只读取必要的 1–2 类 JSON。
2. 严格区分已确认知识（`formal_reusable`）、候选内容、待复核内容和未知信息。
3. 仅在用户明确要求维护知识或明确批准 P1 候选入库时，才执行发现、去重、局部更新和写后回读。

知识按业务模块维护于 `knowledge/modules/<业务模块>/`，六类常用文件覆盖业务规则（`business-rules.json`）、页面功能（`pages-functions.json`）、交互字段（`interactions-fields.json`）、接口配置（`interfaces-configs.json`）、代码/数据定位（`code-data-locator.json`）和质量经验（`quality-experience.json`）。知识库不可用或未命中时不阻断主任务。

### P5｜接口自动化

1. 识别新增接口、存量接口首次初始化、已有接口增量更新或日常回归。
2. AI 独立分析前端请求组装、后端参数处理、共享逻辑和调用关系，发现隐藏场景及有价值的参数组合。
3. 建立源码与自动化场景的双向覆盖关系，维护项目级覆盖索引与需求关联变更摘要。
4. 需要平台操作时，通过已连接且获授权的接口测试 MCP 维护 Case/Step、Debug、正式 Run，并回读真实执行证据。
5. 一期重点是源码驱动的场景发现与持续回归保护；只有真实业务数据准确性确实属于目标时，才按需进入二期数据验证。

## 6. 如何开始使用

### 第一步：准备环境与工程

1. 确保本地已安装 **Python 3.11+**（运行确定性校验工具与单元测试）和 **Git**（代码相关分析取证）。
2. 将本仓库克隆到本地工作目录。
3. 在 ChatGPT、Codex、CodeBuddy 等使用环境中授权 Agent 读取该仓库；若要分析业务代码，同时授予相应业务仓库的只读访问权限。
4. 让 Agent 先读取仓库根目录 `AGENTS.md`，再根据任务意图加载对应 `skills/<skill-name>/SKILL.md`（不依赖特定客户端的自动 Skill Runtime）。

### 第二步：按需准备本地配置

**零配置也可直接开始使用**：不创建本地配置文件时，直接在对话中提供本地仓库路径、分支或环境约定即可；创建后可免去每次重复说明。若需要自动定位仓库或组织级约定，可从示例文件复制创建（已存在时不要覆盖）：

```powershell
if (-not (Test-Path config/repositories.json)) {
    Copy-Item config/repositories.example.json config/repositories.json
}

if (-not (Test-Path config/organization-profile.json)) {
    Copy-Item config/organization-profile.example.json config/organization-profile.json
}
```

- `config/repositories.json`：按需登记可访问的业务工作区、仓库路径和 remote，供代码相关任务定位源码。
- `config/organization-profile.json`：按需填写本组织已确认的分支基线、配置证据来源、SQL 方言、MCP 集成标识与 Bug 默认值。
- 配置值必须来自真实环境和已确认事实，不要猜测分支、环境、表前缀或工具名称；认证信息应由 Agent 客户端或私有安全配置提供。

### 第三步：连接任务需要的外部能力

MCP 是可选的外部能力，不是仓库自带服务。只有任务依赖需求平台、缺陷平台、用例管理、接口测试、配置或血缘查询时，才需要连接对应 MCP。

| 任务 | 是否必须连接外部平台 |
|---|---|
| 使用完整需求正文做 P1 分析/用例设计 | 不必须 |
| P2 代码影响分析 | 需要业务源码访问；其他 MCP 按证据缺口选用 |
| P3 SQL 设计 | 不需要数据库连接；用户自行在获准环境执行 SQL |
| P4 知识检索/维护 | 使用本地知识文件即可，不依赖向量数据库 |
| P5 源码分析/场景设计 | 需要相关前后端源码访问；Case/Step 维护、Debug、Run 需要已连接且获授权的接口测试 MCP |

### 第四步：直接用自然语言提出任务

不需要记固定命令，也不需要填写复杂参数表。尽量提供当前已知的需求、接口、代码分支或异常现象；缺少的信息由 Agent 根据实际影响再判断是否询问。

```text
# 首次发起任务示例
分析这个需求，先告诉我业务目标、关键规则和待确认事项。

根据下面的需求设计正式测试用例，并完成必要的产物校验。

需求 123456 已经提测，提测点是订单列表筛选和汇总逻辑，帮我分析代码影响。

根据这个需求的真实数据场景设计找数和验证 SQL，不要执行数据库。

检索【示例模块】已有知识；如果发现确实缺少且值得复用的规则，再帮我补充。

为接口 example.api.list 初始化接口自动化，分析前后端源码并建立覆盖基线。

本次接口变更影响了哪些历史场景？请分析增量并给出需要回归的范围。

# 后续确认与连续推进示例
同意将第 1、3 条建议知识入库。

开始逐条验证，先看第 1 条 MV 和对应 SQL。

确认提交 BUG-DRAFT-123456-20261115-1

确认维护 P2 报告中建议的第 1 个接口自动化。
```

## 7. 产物放在哪里

### 需求关联的正式产物

```text
output/
└── 【<禅道 moduleName>】/
    └── <需求编号>-<原始完整需求标题>/
        ├── versions/
        │   └── <YYYYMMDD-vN>/
        │       └── manifest.json
        ├── testcases/
        │   └── <YYYYMMDD-vN>/
        ├── analysis/
        │   └── <YYYYMMDD-vN>/
        ├── sql/
        │   └── <YYYYMMDD-vN>/
        └── api-automation/
            └── <YYYYMMDD-vN>/
```

- 一级模块目录使用禅道需求详情真实 `moduleName`，外层统一添加 `【】`（例如 `【销售结果】`）；首次归档前按 `skills/testcase-design/references/output-archive.md` 校验需求 ID、模块 ID 和模块名称。不得从需求标题括号推断模块；模块信息缺失时停止创建目录。
- 需求目录保留原始完整标题，不擅自删除括号或改写名称。
- `versions/<版本>/manifest.json` 是该需求的版本与正式产物索引。
- `testcases/`、`analysis/`、`sql/`、`api-automation/` 只在对应类型有正式产物时创建，不预建空目录；同一需求共用版本序列，历史版本通过 Manifest 延续引用，不覆盖历史文件。
- 已登记 Bug 的回归与关闭回执存放在对应需求或任务目录下的 `analysis/bug-lifecycle/BUG-<BugID>/`。
- **无需求编号**的独立 BUG 根因排查与代码变更分析，归档至 `output/impact-analysis/BUG-<主题>-<YYYYMMDD>/vN/` 或 `CODE-<主题>-<YYYYMMDD>/vN/`。

### 接口自动化项目级索引

```text
output/api-automation/
├── index.json
└── interfaces/
    └── <API Code>.json
```

项目级 `index.json` 和每接口 JSON 维护当前有效接口基线；与具体需求绑定的分析/设计/变更速览进入该需求版本下的 `api-automation/`。平台请求、响应、Step 日志和完整执行报告由对应平台保存，本地只保留必要的身份、源码 SHA、覆盖状态和证据引用。

### 其他目录

| 目录 | 用途 | 是否正式业务交付 |
|---|---|---|
| `skills/` | Skill 入口、规则 references、确定性工具和自动化测试 | 否，属于工程能力本身 |
| `knowledge/modules/` | 按业务模块组织的可复用知识 | 是，属于知识资产 |
| `.qa-work/` | 草稿、临时分析、验证工作稿和发布准备材料 | 否，不作为正式交付目录 |
| `platform-sync/` | 按需保存平台同步回执的通用规则与记录位置 | 仅回执，不替代正式产物 |
| `implementation/`、`artifacts/` | 本地工程实施与审查资料 | 否，不是公开 Skill 的运行依赖 |

## 8. 工程测试与结果判定

在仓库根目录使用 Python 3.11+ 执行自动化测试（P4 `knowledge-management` 当前为纯规则文档，暂无独立单元测试脚本）：

```powershell
# 一键运行全仓全部 Skill 单元测试（PowerShell）
Get-ChildItem skills\*\tests -Directory | ForEach-Object {
    python -B -m unittest discover -s $_.FullName -p "test_*.py"
}

# 或按单个 Skill 分别运行：
# P1：测试用例设计与 Manifest/XMind/ACE 等工具
python -B -m unittest discover -s skills/testcase-design/tests -p "test_*.py"

# P2：代码影响分析与 Bug 归档工具
python -B -m unittest discover -s skills/code-impact-analysis/tests -p "test_*.py"

# P3：SQL 结构、Manifest 与数据场景工具
python -B -m unittest discover -s skills/sql-design/tests -p "test_*.py"

# P5：接口自动化工具
python -B -m unittest discover -s skills/api-autotesting/tests -p "test_*.py"
```

这些测试只证明对应自动化测试覆盖范围内的工程行为。实际交付还必须严格区分以下五个状态层：

- **设计完成**：AI 已完成对应范围的需求、场景、Oracle 或 SQL 设计。
- **工程校验通过**：脚本、格式、Manifest 或自动化单元测试通过。
- **平台操作完成**：平台真实返回并按规则回读确认保存/更新结果。
- **实际执行完成**：Debug、正式 Run 或数据库查询有真实执行证据。
- **业务验收完成**：用户或授权验收方确认业务结果符合预期。

某一层通过不能自动推导下一层通过；未执行或证据不足时应保留 `NOT_RUN`、`UNKNOWN`、`BLOCKED` 或 `NOT_VERIFIED` 等真实状态。

## 9. 安全与公开发布边界

- 不得擅自修改业务仓库代码、写入业务数据、执行生产 SQL、导入/修改平台记录或 Push。
- SQL 默认只读，由用户在获准的数据库环境手动执行；任何平台写操作必须遵循对应 Skill 的预览、人工授权与回读规则。
- 普通需求分析和 P1 用例设计不默认 Git Fetch；代码相关任务才按需获取源码和远端版本证据。
- `.gitignore` 会保护本地 `output/`、`.qa-work/`、`implementation/`、`artifacts/`、真实本地配置、个人决策/实施日志和用户业务知识等内容；公开仓库只保留可复用规则、代码、示例配置和合成测试材料。
- **Git 忽略规则不能保护手动压缩整个目录的行为。** 对外提供 ZIP 或审查包时，必须从允许发布的文件清单重新组包并检查内容，不要直接压缩整个工作目录。

## 10. 从哪里继续了解

- 全局规则和能力路由：[`AGENTS.md`](AGENTS.md)
- 测试用例设计（P1）：[`skills/testcase-design/SKILL.md`](skills/testcase-design/SKILL.md)
- 代码影响分析（P2）：[`skills/code-impact-analysis/SKILL.md`](skills/code-impact-analysis/SKILL.md)
- SQL 设计（P3）：[`skills/sql-design/SKILL.md`](skills/sql-design/SKILL.md)
- 知识管理（P4）：[`skills/knowledge-management/SKILL.md`](skills/knowledge-management/SKILL.md)
- 接口自动化（P5）：[`skills/api-autotesting/SKILL.md`](skills/api-autotesting/SKILL.md)

**使用建议**：先读本 README 了解全貌，再读 `AGENTS.md` 和本次任务对应的 Skill。不必一次性学习所有 references；Agent 也应遵循同样的按需加载原则。